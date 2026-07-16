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

import generate_stock_report as report


def make_report_db(path: Path) -> None:
    columns = []
    for column in report.SELECT_COLUMNS:
        column_type = "TEXT" if column in {"stock_code", "stock_name", "market", "sector", "trade_date", "fiscal_year", "year_month"} else "REAL"
        columns.append(f"{column} {column_type}")
    values = {
        column: 1.0
        for column in report.SELECT_COLUMNS
    }
    values.update(
        {
            "stock_code": "9202",
            "stock_name": "ANA Holdings",
            "market": "Prime",
            "sector": "Air",
            "trade_date": "2026-07-01",
            "fiscal_year": "2025",
            "year_month": "2026-07",
        }
    )

    with closing(sqlite3.connect(path)) as connection:
        connection.execute(f"CREATE TABLE report_rows ({', '.join(columns)})")
        placeholders = ", ".join("?" for _ in report.SELECT_COLUMNS)
        connection.execute(
            f"INSERT INTO report_rows ({', '.join(report.SELECT_COLUMNS)}) VALUES ({placeholders})",
            tuple(values[column] for column in report.SELECT_COLUMNS),
        )
        connection.execute("CREATE VIEW v_ai_stock_report_input AS SELECT * FROM report_rows")
        connection.execute("CREATE VIEW v_stock_fundamental AS SELECT stock_code FROM report_rows")
        connection.execute("CREATE VIEW v_macro_economic AS SELECT trade_date FROM report_rows")
        connection.commit()


class GenerateStockReportDbConnectionTests(unittest.TestCase):
    def test_load_report_input_uses_sqlite_common_connection(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "market_analysis.db"
            make_report_db(db_path)
            with patch.dict("os.environ", {"DB_TYPE": "sqlite"}, clear=False):
                frame = report.load_report_input(db_path, "9202")

        self.assertEqual(len(frame), 1)
        self.assertEqual(frame.iloc[0]["stock_code"], "9202")
        self.assertEqual(str(frame.iloc[0]["trade_date"].date()), "2026-07-01")

    def test_validate_views_reports_missing_view_safely(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "market_analysis.db"
            with closing(sqlite3.connect(db_path)) as connection:
                connection.execute("CREATE TABLE sample (id INTEGER)")
                connection.commit()
            with patch.dict("os.environ", {"DB_TYPE": "sqlite"}, clear=False):
                connection = report.connect_read_only(db_path)
                try:
                    with self.assertRaises(RuntimeError) as context:
                        report.validate_views(connection)
                finally:
                    connection.close()

        self.assertIn("v_ai_stock_report_input", str(context.exception))


if __name__ == "__main__":
    unittest.main()
