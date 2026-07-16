from __future__ import annotations

import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import dispatcher
import question_agent
from workflows import FOLLOWUP_REQUIRED, SINGLE_STOCK_ANALYSIS, STOCK_SCREENING, get_workflow


def _analysis_result(
    *,
    succeeded: bool = True,
    report_path: str | None = "report.html",
    route: str = "single_stock_report",
) -> SimpleNamespace:
    return SimpleNamespace(
        succeeded=succeeded,
        report_path=report_path,
        followup_question=None,
        route=route,
    )


class DispatcherTests(unittest.TestCase):
    def test_no_direct_database_or_legacy_report_patterns(self) -> None:
        source = Path(dispatcher.__file__).read_text(encoding="utf-8")

        self.assertNotIn("sqlite3", source)
        self.assertNotIn("sqlite_master", source)
        self.assertNotIn("PRAGMA", source)
        self.assertNotIn("connect_database", source)
        self.assertNotIn("run_report", source)

    def test_single_stock_delegates_to_analysis_connector(self) -> None:
        decision = question_agent.QuestionDecision(
            user_question="9202",
            primary_intent="Intent008",
            selected_stock_code="9202",
            selected_stock_name="ANAホールディングス",
        )
        with mock.patch.object(
            dispatcher,
            "run_v1_analysis_flow",
            return_value=_analysis_result(report_path="report.html"),
        ) as run_flow:
            result = dispatcher.execute(
                get_workflow(SINGLE_STOCK_ANALYSIS),
                decision=decision,
                db_path=Path("missing.db"),
                skip_web_update=True,
                skip_finance=True,
                dry_run=False,
                limit=3,
            )

        self.assertTrue(result.succeeded)
        self.assertEqual(result.report_path, "report.html")
        run_flow.assert_called_once_with(
            question="9202",
            intent_id="Intent008",
            db_path=Path("missing.db"),
            output_json=None,
            generate_report=True,
            allow_update=False,
            limit=3,
            skip_finance=True,
        )

    def test_followup_workflow_does_not_start_analysis(self) -> None:
        decision = question_agent.QuestionDecision(
            user_question="9999",
            primary_intent="",
            message="銘柄コードを教えてください。",
        )
        with mock.patch.object(dispatcher, "run_v1_analysis_flow") as run_flow:
            result = dispatcher.execute(
                get_workflow(FOLLOWUP_REQUIRED),
                decision=decision,
                db_path=Path("missing.db"),
                skip_web_update=True,
                skip_finance=False,
                dry_run=False,
                limit=5,
            )

        self.assertTrue(result.succeeded)
        run_flow.assert_not_called()

    def test_stock_screening_delegates_selected_candidate_to_analysis_connector(self) -> None:
        decision = question_agent.QuestionDecision(
            user_question="安定した株を探して",
            primary_intent="Intent005",
            entities={"投資目的": "安定性"},
        )
        candidates = pd.DataFrame(
            [{"stock_code": "9202", "stock_name": "ANAホールディングス"}]
        )
        with mock.patch.object(
            dispatcher.qa,
            "select_candidate",
            return_value=(candidates, ["reason"]),
        ):
            with mock.patch.object(
                dispatcher,
                "run_v1_analysis_flow",
                return_value=_analysis_result(report_path="screened.html"),
            ) as run_flow:
                result = dispatcher.execute(
                    get_workflow(STOCK_SCREENING),
                    decision=decision,
                    db_path=Path("missing.db"),
                    skip_web_update=False,
                    skip_finance=False,
                    dry_run=False,
                    limit=5,
                )

        self.assertTrue(result.succeeded)
        self.assertEqual(decision.selected_stock_code, "9202")
        self.assertEqual(result.report_path, "screened.html")
        self.assertTrue(run_flow.call_args.kwargs["allow_update"])


if __name__ == "__main__":
    unittest.main()
