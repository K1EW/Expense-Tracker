#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import tempfile
import uuid
from datetime import date
from decimal import Decimal, InvalidOperation
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

import pandas as pd

TABLE_FIELDS = {
    "categories": ["id", "name"],
    "subcategories": ["id", "name", "category_id"],
    "transactions": [
        "id",
        "date",
        "amount",
        "category_id",
        "subcategory_id",
        "note",
    ],
}


class APIError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


class CSVStore:
    """Read and write the API's CSV tables with pandas DataFrames."""

    def __init__(self, directory: Path):
        self.directory = directory
        self.directory.mkdir(parents=True, exist_ok=True)
        for table, fields in TABLE_FIELDS.items():
            path = self._path(table)
            if not path.exists():
                self._write(table, pd.DataFrame(columns=fields))

    def _path(self, table: str) -> Path:
        return self.directory / f"{table}.csv"

    def _read(self, table: str) -> pd.DataFrame:
        """Load table values as strings and preserve empty cells."""
        frame = pd.read_csv(
            self._path(table),
            dtype=str,
            keep_default_na=False,
            encoding="utf-8",
        )
        fields = TABLE_FIELDS[table]
        for field in fields:
            if field not in frame.columns:
                frame[field] = ""
        return frame.loc[:, fields]

    def _write(self, table: str, frame: pd.DataFrame) -> None:
        path = self._path(table)
        fields = TABLE_FIELDS[table]
        # Replace atomically so a failed request cannot leave a partial CSV.
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.directory, delete=False
        ) as file:
            temporary_path = Path(file.name)
            frame.loc[:, fields].to_csv(file, index=False, lineterminator="\n")
        temporary_path.replace(path)

    @staticmethod
    def _new_id() -> str:
        return str(uuid.uuid4())

    @staticmethod
    def _required_name(value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise APIError(400, "name must be a non-empty string")
        return value.strip()

    @staticmethod
    def _find(frame: pd.DataFrame, entity_id: str, label: str) -> dict[str, str]:
        matches = frame.loc[frame["id"] == entity_id]
        if matches.empty:
            raise APIError(404, f"{label} not found")
        return matches.iloc[0].to_dict()

    @staticmethod
    def _as_json(row: dict[str, str]) -> dict[str, Any]:
        result: dict[str, Any] = dict(row)
        for key in ("category_id", "subcategory_id", "note"):
            if key in result and result[key] == "":
                result[key] = None
        return result

    def list_rows(self, table: str) -> list[dict[str, Any]]:
        return [self._as_json(row) for row in self._read(table).to_dict("records")]

    def get_row(self, table: str, entity_id: str) -> dict[str, Any]:
        label = table[:-1]
        return self._as_json(self._find(self._read(table), entity_id, label))

    def create_category(self, body: dict[str, Any]) -> dict[str, Any]:
        row = {"id": self._new_id(), "name": self._required_name(body.get("name"))}
        categories = self._read("categories")
        categories = pd.concat([categories, pd.DataFrame([row])], ignore_index=True)
        self._write("categories", categories)
        return row

    def update_category(self, entity_id: str, body: dict[str, Any]) -> dict[str, Any]:
        categories = self._read("categories")
        row = self._find(categories, entity_id, "category")
        if "name" not in body:
            raise APIError(400, "name is required")
        row["name"] = self._required_name(body["name"])
        categories.loc[categories["id"] == entity_id, "name"] = row["name"]
        self._write("categories", categories)
        return row

    def delete_category(self, entity_id: str) -> None:
        categories = self._read("categories")
        self._find(categories, entity_id, "category")
        subcategories = self._read("subcategories")
        subcategories = subcategories.loc[
            subcategories["category_id"] != entity_id
        ].reset_index(drop=True)
        transactions = self._read("transactions")
        affected = transactions["category_id"] == entity_id
        transactions.loc[affected, ["category_id", "subcategory_id"]] = ""
        self._write("transactions", transactions)
        self._write("subcategories", subcategories)
        categories = categories.loc[categories["id"] != entity_id].reset_index(
            drop=True
        )
        self._write("categories", categories)

    def create_subcategory(self, body: dict[str, Any]) -> dict[str, Any]:
        category_id = body.get("category_id")
        if not isinstance(category_id, str) or not category_id:
            raise APIError(400, "category_id is required")
        self._find(self._read("categories"), category_id, "category")
        row = {
            "id": self._new_id(),
            "name": self._required_name(body.get("name")),
            "category_id": category_id,
        }
        subcategories = self._read("subcategories")
        subcategories = pd.concat(
            [subcategories, pd.DataFrame([row])], ignore_index=True
        )
        self._write("subcategories", subcategories)
        return row

    def update_subcategory(
        self, entity_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        subcategories = self._read("subcategories")
        row = self._find(subcategories, entity_id, "subcategory")
        if "name" not in body:
            raise APIError(400, "name is required")
        row["name"] = self._required_name(body["name"])
        subcategories.loc[subcategories["id"] == entity_id, "name"] = row["name"]
        self._write("subcategories", subcategories)
        return row

    def delete_subcategory(self, entity_id: str) -> None:
        subcategories = self._read("subcategories")
        self._find(subcategories, entity_id, "subcategory")
        subcategories = subcategories.loc[subcategories["id"] != entity_id].reset_index(
            drop=True
        )
        self._write("subcategories", subcategories)
        transactions = self._read("transactions")
        transactions.loc[
            transactions["subcategory_id"] == entity_id, "subcategory_id"
        ] = ""
        self._write("transactions", transactions)

    @staticmethod
    def _validate_date(value: Any) -> str:
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise APIError(400, "date must be a string in YYYY-MM-DD format")
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            raise APIError(
                400, "date must be a valid date in YYYY-MM-DD format"
            ) from None

    @staticmethod
    def _validate_amount(value: Any) -> str:
        if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
            raise APIError(400, "amount must be a number or numeric string")
        try:
            amount = Decimal(str(value))
        except InvalidOperation:
            raise APIError(400, "amount must be a valid number") from None
        if not amount.is_finite():
            raise APIError(400, "amount must be finite")
        if amount <= 0:
            raise APIError(400, "amount must be greater than zero")
        return format(amount, "f")

    def _validate_transaction_relations(
        self, category_id: str, subcategory_id: str
    ) -> None:
        categories = self._read("categories")
        subcategories = self._read("subcategories")
        if category_id:
            self._find(categories, category_id, "category")
        if subcategory_id:
            subcategory = self._find(subcategories, subcategory_id, "subcategory")
            if not category_id:
                raise APIError(
                    400, "category_id is required when subcategory_id is set"
                )
            if subcategory["category_id"] != category_id:
                raise APIError(
                    400, "subcategory does not belong to the specified category"
                )

    def create_transaction(self, body: dict[str, Any]) -> dict[str, Any]:
        for field in ("date", "amount"):
            if field not in body:
                raise APIError(400, f"{field} is required")
        category_id = body.get("category_id") or ""
        subcategory_id = body.get("subcategory_id") or ""
        if not isinstance(category_id, str) or not isinstance(subcategory_id, str):
            raise APIError(
                400, "category_id and subcategory_id must be strings or null"
            )
        self._validate_transaction_relations(category_id, subcategory_id)
        note = body.get("note")
        if note is not None and not isinstance(note, str):
            raise APIError(400, "note must be a string or null")
        row = {
            "id": self._new_id(),
            "date": self._validate_date(body["date"]),
            "amount": self._validate_amount(body["amount"]),
            "category_id": category_id,
            "subcategory_id": subcategory_id,
            "note": note or "",
        }
        transactions = self._read("transactions")
        transactions = pd.concat([transactions, pd.DataFrame([row])], ignore_index=True)
        self._write("transactions", transactions)
        return self._as_json(row)

    def update_transaction(
        self, entity_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        transactions = self._read("transactions")
        row = self._find(transactions, entity_id, "transaction")
        updated = dict(row)
        if "date" in body:
            updated["date"] = self._validate_date(body["date"])
        if "amount" in body:
            updated["amount"] = self._validate_amount(body["amount"])
        if "category_id" in body:
            category_id = body["category_id"]
            if category_id is None:
                category_id = ""
            if not isinstance(category_id, str):
                raise APIError(400, "category_id must be a string or null")
            updated["category_id"] = category_id
        if "subcategory_id" in body:
            subcategory_id = body["subcategory_id"]
            if subcategory_id is None:
                subcategory_id = ""
            if not isinstance(subcategory_id, str):
                raise APIError(400, "subcategory_id must be a string or null")
            updated["subcategory_id"] = subcategory_id
        if "note" in body:
            note = body["note"]
            if note is not None and not isinstance(note, str):
                raise APIError(400, "note must be a string or null")
            updated["note"] = note or ""
        self._validate_transaction_relations(
            updated["category_id"], updated["subcategory_id"]
        )
        transaction_mask = transactions["id"] == entity_id
        for field in TABLE_FIELDS["transactions"]:
            transactions.loc[transaction_mask, field] = updated[field]
        self._write("transactions", transactions)
        return self._as_json(updated)

    def delete_transaction(self, entity_id: str) -> None:
        transactions = self._read("transactions")
        self._find(transactions, entity_id, "transaction")
        transactions = transactions.loc[transactions["id"] != entity_id].reset_index(
            drop=True
        )
        self._write("transactions", transactions)

    def query_transactions(self, query: dict[str, list[str]]) -> list[dict[str, Any]]:
        filters = {
            key: query[key][0]
            for key in ("category_id", "subcategory_id", "start_date", "end_date")
            if key in query
        }
        if ("start_date" in filters) != ("end_date" in filters):
            raise APIError(400, "start_date and end_date must be provided together")
        if "start_date" in filters:
            filters["start_date"] = self._validate_date(filters["start_date"])
            filters["end_date"] = self._validate_date(filters["end_date"])
            if filters["start_date"] > filters["end_date"]:
                raise APIError(400, "start_date must be on or before end_date")
        for field in ("category_id", "subcategory_id"):
            if field in filters and not filters[field]:
                raise APIError(400, f"{field} cannot be empty")
        transactions = self._read("transactions")
        if "category_id" in filters:
            transactions = transactions.loc[
                transactions["category_id"] == filters["category_id"]
            ]
        if "subcategory_id" in filters:
            transactions = transactions.loc[
                transactions["subcategory_id"] == filters["subcategory_id"]
            ]
        if "start_date" in filters:
            transactions = transactions.loc[
                transactions["date"].between(
                    filters["start_date"], filters["end_date"], inclusive="both"
                )
            ]
        return [self._as_json(row) for row in transactions.to_dict("records")]


class RequestHandler(BaseHTTPRequestHandler):
    store: CSVStore

    def log_message(self, format: str, *args: Any) -> None:
        super().log_message(format, *args)

    def _send_json(self, status: int, payload: Any = None) -> None:
        body = b"" if status == 204 else json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def _body(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise APIError(400, "invalid Content-Length") from None
        if length <= 0:
            raise APIError(400, "request body must be a JSON object")
        try:
            body = json.loads(self.rfile.read(length))
        except (json.JSONDecodeError, UnicodeDecodeError):
            raise APIError(400, "request body must contain valid JSON") from None
        if not isinstance(body, dict):
            raise APIError(400, "request body must be a JSON object")
        return body

    def _dispatch(self) -> None:
        parsed = urlsplit(self.path)
        path = re.sub(r"/+", "/", parsed.path).rstrip("/") or "/"
        parts = [unquote(part) for part in path.split("/") if part]
        query = parse_qs(parsed.query, keep_blank_values=True)
        try:
            if self.command == "GET" and (
                path == "/"
                or not parts
                or parts[0] not in {"transactions", "categories", "subcategories"}
            ):
                self._send_static(path)
                return
            payload, status = self._route(parts, query)
            self._send_json(status, payload)
        except APIError as error:
            self._send_json(error.status, {"error": error.message})
        except (OSError, pd.errors.ParserError, pd.errors.EmptyDataError) as error:
            self._send_json(500, {"error": "CSV storage error", "details": str(error)})

    def _send_static(self, path: str) -> None:
        web_root = (Path(__file__).resolve().parent / "web").resolve()
        relative_path = "index.html" if path == "/" else unquote(path.lstrip("/"))
        file_path = (web_root / relative_path).resolve()
        if file_path != web_root and web_root not in file_path.parents:
            self._send_json(404, {"error": "not found"})
            return
        if not file_path.is_file():
            self._send_json(404, {"error": "not found"})
            return
        content = file_path.read_bytes()
        content_type = (
            mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        )
        if content_type.startswith(("text/", "application/javascript")):
            content_type += "; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_GET(self) -> None:
        self._dispatch()

    def do_POST(self) -> None:
        self._dispatch()

    def do_PATCH(self) -> None:
        self._dispatch()

    def do_DELETE(self) -> None:
        self._dispatch()

    def _route(self, parts: list[str], query: dict[str, list[str]]) -> tuple[Any, int]:
        method = self.command
        if not parts:
            raise APIError(404, "route not found")
        collection = parts[0]
        allowed = {"transactions", "categories", "subcategories"}
        if collection not in allowed:
            raise APIError(404, "route not found")

        if len(parts) == 1:
            if method == "GET":
                if collection == "transactions":
                    return self.store.query_transactions(query), 200
                return self.store.list_rows(collection), 200
            if method == "POST":
                body = self._body()
                creators = {
                    "transactions": self.store.create_transaction,
                    "categories": self.store.create_category,
                    "subcategories": self.store.create_subcategory,
                }
                return creators[collection](body), 201
            raise APIError(405, "method not allowed")

        if len(parts) != 2:
            raise APIError(404, "route not found")
        entity_id = parts[1]
        if method == "GET":
            return self.store.get_row(collection, entity_id), 200
        if method == "PATCH":
            body = self._body()
            updaters = {
                "transactions": self.store.update_transaction,
                "categories": self.store.update_category,
                "subcategories": self.store.update_subcategory,
            }
            return updaters[collection](entity_id, body), 200
        if method == "DELETE":
            deleters = {
                "transactions": self.store.delete_transaction,
                "categories": self.store.delete_category,
                "subcategories": self.store.delete_subcategory,
            }
            deleters[collection](entity_id)
            return None, 204
        raise APIError(405, "method not allowed")

    def log_error(self, format: str, *args: Any) -> None:
        super().log_error(format, *args)


def make_handler(store: CSVStore) -> type[RequestHandler]:
    class BoundRequestHandler(RequestHandler):
        pass

    BoundRequestHandler.store = store
    return BoundRequestHandler


def main() -> None:
    parser = argparse.ArgumentParser(description="CSV-backed expense tracker HTTP API")
    parser.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", "8000")))
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(os.environ.get("EXPENSE_DATA_DIR", "data")),
        help="directory for categories.csv, subcategories.csv, and transactions.csv",
    )
    args = parser.parse_args()
    store = CSVStore(args.data_dir)
    # A single-threaded server keeps CSV read/modify/write operations serialized.
    server = HTTPServer((args.host, args.port), make_handler(store))
    print(f"Expense tracker API listening on http://{args.host}:{args.port}")
    print(f"CSV data directory: {args.data_dir.resolve()}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
