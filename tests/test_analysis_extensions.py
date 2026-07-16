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

import analysis_extensions as ext


EXPECTED_COLUMNS = [
    "stock_code",
    "stock_name",
    "sector",
    "trade_date",
    "close_price",
    "fiscal_year",
    "sales",
    "operating_profit",
    "net_profit",
    "roe",
    "eps",
    "per",
    "pbr",
    "dividend_yield",
    "equity_ratio",
]


def make_sector_db(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            """
            CREATE TABLE report_rows (
                stock_code TEXT,
                stock_name TEXT,
                sector TEXT,
                trade_date TEXT,
                close_price REAL,
                fiscal_year TEXT,
                sales REAL,
                operating_profit REAL,
                net_profit REAL,
                roe REAL,
                eps REAL,
                per REAL,
                pbr REAL,
                dividend_yield REAL,
                equity_ratio REAL
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO report_rows VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
            )
            """,
            [
                (
                    "1001",
                    "Alpha",
                    "Tech",
                    "2025-07-01",
                    100.0,
                    "2025",
                    1000.0,
                    100.0,
                    70.0,
                    0.10,
                    10.0,
                    12.0,
                    1.1,
                    0.02,
                    0.50,
                ),
                (
                    "1002",
                    "Beta",
                    "Tech",
                    "2026-07-01",
                    120.0,
                    "2026",
                    1100.0,
                    120.0,
                    80.0,
                    0.12,
                    12.0,
                    13.0,
                    1.2,
                    0.03,
                    0.55,
                ),
                (
                    "2001",
                    "Gamma",
                    "Finance",
                    "2026-07-01",
                    90.0,
                    "2026",
                    900.0,
                    90.0,
                    60.0,
                    0.08,
                    9.0,
                    10.0,
                    0.9,
                    0.04,
                    0.60,
                ),
            ],
        )
        connection.execute("CREATE VIEW v_ai_stock_report_input AS SELECT * FROM report_rows")
        connection.commit()


class AnalysisExtensionsTests(unittest.TestCase):
    def test_load_sector_data_sqlite_shape_and_values(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "market_analysis.db"
            make_sector_db(db_path)
            with patch.dict("os.environ", {"DB_TYPE": "sqlite"}, clear=False):
                frame = ext.load_sector_data(db_path, "Tech")

        self.assertEqual(list(frame.columns), EXPECTED_COLUMNS)
        self.assertEqual(len(frame), 2)
        self.assertEqual(frame["stock_code"].tolist(), ["1001", "1002"])
        self.assertTrue(str(frame["trade_date"].dtype).startswith("datetime64"))

    def test_load_sector_data_sqlite_missing_sector_returns_empty_frame(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "market_analysis.db"
            make_sector_db(db_path)
            with patch.dict("os.environ", {"DB_TYPE": "sqlite"}, clear=False):
                frame = ext.load_sector_data(db_path, "NoSuchSector")

        self.assertEqual(list(frame.columns), EXPECTED_COLUMNS)
        self.assertTrue(frame.empty)


if __name__ == "__main__":
    unittest.main()
