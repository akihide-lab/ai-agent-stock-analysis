"""Thin V1/V1.5 connector from user question to existing analysis flows."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    from .context_aggregator import aggregate_context
    from .data_source_rules import build_data_source_plan
    from .followup_question_builder import FollowupQuestionBuilder
    from .intent_actions import normalize_intent_id
    from .query_flow_models import (
        AnalysisRunResult,
        MissingInformation,
        QueryFlowInput,
        to_plain_data,
    )
    from .rag_retriever import DEFAULT_CHROMA_DIR, search_rag_context
    from .rdb_retriever import DEFAULT_DB_PATH, retrieve_rdb_context
    from .stock_name_resolver import StockCandidate, StockNameResolver
except ImportError:
    from context_aggregator import aggregate_context
    from data_source_rules import build_data_source_plan
    from followup_question_builder import FollowupQuestionBuilder
    from intent_actions import normalize_intent_id
    from query_flow_models import (
        AnalysisRunResult,
        MissingInformation,
        QueryFlowInput,
        to_plain_data,
    )
    from rag_retriever import DEFAULT_CHROMA_DIR, search_rag_context
    from rdb_retriever import DEFAULT_DB_PATH, retrieve_rdb_context
    from stock_name_resolver import StockCandidate, StockNameResolver


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUTPUT_JSON = PROJECT_ROOT / "logs" / "analysis_context_latest.json"
UPDATE_MARKET_SCRIPT = SCRIPT_DIR / "update_market_data.py"
UPDATE_OFFICIAL_MACRO_SCRIPT = SCRIPT_DIR / "update_official_macro_web.py"

REPORT_INTENTS = {"Intent001", "Intent002", "Intent003", "Intent008", "Intent010"}
CANDIDATE_INTENTS = {"Intent001", "Intent002", "Intent003"}
STOCK_REQUIRED_INTENTS = {"Intent008", "Intent009", "Intent010"}


def _infer_intent(question: str, resolved_stock_count: int = 0) -> str:
    """Small V1 fallback classifier for standalone connector testing."""

    text = question or ""
    lower = text.lower()
    if "比較" in text or "どっち" in text or " vs " in lower:
        return "Intent009"
    if "買" in text or "売" in text or "保有" in text:
        return "Intent010"
    if "配当" in text or "高配当" in text:
        return "Intent003"
    if "値上" in text or "上がり" in text or "成長" in text or "伸び" in text:
        return "Intent002"
    if "おすすめ" in text or "オススメ" in text or "良さそう" in text:
        return "Intent001"
    if "分析" in text or "調べ" in text or "どう" in text or resolved_stock_count > 0:
        return "Intent008"
    return "Intent001"


def build_initial_query(question: str, intent_id: str | None) -> QueryFlowInput:
    primary_intent = normalize_intent_id(intent_id) if intent_id else "Intent001"
    return QueryFlowInput(
        user_question=question,
        primary_intent=primary_intent,
        missing_information=MissingInformation(),
    )


def _complete_rows(context: Any) -> int | None:
    for result in context.retrieved_context.rdb_results:
        if result.target != "analysis_readiness" or not result.rows:
            continue
        return int(result.rows[0].get("complete_rows") or 0)
    return None


def _first_candidate_stock(context: Any) -> dict[str, Any] | None:
    for result in context.retrieved_context.rdb_results:
        if result.target != "candidate_stocks" or not result.rows:
            continue
        row = result.rows[0]
        if row.get("stock_code"):
            return {
                "stock_code": str(row.get("stock_code")),
                "stock_name": row.get("stock_name"),
                "market": row.get("market"),
                "sector": row.get("sector"),
            }
    return None


def _candidate_to_entity(candidate: StockCandidate) -> dict[str, Any]:
    return {
        "stock_code": candidate.stock_code,
        "stock_name": candidate.stock_name,
        "market": candidate.market,
        "sector": candidate.sector,
        "match_type": candidate.match_type,
    }


def _write_result(output_json: Path | None, result: AnalysisRunResult) -> None:
    if not output_json:
        return
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(
        json.dumps(to_plain_data(result), ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )


def _build_followup_result(
    query: QueryFlowInput,
    plan: Any,
    candidates: list[StockCandidate],
    message: str,
    output_json: Path | None,
) -> AnalysisRunResult:
    context = aggregate_context(
        query=query,
        plan=plan,
        rdb_results=[],
        rag_results=[],
        warnings=["Follow-up is required before analysis."],
    )
    result = AnalysisRunResult(
        analysis_context=context,
        report_path=None,
        route="followup_required",
        succeeded=False,
        warnings=["Follow-up is required before analysis."],
        followup_question=message,
        stock_candidates=[_candidate_to_entity(candidate) for candidate in candidates],
    )
    _write_result(output_json, result)
    return result


def _run_existing_update_scripts(stock_code: str, db_path: Path) -> tuple[bool, list[str]]:
    messages: list[str] = []
    commands = [
        [
            sys.executable,
            str(UPDATE_MARKET_SCRIPT),
            "--db",
            str(db_path),
            "--stock-code",
            stock_code,
        ],
        [
            sys.executable,
            str(UPDATE_OFFICIAL_MACRO_SCRIPT),
            "--db",
            str(db_path),
        ],
    ]

    for command in commands:
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
        name = Path(command[1]).name
        if process.returncode != 0:
            messages.append(
                f"{name} failed with code {process.returncode}: "
                f"{(process.stderr or process.stdout)[-3000:]}"
            )
            return False, messages
        messages.append(f"{name} succeeded.")
    return True, messages


def run_v1_analysis_flow(
    question: str,
    intent_id: str | None = None,
    db_path: Path = DEFAULT_DB_PATH,
    chroma_dir: Path = DEFAULT_CHROMA_DIR,
    output_json: Path | None = DEFAULT_OUTPUT_JSON,
    generate_report: bool = True,
    allow_update: bool = True,
    limit: int = 10,
) -> AnalysisRunResult:
    query = build_initial_query(question, intent_id)

    resolver = StockNameResolver(db_path)
    resolved_candidates = resolver.resolve(question)
    if intent_id is None:
        query.primary_intent = _infer_intent(question, len(resolved_candidates))

    plan = build_data_source_plan(query.primary_intent)

    if plan.intent_id in STOCK_REQUIRED_INTENTS:
        builder = FollowupQuestionBuilder()
        if len(resolved_candidates) == 0:
            message = builder.build([], original_input=question)
            return _build_followup_result(query, plan, [], message, output_json)
        if len(resolved_candidates) > 1:
            message = builder.build(resolved_candidates, original_input=question)
            return _build_followup_result(query, plan, resolved_candidates, message, output_json)

        selected = resolved_candidates[0]
        query.entities["stocks"] = [_candidate_to_entity(selected)]
        query.entities["stock_code"] = selected.stock_code

    rdb_results, resolved_stocks, rdb_warnings = retrieve_rdb_context(
        query,
        plan,
        db_path=db_path,
        limit=limit,
    )

    if resolved_stocks and "stock_code" not in query.entities:
        query.entities["stocks"] = resolved_stocks
        query.entities["stock_code"] = str(resolved_stocks[0].get("stock_code"))

    rag_results, rag_warnings = search_rag_context(
        query,
        plan,
        chroma_dir=chroma_dir,
        n_results=min(limit, 10),
    )
    warnings = [*rdb_warnings, *rag_warnings]
    context = aggregate_context(query, plan, rdb_results, rag_results, warnings)

    if plan.intent_id in CANDIDATE_INTENTS and not context.selected_stock_code:
        candidate = _first_candidate_stock(context)
        if candidate:
            query.entities["stocks"] = [candidate]
            query.entities["stock_code"] = str(candidate["stock_code"])
            rdb_results, resolved_stocks, rdb_warnings = retrieve_rdb_context(
                query,
                plan,
                db_path=db_path,
                limit=limit,
            )
            rag_results, rag_warnings = search_rag_context(
                query,
                plan,
                chroma_dir=chroma_dir,
                n_results=min(limit, 10),
            )
            warnings = [
                *warnings,
                "Candidate stock was selected from v_agent_stock_candidates.",
                *rdb_warnings,
                *rag_warnings,
            ]
            context = aggregate_context(query, plan, rdb_results, rag_results, warnings)

    complete_rows = _complete_rows(context)
    if (
        allow_update
        and plan.intent_id in REPORT_INTENTS
        and context.selected_stock_code
        and (complete_rows is None or complete_rows < 20)
    ):
        ok, update_messages = _run_existing_update_scripts(
            context.selected_stock_code,
            db_path.expanduser().resolve(strict=True),
        )
        warnings.extend(update_messages)
        if not ok:
            result = AnalysisRunResult(
                analysis_context=context,
                report_path=None,
                route=plan.next_flow,
                succeeded=False,
                warnings=warnings,
            )
            _write_result(output_json, result)
            return result

        rdb_results, resolved_stocks, rdb_warnings = retrieve_rdb_context(
            query,
            plan,
            db_path=db_path,
            limit=limit,
        )
        rag_results, rag_warnings = search_rag_context(
            query,
            plan,
            chroma_dir=chroma_dir,
            n_results=min(limit, 10),
        )
        warnings = [
            *warnings,
            "Data freshness was rechecked after update.",
            *rdb_warnings,
            *rag_warnings,
        ]
        context = aggregate_context(query, plan, rdb_results, rag_results, warnings)

    route = plan.next_flow
    report_path = None
    succeeded = False

    if generate_report and plan.intent_id in REPORT_INTENTS:
        if not context.selected_stock_code:
            warnings.append("Existing report generation skipped because no stock was selected.")
        else:
            if str(SCRIPT_DIR) not in sys.path:
                sys.path.insert(0, str(SCRIPT_DIR))
            from generate_stock_report import generate_report as existing_generate_report

            try:
                report = existing_generate_report(
                    context.selected_stock_code,
                    db_path.expanduser().resolve(strict=True),
                    None,
                    None,
                )
                report_path = str(report)
                succeeded = True
            except Exception as exc:
                warnings.append(f"Existing report generation failed: {exc}")
                succeeded = False
    elif plan.intent_id == "Intent009":
        succeeded = len(context.comparison_stock_codes) >= 2
    else:
        succeeded = bool(context.retrieved_context.rdb_results)

    result = AnalysisRunResult(
        analysis_context=context,
        report_path=report_path,
        route=route,
        succeeded=succeeded,
        warnings=warnings,
    )
    _write_result(output_json, result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the V1/V1.5 query-to-analysis connector.")
    parser.add_argument("question", help="User question, for example: トヨタを分析して")
    parser.add_argument("--intent-id", help="Optional explicit IntentXXX ID")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--chroma-dir", type=Path, default=DEFAULT_CHROMA_DIR)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--context-only", action="store_true")
    parser.add_argument("--no-update", action="store_true")
    parser.add_argument("--limit", type=int, default=10)
    return parser.parse_args()


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args()
    result = run_v1_analysis_flow(
        question=args.question,
        intent_id=args.intent_id,
        db_path=args.db,
        chroma_dir=args.chroma_dir,
        output_json=args.output_json,
        generate_report=not args.context_only,
        allow_update=not args.no_update,
        limit=args.limit,
    )
    print(json.dumps(to_plain_data(result), ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    main()
