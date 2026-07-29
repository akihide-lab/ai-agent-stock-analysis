from __future__ import annotations

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from mongodb_news_repository import MongoDBNewsRepository, normalize_news_document


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows

    def sort(self, key, direction):
        reverse = direction == -1
        self.rows = sorted(self.rows, key=lambda row: row.get(key), reverse=reverse)
        return self

    def limit(self, limit):
        self.rows = self.rows[:limit]
        return self

    def __iter__(self):
        return iter(self.rows)


class FakeCollection:
    def __init__(self):
        self.rows = {}
        self.indexes = []
        self.next_id = 1

    def create_index(self, keys, **kwargs):
        self.indexes.append((keys, kwargs))

    def update_one(self, filter_doc, update_doc, upsert=False):
        url = filter_doc["url"]
        if url in self.rows:
            self.rows[url].update(update_doc["$set"])
            return SimpleNamespace(upserted_id=None, matched_count=1)

        row = {"_id": self.next_id}
        self.next_id += 1
        row.update(update_doc.get("$setOnInsert", {}))
        row.update(update_doc["$set"])
        self.rows[url] = row
        return SimpleNamespace(upserted_id=row["_id"], matched_count=0)

    def find(self, filter_doc):
        stock_code = filter_doc["stock_code"]
        return FakeCursor(
            [row for row in self.rows.values() if row.get("stock_code") == stock_code]
        )


def _news(url: str, title: str, published_at: datetime):
    return {
        "stock_code": "7203",
        "company_name": "Toyota",
        "title": title,
        "body": "body",
        "url": url,
        "published_at": published_at,
        "source": "sample_news",
        "category": "business",
    }


class MongoDBNewsRepositoryTests(unittest.TestCase):
    def test_normalize_news_document_uses_utc_datetime(self):
        document = normalize_news_document(
            _news("https://example.com/1", "title", datetime(2026, 7, 29, 9, 0))
        )

        self.assertEqual(document["published_at"].tzinfo, timezone.utc)
        self.assertEqual(document["vector_status"], "pending")

    def test_ensure_indexes_creates_required_indexes(self):
        collection = FakeCollection()
        repository = MongoDBNewsRepository(collection)

        repository.ensure_indexes()

        self.assertEqual(collection.indexes[0][0], [("url", 1)])
        self.assertTrue(collection.indexes[0][1]["unique"])
        self.assertEqual(collection.indexes[1][0], [("stock_code", 1), ("published_at", -1)])

    def test_save_many_upserts_by_url_and_updates_existing_document(self):
        collection = FakeCollection()
        repository = MongoDBNewsRepository(collection)
        published_at = datetime(2026, 7, 29, 9, 0, tzinfo=timezone.utc)

        first = repository.save_many([_news("https://example.com/1", "old", published_at)])
        second = repository.save_many([_news("https://example.com/1", "new", published_at)])

        self.assertEqual(first.inserted, 1)
        self.assertEqual(second.updated, 1)
        self.assertEqual(len(collection.rows), 1)
        self.assertEqual(collection.rows["https://example.com/1"]["title"], "new")

    def test_find_by_stock_code_sorts_desc_and_limits(self):
        collection = FakeCollection()
        repository = MongoDBNewsRepository(collection)
        repository.save_many(
            [
                _news("https://example.com/1", "old", datetime(2026, 7, 28, tzinfo=timezone.utc)),
                _news("https://example.com/2", "new", datetime(2026, 7, 29, tzinfo=timezone.utc)),
            ]
        )

        results = repository.find_by_stock_code("7203", limit=1)
        missing = repository.find_by_stock_code("9999", limit=1)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].title, "new")
        self.assertEqual(missing, [])


if __name__ == "__main__":
    unittest.main()
