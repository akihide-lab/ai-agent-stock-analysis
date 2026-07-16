from __future__ import annotations

import argparse
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PROJECT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import dispatcher
import orchestrator
import question_agent
from workflows import (
    AgentState,
    FOLLOWUP_REQUIRED,
    SINGLE_STOCK_ANALYSIS,
    STOCK_SCREENING,
    SYSTEM_ERROR,
    UNSUPPORTED,
    get_workflow,
)


def make_db(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE v_agent_stock_master (
                stock_code TEXT,
                stock_name TEXT,
                market TEXT,
                sector TEXT
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO v_agent_stock_master
                (stock_code, stock_name, market, sector)
            VALUES (?, ?, ?, ?)
            """,
            [
                ("7203", "トヨタ自動車", "東証プライム", "輸送用機器"),
                ("9434", "ソフトバンク株式会社", "東証プライム", "情報・通信業"),
                ("9984", "ソフトバンクグループ株式会社", "東証プライム", "情報・通信業"),
            ],
        )
        connection.execute(
            """
            CREATE TABLE v_agent_data_freshness (
                data_name TEXT,
                latest_date TEXT,
                record_count INTEGER
            )
            """
        )
        connection.execute(
            """
            INSERT INTO v_agent_data_freshness
                (data_name, latest_date, record_count)
            VALUES ('stock_master', '2026-07-13', 3)
            """
        )


def args_for(question: str, db_path: Path, **overrides: object) -> argparse.Namespace:
    values = {
        "question": question,
        "db": db_path,
        "limit": 5,
        "dry_run": False,
        "skip_web_update": True,
        "skip_finance": False,
        "job_id": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


class OrchestrationLayerTest(unittest.TestCase):
    def setUp(self) -> None:
        self.log_temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.original_log_directory = question_agent.LOG_DIRECTORY
        self.original_orchestrator_log_directory = orchestrator.qa.LOG_DIRECTORY
        question_agent.LOG_DIRECTORY = Path(self.log_temp.name)
        orchestrator.qa.LOG_DIRECTORY = Path(self.log_temp.name)

    def tearDown(self) -> None:
        question_agent.LOG_DIRECTORY = self.original_log_directory
        orchestrator.qa.LOG_DIRECTORY = self.original_orchestrator_log_directory
        self.log_temp.cleanup()

    def test_domain_outside_does_not_call_analysis(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "stocks.db"
            with mock.patch.object(dispatcher.qa, "run_report") as run_report:
                result = orchestrator.run(args_for("今日の天気を教えて", db_path))

        self.assertEqual(result.state, AgentState.UNSUPPORTED)
        self.assertEqual(result.workflow_name, UNSUPPORTED)
        run_report.assert_not_called()

    def test_insufficient_information_stops_at_followup(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "stocks.db"
            with mock.patch.object(dispatcher.qa, "run_report") as run_report:
                result = orchestrator.run(args_for("おすすめの株教えて", db_path))

        self.assertEqual(result.state, AgentState.NEEDS_FOLLOWUP)
        self.assertEqual(result.workflow_name, FOLLOWUP_REQUIRED)
        run_report.assert_not_called()

    def test_multiple_stock_candidates_stop_at_followup(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "stocks.db"
            make_db(db_path)
            with mock.patch.object(dispatcher.qa, "run_report") as run_report:
                result = orchestrator.run(args_for("ソフトバンクを分析して", db_path))

        self.assertEqual(result.state, AgentState.NEEDS_FOLLOWUP)
        self.assertEqual(result.workflow_name, FOLLOWUP_REQUIRED)
        run_report.assert_not_called()

    def test_unknown_stock_does_not_call_analysis(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "stocks.db"
            make_db(db_path)
            with mock.patch.object(dispatcher.qa, "run_report") as run_report:
                result = orchestrator.run(args_for("存在しない銘柄名を分析して", db_path))

        self.assertEqual(result.state, AgentState.NEEDS_FOLLOWUP)
        run_report.assert_not_called()

    def test_unsupported_intent_stops(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "stocks.db"
            with mock.patch.object(dispatcher.qa, "run_report") as run_report:
                result = orchestrator.run(args_for("メールでこの分析を送信して", db_path))

        self.assertEqual(result.state, AgentState.UNSUPPORTED)
        self.assertEqual(result.workflow_name, UNSUPPORTED)
        run_report.assert_not_called()

    def test_system_error_returns_failed_safely(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "missing.db"
            result = orchestrator.run(args_for("7203を分析して", db_path))

        self.assertEqual(result.state, AgentState.FAILED)
        self.assertEqual(result.workflow_name, SYSTEM_ERROR)
        self.assertEqual(result.decision.route, "system_error")
        self.assertIn("処理中にシステム側の問題", result.decision.message)

    def test_no_direct_database_patterns_in_orchestrator(self) -> None:
        source = Path(orchestrator.__file__).read_text(encoding="utf-8")

        self.assertNotIn("sqlite3", source)
        self.assertNotIn("sqlite_master", source)
        self.assertNotIn("PRAGMA", source)
        self.assertNotIn("connect_database", source)

    def test_postgres_ready_single_stock_uses_analysis_connector_without_sqlite_path(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "missing.db"
            master = pd.DataFrame(
                columns=["stock_code", "stock_name", "market", "sector", "name_norm"]
            )
            classification = question_agent.ClassificationResult(
                status="classified",
                intent="Intent008 蜊倅ｸ驫俶氛蛻・梵",
                entities={
                    "銘柄": [
                        {
                            "stock_code": "9202",
                            "stock_name": "ANAホールディングス",
                            "sector": "航空",
                        }
                    ]
                },
                confidence=0.90,
            )
            analysis_result = SimpleNamespace(
                succeeded=True,
                report_path=str(Path(temp_dir) / "report.html"),
                followup_question=None,
                route="single_stock_report",
            )
            with mock.patch.dict("os.environ", {"DB_TYPE": "postgres"}, clear=False):
                with mock.patch.object(orchestrator.qa, "load_stock_master", return_value=master):
                    with mock.patch.object(
                        orchestrator.qa,
                        "classify_with_db",
                        return_value=(classification, [], pd.DataFrame()),
                    ):
                        with mock.patch.object(orchestrator.qa, "load_data_freshness", return_value=[]):
                            with mock.patch.object(
                                orchestrator,
                                "run_v1_analysis_flow",
                                return_value=analysis_result,
                            ) as run_flow:
                                with mock.patch.object(dispatcher, "execute") as execute:
                                    result = orchestrator.run(
                                        args_for(
                                            "9202を分析して",
                                            db_path,
                                            skip_web_update=True,
                                            dry_run=False,
                                        )
                                    )

        self.assertEqual(result.state, AgentState.COMPLETED)
        self.assertEqual(result.workflow_name, SINGLE_STOCK_ANALYSIS)
        execute.assert_not_called()
        run_flow.assert_called_once()
        self.assertEqual(run_flow.call_args.kwargs["db_path"], db_path)
        self.assertTrue(run_flow.call_args.kwargs["generate_report"])
        self.assertFalse(run_flow.call_args.kwargs["allow_update"])

    def test_postgres_followup_does_not_start_analysis_connector(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "missing.db"
            master = pd.DataFrame(
                columns=["stock_code", "stock_name", "market", "sector", "name_norm"]
            )
            classification = question_agent.ClassificationResult(
                status="insufficient",
                intent="Intent008 蜊倅ｸ驫俶氛蛻・梵",
                missing_fields=["銘柄"],
                confidence=0.70,
            )
            with mock.patch.dict("os.environ", {"DB_TYPE": "postgres"}, clear=False):
                with mock.patch.object(orchestrator.qa, "load_stock_master", return_value=master):
                    with mock.patch.object(
                        orchestrator.qa,
                        "classify_with_db",
                        return_value=(classification, [], pd.DataFrame()),
                    ):
                        with mock.patch.object(orchestrator, "run_v1_analysis_flow") as run_flow:
                            result = orchestrator.run(
                                args_for("9999を分析して", db_path, dry_run=False)
                            )

        self.assertEqual(result.state, AgentState.NEEDS_FOLLOWUP)
        self.assertEqual(result.workflow_name, FOLLOWUP_REQUIRED)
        run_flow.assert_not_called()

    def test_skip_web_update_true_uses_analysis_connector(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "stocks.db"
            make_db(db_path)
            fake_report = Path(temp_dir) / "report.html"
            analysis_result = SimpleNamespace(
                succeeded=True,
                report_path=str(fake_report),
                followup_question=None,
                route="single_stock_report",
            )
            with mock.patch.object(
                dispatcher,
                "run_v1_analysis_flow",
                return_value=analysis_result,
            ) as run_flow:
                result = orchestrator.run(args_for("7203を分析して", db_path, skip_web_update=True))

        self.assertEqual(result.workflow_name, SINGLE_STOCK_ANALYSIS)
        run_flow.assert_called_once()
        self.assertEqual(run_flow.call_args.kwargs["question"], "7203")
        self.assertFalse(run_flow.call_args.kwargs["allow_update"])
        self.assertEqual(result.decision.report_path, str(fake_report))

    def test_skip_web_update_false_allows_analysis_connector_update(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "stocks.db"
            make_db(db_path)
            fake_report = Path(temp_dir) / "report.html"
            analysis_result = SimpleNamespace(
                succeeded=True,
                report_path=str(fake_report),
                followup_question=None,
                route="single_stock_report",
            )
            with mock.patch.object(
                dispatcher,
                "run_v1_analysis_flow",
                return_value=analysis_result,
            ) as run_flow:
                result = orchestrator.run(args_for("7203を分析して", db_path, skip_web_update=False))

        self.assertEqual(result.workflow_name, SINGLE_STOCK_ANALYSIS)
        run_flow.assert_called_once()
        self.assertEqual(run_flow.call_args.kwargs["question"], "7203")
        self.assertTrue(run_flow.call_args.kwargs["allow_update"])

    def test_dispatcher_only_executes_selected_terminal_workflow(self) -> None:
        decision = question_agent.QuestionDecision(
            user_question="おすすめの株教えて",
            primary_intent="Intent001 おすすめ銘柄検索",
            message="投資目的を教えてください。",
        )
        with mock.patch.object(dispatcher, "run_v1_analysis_flow") as run_flow:
            result = dispatcher.execute(
                get_workflow(FOLLOWUP_REQUIRED),
                decision=decision,
                db_path=Path("dummy.db"),
                skip_web_update=True,
                skip_finance=False,
                dry_run=False,
                limit=5,
            )

        self.assertTrue(result.succeeded)
        run_flow.assert_not_called()

    def test_stock_screening_dispatcher_selects_candidate_without_own_judgment(self) -> None:
        decision = question_agent.QuestionDecision(
            user_question="安定した株を探して",
            primary_intent="Intent005 安定銘柄検索",
            entities={"投資目的": "安定性"},
        )
        candidates = pd.DataFrame(
            [{"stock_code": "7203", "stock_name": "トヨタ自動車"}]
        )
        with mock.patch.object(dispatcher.qa, "select_candidate", return_value=(candidates, ["reason"])):
            with mock.patch.object(dispatcher, "run_v1_analysis_flow") as run_flow:
                result = dispatcher.execute(
                    get_workflow(STOCK_SCREENING),
                    decision=decision,
                    db_path=Path("dummy.db"),
                    skip_web_update=True,
                    skip_finance=False,
                    dry_run=True,
                    limit=5,
                )

        self.assertTrue(result.succeeded)
        self.assertEqual(decision.selected_stock_code, "7203")
        run_flow.assert_not_called()


if __name__ == "__main__":
    unittest.main()
