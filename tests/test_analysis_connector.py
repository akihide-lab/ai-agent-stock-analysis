from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import analysis_connector as connector
from query_flow_models import RdbResult
from stock_name_resolver import StockCandidate


def _candidate() -> StockCandidate:
    return StockCandidate(
        stock_code="9202",
        stock_name="ANA Holdings",
        market="Prime",
        sector="Air",
        match_type="code_exact",
    )


def _rdb_results(complete_rows: int) -> list[RdbResult]:
    return [
        RdbResult(
            target="data_freshness",
            rows=[{"data_name": "stock_prices", "latest_date": "2026-07-01"}],
            metadata={"available": True},
        ),
        RdbResult(
            target="stock_profile",
            rows=[{"stock_code": "9202", "stock_name": "ANA Holdings", "sector": "Air"}],
            metadata={"stock_code": "9202"},
        ),
        RdbResult(
            target="analysis_readiness",
            rows=[
                {
                    "stock_code": "9202",
                    "stock_name": "ANA Holdings",
                    "total_rows": complete_rows,
                    "complete_rows": complete_rows,
                }
            ],
            metadata={"stock_code": "9202", "available": True},
        ),
    ]


class AnalysisConnectorBoundaryTests(unittest.TestCase):
    def test_no_direct_sqlite_connection_patterns(self) -> None:
        source = Path(connector.__file__).read_text(encoding="utf-8")

        self.assertNotIn("sqlite3", source)
        self.assertNotIn("sqlite_master", source)
        self.assertNotIn("PRAGMA", source)
        self.assertNotIn("psycopg", source)

    def test_postgres_report_generation_does_not_require_sqlite_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "missing" / "market_analysis.db"
            report_path = Path(temp_dir) / "report.html"
            with patch.dict(
                "os.environ",
                {"DB_TYPE": "postgres", "MONGODB_ENABLED": "false"},
                clear=False,
            ):
                with patch.object(
                    connector.StockNameResolver,
                    "resolve",
                    return_value=[_candidate()],
                ):
                    with patch.object(
                        connector,
                        "retrieve_rdb_context",
                        return_value=(_rdb_results(20), [{"stock_code": "9202"}], []),
                    ):
                        with patch.object(
                            connector,
                            "search_rag_context",
                            return_value=([], []),
                        ):
                            with patch(
                                "generate_stock_report.generate_report",
                                return_value=report_path,
                            ) as generate_report:
                                result = connector.run_v1_analysis_flow(
                                    "9202",
                                    intent_id="Intent008",
                                    db_path=db_path,
                                    output_json=None,
                                    generate_report=True,
                                    allow_update=True,
                                    limit=1,
                                )

        self.assertTrue(result.succeeded)
        generate_report.assert_called_once()
        args = generate_report.call_args.args
        self.assertEqual(args[:6], ("9202", db_path, None, None, [], None))
        self.assertEqual(args[6].rows, [])
        self.assertFalse(args[6].metadata["available"])

    def test_postgres_insufficient_data_skips_sqlite_update_and_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "missing" / "market_analysis.db"
            with patch.dict(
                "os.environ",
                {"DB_TYPE": "postgres", "MONGODB_ENABLED": "false"},
                clear=False,
            ):
                with patch.object(
                    connector.StockNameResolver,
                    "resolve",
                    return_value=[_candidate()],
                ):
                    with patch.object(
                        connector,
                        "retrieve_rdb_context",
                        return_value=(_rdb_results(0), [{"stock_code": "9202"}], []),
                    ):
                        with patch.object(
                            connector,
                            "search_rag_context",
                            return_value=([], []),
                        ):
                            with patch.object(
                                connector,
                                "_run_existing_update_scripts",
                            ) as update_scripts:
                                with patch(
                                    "generate_stock_report.generate_report",
                                ) as generate_report:
                                    result = connector.run_v1_analysis_flow(
                                        "9202",
                                        intent_id="Intent008",
                                        db_path=db_path,
                                        output_json=None,
                                        generate_report=True,
                                        allow_update=True,
                                        limit=1,
                                        skip_finance=True,
                                    )

        self.assertFalse(result.succeeded)
        self.assertTrue(
            any("skipped" in warning for warning in result.warnings)
        )
        update_scripts.assert_not_called()
        generate_report.assert_not_called()

    def test_sqlite_update_command_omits_skip_finance_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "market_analysis.db"
            with patch.dict("os.environ", {"DB_TYPE": "sqlite"}, clear=False):
                with patch.object(connector.subprocess, "run") as run:
                    run.return_value.returncode = 0
                    run.return_value.stdout = ""
                    run.return_value.stderr = ""

                    ok, messages = connector._run_existing_update_scripts(
                        "9202",
                        db_path,
                    )

        self.assertTrue(ok)
        self.assertEqual(len(messages), 2)
        market_command = run.call_args_list[0].args[0]
        self.assertNotIn("--skip-finance", market_command)

    def test_sqlite_update_command_passes_skip_finance_when_requested(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "market_analysis.db"
            with patch.dict("os.environ", {"DB_TYPE": "sqlite"}, clear=False):
                with patch.object(connector.subprocess, "run") as run:
                    run.return_value.returncode = 0
                    run.return_value.stdout = ""
                    run.return_value.stderr = ""

                    ok, messages = connector._run_existing_update_scripts(
                        "9202",
                        db_path,
                        skip_finance=True,
                    )

        self.assertTrue(ok)
        self.assertEqual(len(messages), 2)
        market_command = run.call_args_list[0].args[0]
        official_command = run.call_args_list[1].args[0]
        self.assertIn("--skip-finance", market_command)
        self.assertNotIn("--skip-finance", official_command)


if __name__ == "__main__":
    unittest.main()
