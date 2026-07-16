from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from stock_name_resolver import StockNameResolver


def make_master_db(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            """
            CREATE TABLE master_rows (
                stock_code TEXT,
                stock_name TEXT,
                market TEXT,
                sector TEXT
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO master_rows
                (stock_code, stock_name, market, sector)
            VALUES (?, ?, ?, ?)
            """,
            [
                ("1001", "Alpha Motors", "Prime", "Transport"),
                ("1002", "Alpha Foods", "Prime", "Retail"),
                ("2001", "BetaBank", "Prime", "Finance"),
            ],
        )
        connection.execute(
            """
            CREATE VIEW v_agent_stock_master AS
            SELECT * FROM master_rows
            """
        )
        connection.commit()


class StockNameResolverTests(unittest.TestCase):
    def test_resolves_by_stock_code_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "stocks.db"
            make_master_db(db_path)
            with patch.dict("os.environ", {"DB_TYPE": "sqlite"}, clear=False):
                candidates = StockNameResolver(db_path).resolve("1001")

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].stock_code, "1001")
        self.assertEqual(candidates[0].match_type, "code_exact")

    def test_resolves_by_exact_name_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "stocks.db"
            make_master_db(db_path)
            with patch.dict("os.environ", {"DB_TYPE": "sqlite"}, clear=False):
                candidates = StockNameResolver(db_path).resolve("BetaBank")

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].stock_code, "2001")
        self.assertEqual(candidates[0].match_type, "name_exact")

    def test_resolves_by_partial_name_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "stocks.db"
            make_master_db(db_path)
            with patch.dict("os.environ", {"DB_TYPE": "sqlite"}, clear=False):
                candidates = StockNameResolver(db_path).resolve("Bank")

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0].stock_code, "2001")
        self.assertEqual(candidates[0].match_type, "name_partial")

    def test_multiple_candidates_keep_result_shape_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "stocks.db"
            make_master_db(db_path)
            with patch.dict("os.environ", {"DB_TYPE": "sqlite"}, clear=False):
                candidates = StockNameResolver(db_path).resolve("Alpha")

        self.assertEqual([candidate.stock_code for candidate in candidates], ["1001", "1002"])
        self.assertTrue(all(candidate.match_type == "name_partial" for candidate in candidates))

    def test_unresolved_returns_empty_list_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "stocks.db"
            make_master_db(db_path)
            with patch.dict("os.environ", {"DB_TYPE": "sqlite"}, clear=False):
                candidates = StockNameResolver(db_path).resolve("No Such Company")

        self.assertEqual(candidates, [])


if __name__ == "__main__":
    unittest.main()
