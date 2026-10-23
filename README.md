# Expense Tracker HTTP API

A small Python HTTP server backed by three CSV files. It uses pandas to load, filter, and write the tables, and creates the data directory and CSV tables on startup if they do not exist.

The server also serves a responsive browser frontend built with plain HTML, CSS, and JavaScript. There is no frontend build step.

## Run

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
python3 server.py
```

Open <http://127.0.0.1:8000/> in a browser.

`requirements-dev.txt` also installs Ruff for development. Run its checks with:

```sh
ruff check .
ruff format --check .
```

By default, the server listens on `127.0.0.1:8000` and stores CSV files in `./data`. Configure it with command-line options or environment variables:

```sh
python3 server.py --host 0.0.0.0 --port 8080 --data-dir ./expense-data
```

Environment variables `HOST`, `PORT`, and `EXPENSE_DATA_DIR` provide the same defaults.

## Run as a Docker service

Docker Compose builds the app image, runs it as a restartable service, and bind-mounts `./data` so the CSV files persist outside the container. The default port binding is local-only (`127.0.0.1:8000`).

```sh
cp .env.example .env
mkdir -p data
```

Set `PUID` and `PGID` in `.env` to the user and group IDs that can read and write `./data` (check them with `id -u` and `id -g`). Then start the service:

```sh
docker compose up -d --build
docker compose logs -f expense-tracker
```

Open <http://127.0.0.1:8000/> on the server. To access it from another device on your trusted local network, set `EXPENSE_TRACKER_BIND=0.0.0.0` in `.env`, restart with `docker compose up -d`, and visit `http://SERVER_IP:8000/`. The app has no authentication or TLS, so do not expose it directly to the public internet.

Useful service commands:

```sh
docker compose ps
docker compose restart
docker compose down                 # stops the service; leaves ./data untouched
docker compose up -d --build        # rebuild after updating the app
```

Back up the CSV data by copying the `data/` directory while the service is stopped. The Compose service mounts the existing `./data` directory, so it uses the same CSV files as a local Python run.

## Endpoints

All API request and response bodies use JSON. IDs are stable UUIDs. Amounts must be greater than zero and are returned as decimal strings to avoid losing precision.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/transactions` | List all transactions; optional filters below |
| `GET` | `/transactions/{id}` | Get one transaction |
| `POST` | `/transactions` | Create a transaction |
| `PATCH` | `/transactions/{id}` | Update supplied transaction fields |
| `DELETE` | `/transactions/{id}` | Delete a transaction |
| `GET` | `/categories` | List categories |
| `GET` | `/categories/{id}` | Get one category |
| `POST` | `/categories` | Create a category |
| `PATCH` | `/categories/{id}` | Rename a category |
| `DELETE` | `/categories/{id}` | Delete a category and its subcategories; clear matching transaction category and subcategory references |
| `GET` | `/subcategories` | List subcategories |
| `GET` | `/subcategories/{id}` | Get one subcategory |
| `POST` | `/subcategories` | Create a subcategory |
| `PATCH` | `/subcategories/{id}` | Rename a subcategory |
| `DELETE` | `/subcategories/{id}` | Delete a subcategory and clear matching transaction subcategory references |

### Transaction filters

Filters can be combined:

```text
GET /transactions?category_id={id}
GET /transactions?subcategory_id={id}
GET /transactions?start_date=2026-01-01&end_date=2026-01-31
```

Date ranges are inclusive and both `start_date` and `end_date` are required together, in `YYYY-MM-DD` format.

### Example request bodies

Create a category:

```json
{"name":"Food"}
```

Create a subcategory (the category must already exist):

```json
{"name":"Groceries","category_id":"CATEGORY_ID"}
```

Create a transaction:

```json
{
  "date":"2026-01-15",
  "amount":"12.50",
  "category_id":"CATEGORY_ID",
  "subcategory_id":"SUBCATEGORY_ID",
  "note":"Lunch"
}
```

`date` and a positive `amount` are required. Category, subcategory, and note are optional. A subcategory requires a category, and the selected subcategory must belong to the selected category. Set optional transaction fields to `null` in a `PATCH` request to clear them. Clearing a category while its subcategory remains set is rejected; clear both together or clear the subcategory first.

## Web frontend

The home page supports adding expenses, filtering the transaction list by an inclusive date range, and editing or deleting a transaction by selecting it. Transactions are shown newest first, with 20 per page. The Categories page manages categories and subcategories. The Dashboard supports all-time, month, or inclusive date-range summaries, with expandable category totals and an `Uncategorized` group. All amounts are treated as positive expenses.

Successful creates return `201`; successful deletes return `204`. Errors return a JSON body such as `{"error":"..."}`. Invalid input returns `400`, and missing resources return `404`.

## CSV files

- `categories.csv`: `id,name`
- `subcategories.csv`: `id,name,category_id`
- `transactions.csv`: `id,date,amount,category_id,subcategory_id,note`

Empty category, subcategory, and note values in transaction CSV rows are represented as empty fields; API responses expose them as JSON `null`.
