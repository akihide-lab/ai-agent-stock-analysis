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

import rdb_retriever as rdb
from query_flow_models import DataSourcePlan, QueryFlowInput


def make_rdb(path: Path) -> None:
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            """
            CREATE TABLE stock_master_rows (
                stock_code TEXT,
                stock_name TEXT,
                sector TEXT
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE freshness_rows (
                data_name TEXT,
                latest_date TEXT,
                record_count INTEGER
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE candidate_rows (
                stock_code TEXT,
                stock_name TEXT,
                latest_trade_date TEXT,
                volume INTEGER,
                dividend_yield REAL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE report_rows (
                stock_code TEXT,
                stock_name TEXT,
                trade_date TEXT,
                close_price REAL,
                wti_price REAL,
                usd_jpy REAL,
                policy_rate REAL,
                jgb_10y_yield REAL,
                cpi_index REAL,
                gdp_growth REAL,
                fiscal_year TEXT
            )
            """
        )
        connection.executemany(
            "INSERT INTO stock_master_rows VALUES (?, ?, ?)",
            [("9202", "ANA", "Air"), ("7203", "Toyota", "Auto")],
        )
        connection.executemany(
            "INSERT INTO freshness_rows VALUES (?, ?, ?)",
            [("stocks", "2026-07-01", 2), ("finance", "2025", 2)],
        )
        connection.executemany(
            "INSERT INTO candidate_rows VALUES (?, ?, ?, ?, ?)",
            [
                ("9202", "ANA", "2026-07-01", 200, 0.02),
                ("7203", "Toyota", "2026-07-01", 100, 0.03),
            ],
        )
        connection.executemany(
            "INSERT INTO report_rows VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                ("9202", "ANA", "2026-07-01", 100.0, 70.0, 150.0, 0.1, 1.0, 100.0, 1.2, "2025"),
                ("9202", "ANA", "2026-07-02", 101.0, None, 150.0, 0.1, 1.0, 100.0, 1.2, "2025"),
            ],
        )
        connection.execute("CREATE VIEW v_agent_stock_master AS SELECT * FROM stock_master_rows")
        connection.execute("CREATE VIEW v_agent_data_freshness AS SELECT * FROM freshness_rows")
        connection.execute("CREATE VIEW v_agent_stock_candidates AS SELECT * FROM candidate_rows")
        connection.execute("CREATE VIEW v_ai_stock_report_input AS SELECT * FROM report_rows")
        connection.commit()


class RdbRetrieverTests(unittest.TestCase):
    def test_sqlite_fetches_freshness_candidates_and_readiness(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "market_analysis.db"
            make_rdb(db_path)
            with patch.dict("os.environ", {"DB_TYPE": "sqlite"}, clear=False):
                connection = rdb.connect_read_only(db_path)
                try:
                    freshness = rdb.fetch_data_freshness(connection)
                    candidates = rdb.fetch_candidate_stocks(connection, "Intent002", limit=1)
                    readiness = rdb.fetch_analysis_readiness(connection, "9202")
                    missing = rdb.fetch_analysis_readiness(connection, "9999")
                finally:
                    connection.close()

        self.assertTrue(freshness.metadata["available"])
        self.assertEqual(len(candidates.rows), 1)
        self.assertEqual(readiness.rows[0]["total_rows"], 2)
        self.assertEqual(readiness.rows[0]["complete_rows"], 1)
        self.assertEqual(missing.rows, [])

    def test_sqlite_retrieve_rdb_context_keeps_shape(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "market_analysis.db"
            make_rdb(db_path)
            query = QueryFlowInput(
                user_question="9202",
                primary_intent="Intent008",
                entities={},
            )
            plan = DataSourcePlan(
                intent_id="Intent008",
                action_name="analyze",
                rdb_targets=[],
                rag_targets=[],
                next_flow="context",
            )
            with patch.dict("os.environ", {"DB_TYPE": "sqlite"}, clear=False):
                results, resolved, warnings = rdb.retrieve_rdb_context(query, plan, db_path, limit=1)

        self.assertEqual(warnings, [])
        self.assertEqual(resolved[0]["stock_code"], "9202")
        self.assertTrue(any(result.target == "analysis_readiness" for result in results))

    def test_invalid_limit_raises_clear_error(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "market_analysis.db"
            make_rdb(db_path)
            with patch.dict("os.environ", {"DB_TYPE": "sqlite"}, clear=False):
                connection = rdb.connect_read_only(db_path)
                try:
                    with self.assertRaisesRegex(ValueError, "limit must be a positive integer"):
                        rdb.fetch_candidate_stocks(connection, "Intent002", limit=0)
                finally:
                    connection.close()


if __name__ == "__main__":
    unittest.main()
