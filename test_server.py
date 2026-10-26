import tempfile
import unittest
from pathlib import Path

from server import APIError, CSVStore


class CSVStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.store = CSVStore(Path(self.temp_dir.name))

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_creates_csv_tables_on_initialization(self):
        self.assertEqual(
            {"categories.csv", "subcategories.csv", "transactions.csv"},
            {path.name for path in Path(self.temp_dir.name).iterdir()},
        )

    def test_category_and_subcategory_rename_preserves_ids_and_relations(self):
        category = self.store.create_category({"name": "Food"})
        subcategory = self.store.create_subcategory(
            {"name": "Lunch", "category_id": category["id"]}
        )
        transaction = self.store.create_transaction(
            {
                "date": "2026-01-01",
                "amount": "2.50",
                "category_id": category["id"],
                "subcategory_id": subcategory["id"],
            }
        )

        renamed_category = self.store.update_category(category["id"], {"name": "Meals"})
        renamed_subcategory = self.store.update_subcategory(
            subcategory["id"], {"name": "Dinner"}
        )

        self.assertEqual(category["id"], renamed_category["id"])
        self.assertEqual(subcategory["id"], renamed_subcategory["id"])
        self.assertEqual(category["id"], renamed_subcategory["category_id"])
        saved_transaction = self.store.get_row("transactions", transaction["id"])
        self.assertEqual(category["id"], saved_transaction["category_id"])
        self.assertEqual(subcategory["id"], saved_transaction["subcategory_id"])

    def test_subcategory_requires_matching_parent_category(self):
        category = self.store.create_category({"name": "Food"})
        other_category = self.store.create_category({"name": "Travel"})
        subcategory = self.store.create_subcategory(
            {"name": "Lunch", "category_id": category["id"]}
        )

        with self.assertRaisesRegex(APIError, "does not belong"):
            self.store.create_transaction(
                {
                    "date": "2026-01-01",
                    "amount": "2",
                    "category_id": other_category["id"],
                    "subcategory_id": subcategory["id"],
                }
            )
        with self.assertRaisesRegex(APIError, "category_id is required"):
            self.store.create_transaction(
                {
                    "date": "2026-01-01",
                    "amount": "2",
                    "subcategory_id": subcategory["id"],
                }
            )

    def test_category_delete_clears_both_references_and_deletes_children(self):
        category = self.store.create_category({"name": "Food"})
        subcategory = self.store.create_subcategory(
            {"name": "Lunch", "category_id": category["id"]}
        )
        transaction = self.store.create_transaction(
            {
                "date": "2026-01-01",
                "amount": "2",
                "category_id": category["id"],
                "subcategory_id": subcategory["id"],
            }
        )

        self.store.delete_category(category["id"])

        self.assertIsNone(
            self.store.get_row("transactions", transaction["id"])["category_id"]
        )
        self.assertIsNone(
            self.store.get_row("transactions", transaction["id"])["subcategory_id"]
        )
        self.assertEqual([], self.store.list_rows("subcategories"))

    def test_subcategory_delete_preserves_transaction_category(self):
        category = self.store.create_category({"name": "Food"})
        subcategory = self.store.create_subcategory(
            {"name": "Lunch", "category_id": category["id"]}
        )
        transaction = self.store.create_transaction(
            {
                "date": "2026-01-01",
                "amount": 2,
                "category_id": category["id"],
                "subcategory_id": subcategory["id"],
            }
        )

        self.store.delete_subcategory(subcategory["id"])
        saved = self.store.get_row("transactions", transaction["id"])
        self.assertEqual(category["id"], saved["category_id"])
        self.assertIsNone(saved["subcategory_id"])

    def test_editing_only_transaction_subcategory_preserves_other_fields(self):
        category = self.store.create_category({"name": "Food"})
        old_subcategory = self.store.create_subcategory(
            {"name": "Lunch", "category_id": category["id"]}
        )
        new_subcategory = self.store.create_subcategory(
            {"name": "Dinner", "category_id": category["id"]}
        )
        transaction = self.store.create_transaction(
            {
                "date": "2026-10-26",
                "amount": "42.50",
                "category_id": category["id"],
                "subcategory_id": old_subcategory["id"],
                "note": "Meal",
            }
        )

        self.store.update_transaction(
            transaction["id"], {"subcategory_id": new_subcategory["id"]}
        )

        saved = self.store.get_row("transactions", transaction["id"])
        self.assertEqual(
            {
                "id": transaction["id"],
                "date": "2026-10-26",
                "amount": "42.50",
                "category_id": category["id"],
                "subcategory_id": new_subcategory["id"],
                "note": "Meal",
            },
            saved,
        )

    def test_period_filter_is_inclusive(self):
        first = self.store.create_transaction({"date": "2026-01-01", "amount": 1})
        middle = self.store.create_transaction({"date": "2026-01-15", "amount": 2})
        last = self.store.create_transaction({"date": "2026-01-31", "amount": 3})
        outside = self.store.create_transaction({"date": "2026-02-01", "amount": 4})

        results = self.store.query_transactions(
            {"start_date": ["2026-01-01"], "end_date": ["2026-01-31"]}
        )
        self.assertEqual(
            {first["id"], middle["id"], last["id"]}, {row["id"] for row in results}
        )
        self.assertNotIn(outside["id"], {row["id"] for row in results})

    def test_transaction_queries_preserve_creation_order_for_same_date(self):
        earlier = self.store.create_transaction(
            {"date": "2026-10-26", "amount": "10.00"}
        )
        later = self.store.create_transaction({"date": "2026-10-26", "amount": "20.00"})

        results = self.store.query_transactions({})

        self.assertEqual([earlier["id"], later["id"]], [row["id"] for row in results])

    def test_transaction_amount_must_be_positive(self):
        for amount in (0, "-1.25"):
            with (
                self.subTest(amount=amount),
                self.assertRaisesRegex(APIError, "greater than zero"),
            ):
                self.store.create_transaction({"date": "2026-01-01", "amount": amount})


if __name__ == "__main__":
    unittest.main()
