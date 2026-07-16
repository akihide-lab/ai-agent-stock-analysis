from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import dispatcher
import workflows


class WorkflowDefinitionTests(unittest.TestCase):
    def test_no_database_or_legacy_route_patterns(self) -> None:
        source = Path(workflows.__file__).read_text(encoding="utf-8")

        self.assertNotIn("sqlite3", source)
        self.assertNotIn("sqlite_master", source)
        self.assertNotIn("PRAGMA", source)
        self.assertNotIn("connect_database", source)
        self.assertNotIn("DB_TYPE", source)
        self.assertNotIn("run_report", source)
        self.assertNotIn("generate_or_run_existing_report", source)

    def test_workflow_names_match_dispatcher_branches(self) -> None:
        defined = set(workflows.WORKFLOWS)

        self.assertIn(workflows.SINGLE_STOCK_ANALYSIS, defined)
        self.assertIn(workflows.STOCK_SCREENING, defined)
        self.assertIn(workflows.FOLLOWUP_REQUIRED, defined)
        self.assertIn(workflows.UNSUPPORTED, defined)
        self.assertIn(workflows.SYSTEM_ERROR, defined)
        self.assertEqual(dispatcher.SINGLE_STOCK_ANALYSIS, workflows.SINGLE_STOCK_ANALYSIS)
        self.assertEqual(dispatcher.STOCK_SCREENING, workflows.STOCK_SCREENING)
        self.assertEqual(dispatcher.FOLLOWUP_REQUIRED, workflows.FOLLOWUP_REQUIRED)
        self.assertEqual(dispatcher.UNSUPPORTED, workflows.UNSUPPORTED)
        self.assertEqual(dispatcher.SYSTEM_ERROR, workflows.SYSTEM_ERROR)

    def test_single_stock_workflow_matches_analysis_connector_route(self) -> None:
        workflow = workflows.get_workflow(workflows.SINGLE_STOCK_ANALYSIS)

        self.assertEqual(
            workflow.required_inputs,
            (
                "selected_stock_code",
                "db_path",
                "skip_web_update",
                "skip_finance",
                "limit",
            ),
        )
        self.assertEqual(
            workflow.steps,
            ("validate_selected_stock", "delegate_to_analysis_connector"),
        )
        self.assertTrue(workflow.update_allowed)
        self.assertEqual(workflow.stop_conditions, ("missing_selected_stock_code",))

    def test_stock_screening_workflow_delegates_after_candidate_selection(self) -> None:
        workflow = workflows.get_workflow(workflows.STOCK_SCREENING)

        self.assertEqual(
            workflow.required_inputs,
            (
                "user_question",
                "primary_intent",
                "entities",
                "db_path",
                "limit",
                "skip_web_update",
                "skip_finance",
            ),
        )
        self.assertEqual(
            workflow.steps,
            ("select_candidate", "delegate_selected_stock_to_analysis_connector"),
        )
        self.assertTrue(workflow.update_allowed)
        self.assertEqual(
            workflow.stop_conditions,
            ("missing_required_information", "no_candidate"),
        )

    def test_terminal_workflows_do_not_include_analysis_steps(self) -> None:
        for name in (
            workflows.FOLLOWUP_REQUIRED,
            workflows.UNSUPPORTED,
            workflows.SYSTEM_ERROR,
        ):
            workflow = workflows.get_workflow(name)
            joined_steps = " ".join(workflow.steps)

            self.assertFalse(workflow.update_allowed)
            self.assertIn("always_terminal", workflow.stop_conditions)
            self.assertNotIn("analysis_connector", joined_steps)
            self.assertNotIn("report", joined_steps)

    def test_unknown_workflow_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            workflows.get_workflow("missing_workflow")


if __name__ == "__main__":
    unittest.main()
