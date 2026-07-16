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

import search_stocks


def make_candidate_db(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            """
            CREATE TABLE stock_candidate_rows (
                stock_code TEXT,
                stock_name TEXT,
                market TEXT,
                sector TEXT,
                latest_trade_date TEXT,
                latest_close_price REAL,
                volume INTEGER,
                latest_fiscal_year TEXT,
                roe REAL,
                per REAL,
                pbr REAL,
                dividend_yield REAL,
                equity_ratio REAL
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO stock_candidate_rows VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [
                (
                    "1001",
                    "Alpha",
                    "Prime",
                    "Tech",
                    "2026-07-01",
                    1200.0,
                    10000,
                    "2025",
                    0.12,
                    15.0,
                    1.2,
                    0.02,
                    0.45,
                ),
                (
                    "1002",
                    "Beta",
                    "Prime",
                    "Finance",
                    "2026-07-01",
                    900.0,
                    20000,
                    "2025",
                    0.08,
                    9.0,
                    0.8,
                    0.03,
                    0.60,
                ),
            ],
        )
        connection.execute(
            """
            CREATE VIEW v_agent_stock_candidates AS
            SELECT * FROM stock_candidate_rows
            """
        )
        connection.commit()


class SearchStocksTests(unittest.TestCase):
    def test_load_candidates_sqlite_keeps_result_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "market_analysis.db"
            make_candidate_db(db_path)
            with patch.dict("os.environ", {"DB_TYPE": "sqlite"}, clear=False):
                frame = search_stocks.load_candidates(db_path)

        self.assertEqual(
            list(frame.columns),
            [
                "stock_code",
                "stock_name",
                "market",
                "sector",
                "trade_date",
                "close_price",
                "volume",
                "fiscal_year",
                "roe",
                "per",
                "pbr",
                "dividend_yield",
                "equity_ratio",
            ],
        )
        self.assertEqual(len(frame), 2)
        self.assertEqual(frame.iloc[0]["stock_code"], "1001")

    def test_sqlite_view_missing_raises_safe_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "market_analysis.db"
            with closing(sqlite3.connect(db_path)) as connection:
                connection.execute("CREATE TABLE placeholder (id INTEGER)")
                connection.commit()

            with patch.dict("os.environ", {"DB_TYPE": "sqlite"}, clear=False):
                with self.assertRaisesRegex(
                    search_stocks.StockSearchDatabaseError,
                    "Required view is not available",
                ):
                    search_stocks.load_candidates(db_path)

    def test_natural_language_search_existing_logic(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "market_analysis.db"
            make_candidate_db(db_path)
            with patch.dict("os.environ", {"DB_TYPE": "sqlite"}, clear=False):
                summary = search_stocks.summarize_stocks(
                    search_stocks.load_candidates(db_path)
                )

        result, reasons = search_stocks.natural_language_search(summary, "Tech ROE")
        self.assertEqual(result.iloc[0]["sector"], "Tech")
        self.assertTrue(reasons)


if __name__ == "__main__":
    unittest.main()
