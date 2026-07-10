"""Run the existing macro importer safely against a staging database."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
from contextlib import closing
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "market_analysis.db"
DEFAULT_SOURCE_DATA = (
    Path.home()
    / "OneDrive"
    / "デスクトップ"
    / "F_ファイル"
    / "研修"
    / "研修課題５"
    / "data"
)
LEGACY_IMPORTER = PROJECT_ROOT / "scripts" / "legacy_analysis" / "import_macro_data.py"
REQUIRED_FILES = [
    "zmi2020r.csv",
    "zmm2020r.csv",
    "gaku-jfy2612.csv",
    "ritu-jfy2612.csv",
    "jgbcm_all.csv",
    "nme_R031.793954.20260615104522.02.csv",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="既存CSVと既存Pythonを使い、マクロテーブルを安全に更新します。"
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--source-data", type=Path, default=DEFAULT_SOURCE_DATA)
    return parser.parse_args()


def validate(connection: sqlite3.Connection) -> dict[str, object]:
    if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
        raise RuntimeError("SQLite quick_checkに失敗しました")
    result: dict[str, object] = {}
    for table, date_column in (
        ("cpi", "year_month"),
        ("gdp", "fiscal_year"),
        ("interest_rate_long", "date"),
        ("policy_rate", "year_month"),
        ("exchange_rates", "date"),
        ("oil_prices", "date"),
    ):
        result[table] = connection.execute(
            f"SELECT COUNT(*), MIN({date_column}), MAX({date_column}) FROM {table}"
        ).fetchone()
    result["ai_view"] = connection.execute(
        "SELECT COUNT(*), MIN(trade_date), MAX(trade_date) "
        "FROM v_ai_stock_report_input"
    ).fetchone()
    return result


def main() -> None:
    args = parse_args()
    database = args.db.expanduser().resolve(strict=True)
    source_data = args.source_data.expanduser().resolve(strict=True)
    missing = [name for name in REQUIRED_FILES if not (source_data / name).is_file()]
    if missing:
        raise FileNotFoundError(f"必要なCSVがありません: {', '.join(missing)}")

    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    work_root = database.parent / f".macro_import_{timestamp}"
    work_db_dir = work_root / "db"
    work_data_dir = work_root / "data"
    work_python_dir = work_root / "python"
    work_db_dir.mkdir(parents=True)
    work_data_dir.mkdir()
    work_python_dir.mkdir()
    staging_db = work_db_dir / "stock_analysis.db"
    shutil.copy2(database, staging_db)
    for name in REQUIRED_FILES:
        shutil.copy2(source_data / name, work_data_dir / name)
    shutil.copy2(LEGACY_IMPORTER, work_python_dir / "import_macro_data.py")

    process = subprocess.run(
        [sys.executable, str(work_python_dir / "import_macro_data.py")],
        cwd=work_root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=600,
        check=False,
    )
    if process.returncode != 0:
        raise RuntimeError(
            "既存マクロ取込処理が失敗しました\n"
            + process.stdout[-2000:]
            + "\n"
            + process.stderr[-4000:]
        )

    with closing(sqlite3.connect(staging_db)) as connection:
        validation = validate(connection)

    backup_directory = database.parent / "backups"
    backup_directory.mkdir(exist_ok=True)
    backup = backup_directory / f"{database.stem}_before_macro_{timestamp}.db"
    shutil.copy2(database, backup)
    os.replace(staging_db, database)
    shutil.rmtree(work_root, ignore_errors=True)

    summary = {
        "updated_at": datetime.now().astimezone().isoformat(),
        "database": str(database),
        "backup": str(backup),
        "source_data": str(source_data),
        "legacy_importer": str(LEGACY_IMPORTER),
        "validation": validation,
        "stdout_tail": process.stdout[-2000:],
    }
    log_path = PROJECT_ROOT / "logs" / f"macro_data_update_{timestamp}.json"
    log_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"更新ログ: {log_path}")


if __name__ == "__main__":
    main()
