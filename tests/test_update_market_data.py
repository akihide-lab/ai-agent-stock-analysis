from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import update_market_data


def create_stock_prices_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE stock_prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            stock_code TEXT NOT NULL,
            trade_date DATE NOT NULL,
            open_price REAL NOT NULL,
            high_price REAL NOT NULL,
            low_price REAL NOT NULL,
            close_price REAL NOT NULL,
            volume INTEGER NOT NULL
        )
        """
    )


def make_frame(start: str, periods: int, close_base: float = 100.0) -> pd.DataFrame:
    dates = pd.bdate_range(start=start, periods=periods)
    return pd.DataFrame(
        {
            "date": dates.strftime("%Y-%m-%d"),
            "Open": [close_base + index for index in range(periods)],
            "High": [close_base + index + 1 for index in range(periods)],
            "Low": [close_base + index - 1 for index in range(periods)],
            "Close": [close_base + index + 0.5 for index in range(periods)],
            "Volume": [1000 + index for index in range(periods)],
        }
    )


class UpdateMarketDataStockPriceTests(unittest.TestCase):
    def test_source_does_not_delete_stock_prices_before_insert(self) -> None:
        source = Path(update_market_data.__file__).read_text(encoding="utf-8")

        self.assertNotIn("DELETE FROM stock_prices", source)

    def test_upsert_stock_prices_preserves_history_and_updates_existing_rows(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "market.db"
            connection = sqlite3.connect(db_path)
            try:
                create_stock_prices_table(connection)
                existing = make_frame("2026-01-01", 30, close_base=100)
                update_market_data.upsert_stock_prices(connection, {"7203": existing})
                incoming = make_frame("2026-01-15", 30, close_base=200)

                summaries = update_market_data.upsert_stock_prices(
                    connection,
                    {"7203": incoming},
                )

                row_count, min_date, max_date = connection.execute(
                    """
                    SELECT COUNT(*), MIN(trade_date), MAX(trade_date)
                    FROM stock_prices
                    WHERE stock_code = '7203'
                    """
                ).fetchone()
                updated_close = connection.execute(
                    """
                    SELECT close_price
                    FROM stock_prices
                    WHERE stock_code = '7203'
                      AND trade_date = ?
                    """,
                    (incoming.iloc[0]["date"],),
                ).fetchone()[0]
            finally:
                connection.close()

        self.assertGreater(row_count, 30)
        self.assertEqual(min_date, existing.iloc[0]["date"])
        self.assertEqual(max_date, incoming.iloc[-1]["date"])
        self.assertEqual(updated_close, incoming.iloc[0]["Close"])
        self.assertEqual(summaries["7203"]["before_count"], 30)
        self.assertEqual(summaries["7203"]["after_count"], row_count)

    def test_upsert_stock_prices_rejects_partial_fetch_for_existing_history(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "market.db"
            connection = sqlite3.connect(db_path)
            try:
                create_stock_prices_table(connection)
                existing = make_frame("2025-01-01", 80, close_base=100)
                update_market_data.upsert_stock_prices(connection, {"7974": existing})
                partial = make_frame("2026-06-01", 22, close_base=200)

                with self.assertRaisesRegex(RuntimeError, "looks partial"):
                    update_market_data.upsert_stock_prices(connection, {"7974": partial})

                row_count = connection.execute(
                    "SELECT COUNT(*) FROM stock_prices WHERE stock_code = '7974'"
                ).fetchone()[0]
            finally:
                connection.close()

        self.assertEqual(row_count, 80)


if __name__ == "__main__":
    unittest.main()
