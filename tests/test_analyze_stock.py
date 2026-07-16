from __future__ import annotations

import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import analyze_stock
from query_flow_models import (
    AnalysisContext,
    AnalysisRunResult,
    DataSourcePlan,
    QueryFlowInput,
    RetrievedContext,
)


def _result(report_path: str | None = None, succeeded: bool = True) -> AnalysisRunResult:
    query = QueryFlowInput(user_question="9202", primary_intent="Intent008")
    plan = DataSourcePlan(
        intent_id="Intent008",
        action_name="analyze",
        rdb_targets=[],
        rag_targets=[],
        next_flow="single_stock_report",
    )
    context = AnalysisContext(
        query=query,
        data_source_plan=plan,
        retrieved_context=RetrievedContext(),
        selected_stock_code="9202",
        selected_stock_name="ANA Holdings",
    )
    return AnalysisRunResult(
        analysis_context=context,
        report_path=report_path,
        route="single_stock_report",
        succeeded=succeeded,
    )


class AnalyzeStockCliTests(unittest.TestCase):
    def test_no_direct_database_or_update_patterns(self) -> None:
        source = Path(analyze_stock.__file__).read_text(encoding="utf-8")

        self.assertNotIn("sqlite3", source)
        self.assertNotIn("sqlite_master", source)
        self.assertNotIn("PRAGMA", source)
        self.assertNotIn("subprocess", source)
        self.assertNotIn("update_market_data.py", source)
        self.assertNotIn("update_official_macro_web.py", source)

    def test_postgres_cli_delegates_without_requiring_sqlite_path(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "missing" / "market_analysis.db"
            output_json = Path(temp_dir) / "context.json"
            argv = [
                "analyze_stock.py",
                "9202",
                "--db",
                str(db_path),
                "--output-json",
                str(output_json),
                "--skip-web-update",
            ]
            with patch.dict("os.environ", {"DB_TYPE": "postgres"}, clear=False):
                with patch.object(sys, "argv", argv):
                    with patch.object(
                        analyze_stock,
                        "run_v1_analysis_flow",
                        return_value=_result("report.html"),
                    ) as run_flow:
                        with redirect_stdout(StringIO()):
                            with self.assertRaises(SystemExit) as exit_context:
                                analyze_stock.main()

        self.assertEqual(exit_context.exception.code, 0)
        run_flow.assert_called_once_with(
            question="9202",
            intent_id="Intent008",
            db_path=db_path,
            output_json=output_json,
            generate_report=True,
            allow_update=False,
            limit=1,
            output_path=None,
            skip_finance=False,
        )

    def test_context_only_disables_report_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_json = Path(temp_dir) / "context.json"
            argv = [
                "analyze_stock.py",
                "9202",
                "--context-only",
                "--output-json",
                str(output_json),
            ]
            with patch.object(sys, "argv", argv):
                with patch.object(
                    analyze_stock,
                    "run_v1_analysis_flow",
                    return_value=_result(None),
                ) as run_flow:
                    with redirect_stdout(StringIO()):
                        with self.assertRaises(SystemExit) as exit_context:
                            analyze_stock.main()

        self.assertEqual(exit_context.exception.code, 0)
        self.assertFalse(run_flow.call_args.kwargs["generate_report"])
        self.assertTrue(run_flow.call_args.kwargs["allow_update"])
        self.assertFalse(run_flow.call_args.kwargs["skip_finance"])

    def test_skip_finance_is_delegated_to_analysis_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_json = Path(temp_dir) / "context.json"
            argv = [
                "analyze_stock.py",
                "9202",
                "--skip-finance",
                "--output-json",
                str(output_json),
            ]
            with patch.object(sys, "argv", argv):
                with patch.object(
                    analyze_stock,
                    "run_v1_analysis_flow",
                    return_value=_result(None),
                ) as run_flow:
                    with redirect_stdout(StringIO()):
                        with self.assertRaises(SystemExit) as exit_context:
                            analyze_stock.main()

        self.assertEqual(exit_context.exception.code, 0)
        self.assertTrue(run_flow.call_args.kwargs["skip_finance"])


if __name__ == "__main__":
    unittest.main()
