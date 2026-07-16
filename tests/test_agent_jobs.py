from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import agent_jobs


def _args(**overrides: object) -> argparse.Namespace:
    values = {
        "question": "9202",
        "db": None,
        "limit": 5,
        "dry_run": False,
        "skip_web_update": False,
        "skip_finance": False,
        "context_only": False,
        "output": None,
        "output_json": None,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def _analysis_json(
    *,
    succeeded: bool = True,
    route: str = "single_stock_report",
    followup_question: str | None = None,
    report_path: str | None = "report.html",
) -> dict[str, object]:
    return {
        "analysis_context": {
            "selected_stock_code": "9202",
            "selected_stock_name": "ANAホールディングス",
            "retrieved_context": {
                "rdb_results": [
                    {
                        "target": "analysis_readiness",
                        "rows": [{"complete_rows": 1470, "total_rows": 1578}],
                    }
                ]
            },
        },
        "report_path": report_path,
        "route": route,
        "succeeded": succeeded,
        "warnings": [],
        "followup_question": followup_question,
        "stock_candidates": [],
    }


class AgentJobsTests(unittest.TestCase):
    def test_no_direct_database_patterns(self) -> None:
        source = Path(agent_jobs.__file__).read_text(encoding="utf-8")

        self.assertNotIn("sqlite3", source)
        self.assertNotIn("sqlite_master", source)
        self.assertNotIn("PRAGMA", source)
        self.assertNotIn("connect_database", source)
        self.assertNotIn("shell=True", source)

    def test_command_uses_analyze_stock_without_default_db(self) -> None:
        command = agent_jobs.build_analyze_stock_command(
            _args(context_only=True, skip_web_update=True),
            "job123",
        )

        self.assertIn(str(agent_jobs.ANALYZE_STOCK_SCRIPT), command)
        self.assertNotIn(str(agent_jobs.QUESTION_AGENT_SCRIPT), command)
        self.assertNotIn("--db", command)
        self.assertIn("--context-only", command)
        self.assertIn("--skip-web-update", command)
        self.assertIn("--output-json", command)

    def test_command_passes_supported_cli_arguments(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "market_analysis.db"
            output_path = Path(temp_dir) / "report.html"
            output_json = Path(temp_dir) / "context.json"

            command = agent_jobs.build_analyze_stock_command(
                _args(
                    db=db_path,
                    output=output_path,
                    output_json=output_json,
                    skip_finance=True,
                    skip_web_update=True,
                ),
                "job123",
            )

        self.assertIn("--db", command)
        self.assertEqual(command[command.index("--db") + 1], str(db_path))
        self.assertIn("--output", command)
        self.assertEqual(command[command.index("--output") + 1], str(output_path))
        self.assertIn("--output-json", command)
        self.assertEqual(command[command.index("--output-json") + 1], str(output_json))
        self.assertIn("--skip-finance", command)
        self.assertIn("--skip-web-update", command)

    def test_command_maps_dry_run_to_context_only(self) -> None:
        command = agent_jobs.build_analyze_stock_command(_args(dry_run=True), "job123")

        self.assertIn("--context-only", command)
        self.assertNotIn("--output", command)

    def test_apply_analysis_result_marks_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original_log_directory = agent_jobs.LOG_DIRECTORY
            agent_jobs.LOG_DIRECTORY = Path(temp_dir)
            try:
                job_id, _ = agent_jobs.create_job("9202", {})
                output_json = Path(temp_dir) / "context.json"
                output_json.write_text(
                    json.dumps(_analysis_json(), ensure_ascii=False),
                    encoding="utf-8",
                )

                agent_jobs._apply_analysis_result(job_id, 0, output_json)
                payload = agent_jobs.load_job(job_id)
            finally:
                agent_jobs.LOG_DIRECTORY = original_log_directory

        self.assertEqual(payload["status"], "succeeded")
        self.assertEqual(payload["stage"], "completed")
        self.assertEqual(payload["route"], "single_stock_report")
        self.assertEqual(payload["complete_rows"], 1470)
        self.assertEqual(payload["total_rows"], 1578)

    def test_apply_analysis_result_marks_followup_as_non_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original_log_directory = agent_jobs.LOG_DIRECTORY
            agent_jobs.LOG_DIRECTORY = Path(temp_dir)
            try:
                job_id, _ = agent_jobs.create_job("9999", {})
                output_json = Path(temp_dir) / "context.json"
                output_json.write_text(
                    json.dumps(
                        _analysis_json(
                            succeeded=False,
                            route="followup_required",
                            followup_question="銘柄コードを教えてください。",
                            report_path=None,
                        ),
                        ensure_ascii=False,
                    ),
                    encoding="utf-8",
                )

                agent_jobs._apply_analysis_result(job_id, 0, output_json)
                payload = agent_jobs.load_job(job_id)
            finally:
                agent_jobs.LOG_DIRECTORY = original_log_directory

        self.assertEqual(payload["status"], "needs_followup")
        self.assertEqual(payload["stage"], "followup_required")
        self.assertFalse(payload["succeeded"])
        self.assertEqual(payload["route"], "followup_required")
        self.assertIn("銘柄コード", payload["followup_question"])

    def test_apply_analysis_result_marks_missing_json_as_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original_log_directory = agent_jobs.LOG_DIRECTORY
            agent_jobs.LOG_DIRECTORY = Path(temp_dir)
            try:
                job_id, _ = agent_jobs.create_job("9202", {})

                agent_jobs._apply_analysis_result(
                    job_id,
                    0,
                    Path(temp_dir) / "missing.json",
                )
                payload = agent_jobs.load_job(job_id)
            finally:
                agent_jobs.LOG_DIRECTORY = original_log_directory

        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["stage"], "result_json_missing")

    def test_apply_analysis_result_marks_nonzero_exit_as_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original_log_directory = agent_jobs.LOG_DIRECTORY
            agent_jobs.LOG_DIRECTORY = Path(temp_dir)
            try:
                job_id, _ = agent_jobs.create_job("9202", {})

                agent_jobs._apply_analysis_result(job_id, 1, None)
                payload = agent_jobs.load_job(job_id)
            finally:
                agent_jobs.LOG_DIRECTORY = original_log_directory

        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["stage"], "worker_failed")

    def test_run_job_updates_from_output_json(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            original_log_directory = agent_jobs.LOG_DIRECTORY
            agent_jobs.LOG_DIRECTORY = Path(temp_dir)
            try:
                output_json = Path(temp_dir) / "context.json"
                job_id, _ = agent_jobs.create_job(
                    "9202",
                    {"output_json": str(output_json), "context_only": True},
                )
                command = agent_jobs.build_analyze_stock_command(
                    _args(context_only=True, output_json=output_json),
                    job_id,
                )
                agent_jobs.update_job(job_id, command=command)

                def fake_run(*_: object, **__: object) -> object:
                    output_json.write_text(
                        json.dumps(_analysis_json(report_path=None), ensure_ascii=False),
                        encoding="utf-8",
                    )
                    return argparse.Namespace(returncode=0)

                with mock.patch.object(agent_jobs.subprocess, "run", side_effect=fake_run):
                    agent_jobs.run_job(job_id)
                payload = agent_jobs.load_job(job_id)
            finally:
                agent_jobs.LOG_DIRECTORY = original_log_directory

        self.assertEqual(payload["status"], "succeeded")
        self.assertEqual(payload["output_json_path"], str(output_json))


if __name__ == "__main__":
    unittest.main()
