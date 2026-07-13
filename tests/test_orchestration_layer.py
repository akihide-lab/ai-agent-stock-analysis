from __future__ import annotations

import argparse
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
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

    def test_skip_web_update_true_uses_existing_db_report_path(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "stocks.db"
            make_db(db_path)
            fake_report = Path(temp_dir) / "report.html"
            with mock.patch.object(dispatcher.qa, "run_report", return_value=fake_report) as run_report:
                result = orchestrator.run(args_for("7203を分析して", db_path, skip_web_update=True))

        self.assertEqual(result.workflow_name, SINGLE_STOCK_ANALYSIS)
        run_report.assert_called_once_with("7203", db_path.resolve(), True, False)
        self.assertEqual(result.decision.report_path, str(fake_report))

    def test_skip_web_update_false_uses_analyze_stock_route(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "stocks.db"
            make_db(db_path)
            fake_report = Path(temp_dir) / "report.html"
            with mock.patch.object(dispatcher.qa, "run_report", return_value=fake_report) as run_report:
                result = orchestrator.run(args_for("7203を分析して", db_path, skip_web_update=False))

        self.assertEqual(result.workflow_name, SINGLE_STOCK_ANALYSIS)
        run_report.assert_called_once_with("7203", db_path.resolve(), False, False)

    def test_dispatcher_only_executes_selected_terminal_workflow(self) -> None:
        decision = question_agent.QuestionDecision(
            user_question="おすすめの株教えて",
            primary_intent="Intent001 おすすめ銘柄検索",
            message="投資目的を教えてください。",
        )
        with mock.patch.object(dispatcher.qa, "run_report") as run_report:
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
        run_report.assert_not_called()

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
            with mock.patch.object(dispatcher.qa, "run_report") as run_report:
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
        run_report.assert_not_called()


if __name__ == "__main__":
    unittest.main()
