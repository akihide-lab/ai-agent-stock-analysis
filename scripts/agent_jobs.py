"""Background job helpers for the question agent.

This module does not execute SQL DDL. It only starts existing Python flows and
records progress to JSON files under logs/.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOG_DIRECTORY = PROJECT_ROOT / "logs"
QUESTION_AGENT_SCRIPT = PROJECT_ROOT / "scripts" / "question_agent.py"
AGENT_JOBS_SCRIPT = PROJECT_ROOT / "scripts" / "agent_jobs.py"
ANALYZE_STOCK_SCRIPT = PROJECT_ROOT / "scripts" / "analyze_stock.py"
REPORT_DIRECTORY = PROJECT_ROOT / "reports"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def job_path(job_id: str) -> Path:
    return LOG_DIRECTORY / f"job_{job_id}.json"


def job_stdout_path(job_id: str) -> Path:
    return LOG_DIRECTORY / f"job_{job_id}.out.txt"


def job_stderr_path(job_id: str) -> Path:
    return LOG_DIRECTORY / f"job_{job_id}.err.txt"


def job_context_path(job_id: str) -> Path:
    return REPORT_DIRECTORY / f"job_{job_id}_context.json"


def job_report_path(job_id: str) -> Path:
    return REPORT_DIRECTORY / f"job_{job_id}_report.html"


def load_job(job_id: str) -> dict[str, Any]:
    path = job_path(job_id)
    if not path.exists():
        raise FileNotFoundError(f"ジョブが見つかりません: {job_id}")
    return json.loads(path.read_text(encoding="utf-8"))


def save_job(job_id: str, payload: dict[str, Any]) -> Path:
    LOG_DIRECTORY.mkdir(exist_ok=True)
    payload["job_id"] = job_id
    payload["updated_at"] = now_iso()
    path = job_path(job_id)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def create_job(question: str, options: dict[str, Any]) -> tuple[str, Path]:
    job_id = datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]
    payload = {
        "job_id": job_id,
        "question": question,
        "status": "queued",
        "stage": "created",
        "created_at": now_iso(),
        "started_at": None,
        "finished_at": None,
        "options": options,
        "selected_stock_code": None,
        "selected_stock_name": None,
        "report_path": None,
        "question_flow_log": None,
        "error": None,
    }
    return job_id, save_job(job_id, payload)


def update_job(job_id: str, **updates: Any) -> Path:
    payload = load_job(job_id)
    payload.update(updates)
    return save_job(job_id, payload)


def finish_job(job_id: str, **updates: Any) -> Path:
    payload = load_job(job_id)
    payload.update(updates)
    payload["finished_at"] = now_iso()
    return save_job(job_id, payload)


def _command_option(command: list[str], option: str) -> str | None:
    try:
        index = command.index(option)
    except ValueError:
        return None
    if index + 1 >= len(command):
        return None
    return command[index + 1]


def _analysis_readiness(json_payload: dict[str, Any]) -> dict[str, Any]:
    context = json_payload.get("analysis_context") or {}
    retrieved = context.get("retrieved_context") or {}
    for result in retrieved.get("rdb_results") or []:
        if result.get("target") != "analysis_readiness":
            continue
        rows = result.get("rows") or []
        if rows:
            return rows[0]
    return {}


def _apply_analysis_result(job_id: str, returncode: int, output_json: Path | None) -> None:
    if returncode != 0:
        finish_job(
            job_id,
            status="failed",
            stage="worker_failed",
            returncode=returncode,
            error=f"analyze_stock.py exited with code {returncode}",
        )
        return

    if output_json is None or not output_json.exists():
        finish_job(
            job_id,
            status="failed",
            stage="result_json_missing",
            returncode=returncode,
            error="analysis result JSON was not generated",
        )
        return

    try:
        result = json.loads(output_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        finish_job(
            job_id,
            status="failed",
            stage="result_json_invalid",
            returncode=returncode,
            error=f"analysis result JSON could not be parsed: {exc}",
        )
        return

    context = result.get("analysis_context") or {}
    readiness = _analysis_readiness(result)
    route = result.get("route")
    succeeded = bool(result.get("succeeded"))
    followup_question = result.get("followup_question")
    updates = {
        "returncode": returncode,
        "analysis_result_json": str(output_json),
        "route": route,
        "succeeded": succeeded,
        "selected_stock_code": context.get("selected_stock_code"),
        "selected_stock_name": context.get("selected_stock_name"),
        "report_path": result.get("report_path"),
        "complete_rows": readiness.get("complete_rows"),
        "total_rows": readiness.get("total_rows"),
        "warnings": result.get("warnings") or [],
    }

    if route == "followup_required" and followup_question:
        finish_job(
            job_id,
            **updates,
            status="needs_followup",
            stage="followup_required",
            followup_question=followup_question,
        )
        return

    if succeeded:
        finish_job(job_id, **updates, status="succeeded", stage="completed")
        return

    finish_job(
        job_id,
        **updates,
        status="failed",
        stage="analysis_failed",
        error="analysis did not succeed",
    )


def build_question_agent_command(args: argparse.Namespace, job_id: str) -> list[str]:
    return build_analyze_stock_command(args, job_id)


def build_analyze_stock_command(args: argparse.Namespace, job_id: str) -> list[str]:
    python_executable = Path(sys.executable)
    if sys.platform == "win32":
        pythonw = python_executable.with_name("pythonw.exe")
        if pythonw.exists():
            python_executable = pythonw
    output_json = getattr(args, "output_json", None) or job_context_path(job_id)
    context_only = bool(getattr(args, "context_only", False) or getattr(args, "dry_run", False))
    command = [
        str(python_executable),
        str(ANALYZE_STOCK_SCRIPT),
        args.question,
        "--output-json",
        str(output_json),
    ]
    if args.db:
        command.extend(["--db", str(args.db)])
    if context_only:
        command.append("--context-only")
    else:
        output = getattr(args, "output", None) or job_report_path(job_id)
        command.extend(["--output", str(output)])
    if args.skip_web_update:
        command.append("--skip-web-update")
    if args.skip_finance:
        command.append("--skip-finance")
    return command


def start_job(args: argparse.Namespace) -> str:
    options = {
        "limit": args.limit,
        "db": str(args.db) if args.db else None,
        "dry_run": args.dry_run,
        "skip_web_update": args.skip_web_update,
        "skip_finance": args.skip_finance,
        "context_only": getattr(args, "context_only", False),
        "output": str(args.output) if getattr(args, "output", None) else None,
        "output_json": str(args.output_json) if getattr(args, "output_json", None) else None,
    }
    job_id, _ = create_job(args.question, options)
    command = build_analyze_stock_command(args, job_id)
    worker_command = [str(sys.executable), str(AGENT_JOBS_SCRIPT), "run", job_id]
    update_job(
        job_id,
        status="running",
        stage="starting_process",
        started_at=now_iso(),
        command=command,
        worker_command=worker_command,
        output_json_path=_command_option(command, "--output-json"),
        stdout_path=str(job_stdout_path(job_id)),
        stderr_path=str(job_stderr_path(job_id)),
    )

    creationflags = 0
    if sys.platform == "win32":
        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    with job_stdout_path(job_id).open("w", encoding="utf-8") as stdout:
        with job_stderr_path(job_id).open("w", encoding="utf-8") as stderr:
            process = subprocess.Popen(
                worker_command,
                cwd=PROJECT_ROOT,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creationflags,
                close_fds=True,
                env=env,
            )
    time.sleep(0.5)
    returncode = process.poll()
    update_job(
        job_id,
        pid=process.pid,
        returncode=returncode,
        status="failed" if returncode not in (None, 0) else "running",
        stage="process_exited" if returncode not in (None, 0) else "process_started",
    )
    return job_id


def create_queued_job(args: argparse.Namespace) -> str:
    options = {
        "limit": args.limit,
        "db": str(args.db) if args.db else None,
        "dry_run": args.dry_run,
        "skip_web_update": args.skip_web_update,
        "skip_finance": args.skip_finance,
        "context_only": getattr(args, "context_only", False),
        "output": str(args.output) if getattr(args, "output", None) else None,
        "output_json": str(args.output_json) if getattr(args, "output_json", None) else None,
    }
    job_id, _ = create_job(args.question, options)
    command = build_analyze_stock_command(args, job_id)
    update_job(
        job_id,
        stage="queued_for_worker",
        command=command,
        output_json_path=_command_option(command, "--output-json"),
    )
    return job_id


def run_job(job_id: str) -> None:
    payload = load_job(job_id)
    command = payload.get("command")
    if not command:
        options = payload.get("options") or {}
        namespace = argparse.Namespace(
            question=payload["question"],
            db=Path(options["db"]) if options.get("db") else None,
            limit=options.get("limit", 5),
            dry_run=options.get("dry_run", False),
            skip_web_update=options.get("skip_web_update", False),
            skip_finance=options.get("skip_finance", False),
            context_only=options.get("context_only", False),
            output=Path(options["output"]) if options.get("output") else None,
            output_json=Path(options["output_json"]) if options.get("output_json") else None,
        )
        command = build_analyze_stock_command(namespace, job_id)
    command = list(command)
    command[0] = sys.executable
    output_json = _command_option(command, "--output-json")
    update_job(
        job_id,
        status="running",
        stage="worker_running",
        started_at=payload.get("started_at") or now_iso(),
        command=command,
        output_json_path=output_json,
    )
    with job_stdout_path(job_id).open("a", encoding="utf-8") as stdout:
        with job_stderr_path(job_id).open("a", encoding="utf-8") as stderr:
            process = subprocess.run(
                command,
                cwd=PROJECT_ROOT,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=None,
                check=False,
            )
    _apply_analysis_result(
        job_id,
        process.returncode,
        Path(output_json) if output_json else None,
    )


def print_job(job_id: str) -> None:
    payload = load_job(job_id)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def list_jobs(limit: int) -> None:
    paths = sorted(LOG_DIRECTORY.glob("job_*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
    rows = []
    for path in paths[:limit]:
        payload = json.loads(path.read_text(encoding="utf-8"))
        rows.append(
            {
                "job_id": payload.get("job_id"),
                "status": payload.get("status"),
                "stage": payload.get("stage"),
                "question": payload.get("question"),
                "report_path": payload.get("report_path"),
                "updated_at": payload.get("updated_at"),
            }
        )
    print(json.dumps(rows, ensure_ascii=False, indent=2))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="AIエージェントのバックグラウンドジョブを管理します。")
    subparsers = parser.add_subparsers(dest="command", required=True)

    start = subparsers.add_parser("start", help="質問処理をバックグラウンドで開始します（実験的）。")
    start.add_argument("question")
    start.add_argument("--db", type=Path)
    start.add_argument("--limit", type=int, default=5)
    start.add_argument("--dry-run", action="store_true")
    start.add_argument("--skip-web-update", action="store_true")
    start.add_argument("--skip-finance", action="store_true")
    start.add_argument("--context-only", action="store_true")
    start.add_argument("--output", type=Path)
    start.add_argument("--output-json", type=Path)

    create = subparsers.add_parser("create", help="ジョブJSONだけ作成し、実行はワーカーに任せます。")
    create.add_argument("question")
    create.add_argument("--db", type=Path)
    create.add_argument("--limit", type=int, default=5)
    create.add_argument("--dry-run", action="store_true")
    create.add_argument("--skip-web-update", action="store_true")
    create.add_argument("--skip-finance", action="store_true")
    create.add_argument("--context-only", action="store_true")
    create.add_argument("--output", type=Path)
    create.add_argument("--output-json", type=Path)

    status = subparsers.add_parser("status", help="ジョブ状態を表示します。")
    status.add_argument("job_id")

    run = subparsers.add_parser("run", help="作成済みジョブを現在のプロセスで実行します。")
    run.add_argument("job_id")

    recent = subparsers.add_parser("list", help="最近のジョブ一覧を表示します。")
    recent.add_argument("--limit", type=int, default=10)

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.command == "start":
        job_id = start_job(args)
        print(f"ジョブを開始しました: {job_id}")
        print(f"状態確認: {sys.executable} {AGENT_JOBS_SCRIPT} status {job_id}")
    elif args.command == "create":
        job_id = create_queued_job(args)
        print(f"ジョブを作成しました: {job_id}")
        print(f"実行: {sys.executable} {AGENT_JOBS_SCRIPT} run {job_id}")
    elif args.command == "status":
        print_job(args.job_id)
    elif args.command == "run":
        run_job(args.job_id)
        print_job(args.job_id)
    elif args.command == "list":
        list_jobs(args.limit)


if __name__ == "__main__":
    main()
