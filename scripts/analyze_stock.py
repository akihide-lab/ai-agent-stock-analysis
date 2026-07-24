"""CLI entry point for single-stock analysis."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from analysis_connector import run_v1_analysis_flow
from generate_stock_report import DEFAULT_DB_PATH
from logging_config import setup_logging
from query_flow_models import to_plain_data


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_JSON = PROJECT_ROOT / "logs" / "analysis_context_latest.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the existing single-stock analysis flow from the CLI."
    )
    parser.add_argument("stock_code", help="Example: 9202")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--skip-finance",
        action="store_true",
        help="Accepted for backward compatibility; data updates are delegated.",
    )
    parser.add_argument(
        "--skip-web-update",
        action="store_true",
        help="Skip delegated update handling and use existing configured data only.",
    )
    parser.add_argument(
        "--context-only",
        action="store_true",
        help="Retrieve analysis context without generating an HTML report.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=DEFAULT_OUTPUT_JSON,
        help="Path for the analysis context JSON output.",
    )
    return parser.parse_args()


def _print_result(result: object, output_json: Path | None) -> int:
    if getattr(result, "report_path", None):
        print(f"蜿門ｾ励・豈碑ｼ・・蛻・梵繝ｻHTML逕滓・縺悟ｮ御ｺ・＠縺ｾ縺励◆: {result.report_path}")
    elif getattr(result, "followup_question", None):
        print(result.followup_question)
    else:
        print(json.dumps(to_plain_data(result), ensure_ascii=False, indent=2, default=str))

    if output_json:
        print(f"蛻・梵繧ｳ繝ｳ繝・く繧ｹ繝医Ο繧ｰ: {output_json}")

    warnings = list(getattr(result, "warnings", []) or [])
    context = getattr(result, "analysis_context", None)
    if context is not None:
        warnings.extend(getattr(context, "warnings", []) or [])
    for warning in dict.fromkeys(str(item) for item in warnings if item):
        print(f"warning: {warning}")

    return 0 if getattr(result, "succeeded", False) or getattr(result, "followup_question", None) else 1


def main() -> None:
    setup_logging()
    logging.getLogger(__name__).info("analyze_stock started")
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args()
    if args.output and args.context_only:
        raise SystemExit("--output cannot be used with --context-only.")

    result = run_v1_analysis_flow(
        question=args.stock_code,
        intent_id="Intent008",
        db_path=args.db,
        output_json=args.output_json,
        generate_report=not args.context_only,
        allow_update=not args.skip_web_update,
        limit=1,
        output_path=args.output,
        skip_finance=args.skip_finance,
    )
    raise SystemExit(_print_result(result, args.output_json))


if __name__ == "__main__":
    main()
