"""One-command flow: fetch latest Web data, compare, update, analyze, report."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from generate_stock_report import DEFAULT_DB_PATH, generate_report


PROJECT_ROOT = Path(__file__).resolve().parents[1]
UPDATE_SCRIPT = PROJECT_ROOT / "scripts" / "update_market_data.py"
OFFICIAL_MACRO_SCRIPT = PROJECT_ROOT / "scripts" / "update_official_macro_web.py"
LOG_DIRECTORY = PROJECT_ROOT / "logs"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "指定銘柄の最新Webデータを取得・DB比較し、"
            "分析HTMLレポートを生成します。"
        )
    )
    parser.add_argument("stock_code", help="例: 9202")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--skip-finance",
        action="store_true",
        help="財務データのWeb取得を省略します。",
    )
    return parser.parse_args()


def newest_update_log(after: datetime) -> Path | None:
    candidates = [
        path
        for path in LOG_DIRECTORY.glob("market_data_update_*.json")
        if datetime.fromtimestamp(path.stat().st_mtime) >= after
    ]
    return max(candidates, key=lambda path: path.stat().st_mtime, default=None)


def newest_official_log(after: datetime) -> Path | None:
    candidates = [
        path
        for path in LOG_DIRECTORY.glob("official_macro_update_*.json")
        if datetime.fromtimestamp(path.stat().st_mtime) >= after
    ]
    return max(candidates, key=lambda path: path.stat().st_mtime, default=None)


def run_official_macro_update(database: Path) -> dict[str, object]:
    started_at = datetime.now()
    process = subprocess.run(
        [
            sys.executable,
            str(OFFICIAL_MACRO_SCRIPT),
            "--db",
            str(database),
        ],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        check=False,
    )
    if process.returncode == 0:
        log_path = newest_official_log(started_at)
        if log_path:
            return json.loads(log_path.read_text(encoding="utf-8"))
        return {"comparisons": {}, "failures": {}}
    return {
        "comparisons": {},
        "failures": {
            "official_macro_web": (
                process.stderr[-3000:]
                or process.stdout[-3000:]
                or f"終了コード {process.returncode}"
            )
        },
    }


def merge_acquisition_results(
    market: dict[str, object],
    official: dict[str, object],
) -> dict[str, object]:
    merged = dict(market)
    merged["comparisons"] = {
        **market.get("comparisons", {}),
        **official.get("comparisons", {}),
    }
    merged["failures"] = {
        **market.get("failures", {}),
        **official.get("failures", {}),
    }
    merged["official_macro_updated_at"] = official.get("updated_at")
    return merged


def run_web_update(
    stock_code: str,
    database: Path,
    skip_finance: bool,
) -> dict[str, object]:
    started_at = datetime.now()
    command = [
        sys.executable,
        str(UPDATE_SCRIPT),
        "--db",
        str(database),
        "--stock-code",
        stock_code,
    ]
    if skip_finance:
        command.append("--skip-finance")
    process = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=900,
        check=False,
    )
    if process.returncode == 0:
        log_path = newest_update_log(started_at)
        if log_path:
            result = json.loads(log_path.read_text(encoding="utf-8"))
            result["update_stdout_tail"] = process.stdout[-2000:]
            return result
        return {
            "updated_at": datetime.now().astimezone().isoformat(),
            "comparisons": {},
            "failures": {},
            "warning": "更新処理は成功しましたが更新ログを検出できませんでした。",
        }
    return {
        "updated_at": datetime.now().astimezone().isoformat(),
        "comparisons": {},
        "failures": {
            "web_update": (
                process.stderr[-3000:]
                or process.stdout[-3000:]
                or f"終了コード {process.returncode}"
            )
        },
        "fallback": "Web取得に失敗したため既存DBでレポートを生成",
    }


def main() -> None:
    args = parse_args()
    database = args.db.expanduser().resolve(strict=True)
    market_acquisition = run_web_update(
        args.stock_code,
        database,
        args.skip_finance,
    )
    official_acquisition = run_official_macro_update(database)
    acquisition = merge_acquisition_results(
        market_acquisition,
        official_acquisition,
    )
    acquisition_log = (
        LOG_DIRECTORY
        / f"stock_acquisition_{args.stock_code}_"
        f"{datetime.now().astimezone():%Y%m%d_%H%M%S}.json"
    )
    acquisition_log.write_text(
        json.dumps(acquisition, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    destination = generate_report(
        args.stock_code,
        database,
        args.output,
        acquisition,
    )
    print(f"取得・比較・分析・HTML生成が完了しました: {destination}")
    print(f"取得比較ログ: {acquisition_log}")
    if acquisition.get("failures"):
        print("一部取得に失敗したため、該当データは既存DB値を使用しました。")


if __name__ == "__main__":
    main()
