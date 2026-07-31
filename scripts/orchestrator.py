"""Stateful orchestration for the stock question agent."""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import pandas as pd

import dispatcher
import followup_question_builder
import question_agent as qa
import stock_domain_router
from agent_jobs import finish_job, update_job
from analysis_connector import run_v1_analysis_flow
from db_connection import get_db_type
from query_flow_models import ClassificationResult
from workflows import (
    AgentState,
    FOLLOWUP_REQUIRED,
    SINGLE_STOCK_ANALYSIS,
    STOCK_SCREENING,
    SYSTEM_ERROR,
    UNSUPPORTED,
    get_workflow,
)


@dataclass
class OrchestrationResult:
    state: AgentState
    workflow_name: str
    decision: qa.QuestionDecision
    candidates: pd.DataFrame | None = None
    error_log: Path | None = None


def run(args: Any) -> OrchestrationResult:
    state = AgentState.RECEIVED
    candidates: pd.DataFrame | None = None

    try:
        if args.job_id:
            update_job(args.job_id, status="running", stage="checking_data_freshness")

        domain_result = stock_domain_router.classify(args.question)
        if not domain_result.is_stock:
            decision, workflow_name, state = _build_domain_stop(args.question, domain_result)
            _finalize_terminal(args.job_id, decision, state)
            return OrchestrationResult(state, workflow_name, decision)

        pre_db_result = qa.classify_pre_db(args.question, domain_result)
        if pre_db_result is not None:
            decision, workflow_name, state = _build_pre_db_stop(
                args.question,
                domain_result,
                pre_db_result,
            )
            _finalize_terminal(args.job_id, decision, state)
            return OrchestrationResult(state, workflow_name, decision)

        db_path = _db_path_for_orchestration(args.db)
        if args.job_id:
            update_job(args.job_id, stage="loading_stock_master")
        master = qa.load_stock_master(db_path)
        classification, stock_candidates, _ = qa.classify_with_db(
            args.question,
            db_path,
            master,
        )

        if classification.status in {
            "ambiguous",
            "insufficient",
            "unsupported",
            "system_error",
        }:
            decision, workflow_name, state, candidates = _build_db_stop(
                args.question,
                domain_result,
                classification,
                stock_candidates,
            )
            _finalize_terminal(args.job_id, decision, state)
            return OrchestrationResult(state, workflow_name, decision, candidates)

        state = AgentState.READY_FOR_DATA
        data_freshness = qa.load_data_freshness(db_path)
        decision = _build_ready_decision(args.question, domain_result, classification, data_freshness)

        if decision.missing_fields:
            decision.route = "followup_required"
            decision.message = "分析に必要な情報が不足しています。"
            decision.selected_flow = "followup"
            decision.early_return = True
            state = AgentState.NEEDS_FOLLOWUP
            workflow_name = FOLLOWUP_REQUIRED
            _write_log(decision, None)
            _finalize_terminal(args.job_id, decision, state)
            return OrchestrationResult(state, workflow_name, decision)

        workflow_name = _select_workflow(decision.primary_intent)
        workflow = get_workflow(workflow_name)
        state = AgentState.DATA_READY

        if workflow_name == SINGLE_STOCK_ANALYSIS:
            stocks = decision.entities.get("銘柄") or []
            selected_stock = stocks[0]
            decision.route = "analyze_stock"
            decision.selected_stock_code = str(selected_stock["stock_code"])
            decision.selected_stock_name = str(selected_stock["stock_name"])
            decision.selection_reasons = ["質問文で銘柄が指定されているため、その銘柄を分析"]
            decision.resolved_stock_candidates = list(stocks)
            decision.selected_flow = "analyze_stock"

        if args.job_id:
            update_job(
                args.job_id,
                stage="decision_ready",
                primary_intent=decision.primary_intent,
                route=decision.route,
                selected_stock_code=decision.selected_stock_code,
                selected_stock_name=decision.selected_stock_name,
            )
            if not args.dry_run and workflow_name in {SINGLE_STOCK_ANALYSIS, STOCK_SCREENING}:
                update_job(args.job_id, stage="generating_report")

        dispatched = _execute_ready_workflow(
            workflow,
            decision=decision,
            db_path=db_path,
            skip_web_update=args.skip_web_update,
            skip_finance=args.skip_finance,
            dry_run=args.dry_run,
            limit=args.limit,
        )
        candidates = dispatched.candidates
        if dispatched.report_path:
            decision.report_path = dispatched.report_path
        if dispatched.error == "no_candidate":
            decision.route = "no_candidate"
            decision.message = dispatched.message
            decision.selected_flow = "no_candidate"
            decision.early_return = True

        state = AgentState.ANALYZED if dispatched.succeeded else AgentState.FAILED
        _write_log(decision, candidates)

        if args.job_id:
            finish_job(
                args.job_id,
                status="succeeded" if dispatched.succeeded else "failed",
                stage="completed" if dispatched.succeeded else "failed",
                selected_stock_code=decision.selected_stock_code,
                selected_stock_name=decision.selected_stock_name,
                report_path=decision.report_path,
                question_flow_log=decision.log_path,
                error=dispatched.error,
            )

        if state == AgentState.ANALYZED:
            state = AgentState.COMPLETED
        return OrchestrationResult(state, workflow_name, decision, candidates)
    except Exception as exc:
        error_code = f"ERR-{uuid.uuid4().hex[:10]}"
        error_log = qa.write_system_error_log(args.question, exc, request_id=error_code)
        if args.job_id:
            finish_job(
                args.job_id,
                status="failed",
                stage="failed",
                error=f"system_error: {error_code}",
            )
        classification = ClassificationResult(status="system_error", error_code=error_code)
        message = followup_question_builder.build_safe_error_response(error_code)
        decision = qa.build_followup_decision(args.question, classification, message)
        decision.route = "system_error"
        decision.selected_flow = "system_error"
        decision.early_return = True
        decision.log_path = str(error_log)
        return OrchestrationResult(AgentState.FAILED, SYSTEM_ERROR, decision, error_log=error_log)


def _build_domain_stop(
    question: str,
    domain_result: stock_domain_router.DomainClassification,
) -> tuple[qa.QuestionDecision, str, AgentState]:
    classification = ClassificationResult(
        status="unsupported",
        intent=None,
        confidence=domain_result.confidence,
    )
    if domain_result.domain == "unknown":
        message = "依頼内容を特定できませんでした。何を確認したいか、もう少し具体的に教えてください。"
        selected_flow = "followup"
        route = "followup"
        state = AgentState.NEEDS_FOLLOWUP
        workflow_name = FOLLOWUP_REQUIRED
    else:
        message = "株式分析フローの対象外です。通常フローへ渡してください。"
        selected_flow = "general_request"
        route = "general_request"
        state = AgentState.UNSUPPORTED
        workflow_name = UNSUPPORTED
    decision = qa.build_followup_decision(question, classification, message)
    decision.detected_domain = domain_result.domain
    decision.detected_intent = classification.intent
    decision.intent_status = classification.status
    decision.missing_fields = list(classification.missing_fields)
    decision.selected_flow = selected_flow
    decision.route = route
    decision.early_return = True
    _write_log(decision, None)
    return decision, workflow_name, state


def _db_path_for_orchestration(db_path: Path) -> Path:
    if _effective_db_type(db_path) == "sqlite":
        return db_path.expanduser().resolve(strict=True)
    return db_path.expanduser()


def _effective_db_type(db_path: Path) -> str:
    return "sqlite" if db_path.exists() else get_db_type()


def _execute_ready_workflow(
    workflow: Any,
    *,
    decision: qa.QuestionDecision,
    db_path: Path,
    skip_web_update: bool,
    skip_finance: bool,
    dry_run: bool,
    limit: int,
) -> dispatcher.DispatchResult:
    if (
        _effective_db_type(db_path) == "postgres"
        and workflow.name == SINGLE_STOCK_ANALYSIS
        and not dry_run
    ):
        result = run_v1_analysis_flow(
            question=str(decision.selected_stock_code),
            intent_id="Intent008",
            db_path=db_path,
            generate_report=True,
            allow_update=not skip_web_update,
            limit=limit,
            skip_finance=skip_finance,
        )
        return dispatcher.DispatchResult(
            workflow_name=workflow.name,
            succeeded=bool(result.succeeded),
            report_path=result.report_path,
            message=result.followup_question or "",
            error=None if result.succeeded else result.route,
            metadata={"route": result.route},
        )

    return dispatcher.execute(
        workflow,
        decision=decision,
        db_path=db_path,
        skip_web_update=skip_web_update,
        skip_finance=skip_finance,
        dry_run=dry_run,
        limit=limit,
    )


def _build_pre_db_stop(
    question: str,
    domain_result: stock_domain_router.DomainClassification,
    result: ClassificationResult,
) -> tuple[qa.QuestionDecision, str, AgentState]:
    message = _message_for_classification(question, result, [])
    decision = qa.build_followup_decision(question, result, message)
    decision.detected_domain = domain_result.domain
    decision.detected_intent = result.intent
    decision.intent_status = result.status
    decision.missing_fields = list(result.missing_fields)
    decision.selected_flow = "followup"
    decision.early_return = True
    workflow_name = _workflow_for_status(result.status)
    state = _state_for_status(result.status)
    _write_log(decision, None)
    return decision, workflow_name, state


def _build_db_stop(
    question: str,
    domain_result: stock_domain_router.DomainClassification,
    classification: ClassificationResult,
    stock_candidates: list[Any],
) -> tuple[qa.QuestionDecision, str, AgentState, pd.DataFrame | None]:
    message = _message_for_classification(question, classification, stock_candidates)
    decision = qa.build_followup_decision(question, classification, message, data_freshness=[])
    decision.detected_domain = domain_result.domain
    decision.detected_intent = classification.intent
    decision.intent_status = classification.status
    decision.missing_fields = list(classification.missing_fields)
    decision.resolved_stock_candidates = [asdict(candidate) for candidate in stock_candidates]
    decision.selected_flow = "followup"
    decision.early_return = True
    workflow_name = _workflow_for_status(classification.status)
    state = _state_for_status(classification.status)
    candidates = pd.DataFrame([asdict(candidate) for candidate in stock_candidates]) if stock_candidates else None
    _write_log(decision, candidates, stock_candidates=stock_candidates)
    return decision, workflow_name, state, candidates


def _build_ready_decision(
    question: str,
    domain_result: stock_domain_router.DomainClassification,
    classification: ClassificationResult,
    data_freshness: list[dict[str, object]],
) -> qa.QuestionDecision:
    primary_intent = classification.intent or "Intent001 おすすめ銘柄検索"
    entities = dict(classification.entities)
    missing = {
        "required": qa.required_missing(primary_intent, entities),
        "optional": [],
        "defaulted": [],
    }
    if "投資期間" not in entities:
        missing["defaulted"].append("投資期間: 中長期")
    if "リスク" not in entities:
        missing["defaulted"].append("リスク: 普通")
    decision = qa.QuestionDecision(
        user_question=question,
        primary_intent=primary_intent,
        secondary_intents=list(classification.intent_candidates),
        entities=entities,
        missing_information=missing,
        classification_status=classification.status,
        confidence=classification.confidence,
        data_freshness=data_freshness,
    )
    decision.detected_domain = domain_result.domain
    decision.detected_intent = primary_intent
    decision.intent_status = classification.status
    decision.missing_fields = list(missing["required"])
    return decision


def _message_for_classification(
    question: str,
    classification: ClassificationResult,
    stock_candidates: list[Any],
) -> str:
    if classification.status == "ambiguous" and stock_candidates:
        return followup_question_builder.build_for_multiple_stock_candidates(
            stock_candidates,
            original_input=question,
        )
    if classification.status == "ambiguous":
        return followup_question_builder.build_for_ambiguous_intent(
            original_input=question,
            intent_candidates=classification.intent_candidates,
        )
    if classification.status == "insufficient" and classification.missing_fields == ["銘柄"]:
        return followup_question_builder.build_for_unknown_stock(question)
    if classification.status == "insufficient":
        return followup_question_builder.build_for_missing_information(
            original_input=question,
            intent=classification.intent,
            missing_fields=classification.missing_fields,
            known_entities=classification.entities,
        )
    if classification.status == "unsupported":
        return followup_question_builder.build_for_unsupported_request(question)
    if classification.status == "system_error":
        return followup_question_builder.build_safe_error_response(classification.error_code)
    return followup_question_builder.build_for_reclassification(question)


def _select_workflow(primary_intent: str) -> str:
    if primary_intent in {
        "Intent001 おすすめ銘柄検索",
        "Intent002 値上がり期待銘柄検索",
        "Intent003 高配当銘柄検索",
        "Intent004 株主優待銘柄検索",
        "Intent005 安定銘柄検索",
        "Intent006 成長株検索",
        "Intent007 業界分析",
    }:
        return STOCK_SCREENING
    return SINGLE_STOCK_ANALYSIS


def _workflow_for_status(status: str) -> str:
    if status == "unsupported":
        return UNSUPPORTED
    if status == "system_error":
        return SYSTEM_ERROR
    return FOLLOWUP_REQUIRED


def _state_for_status(status: str) -> AgentState:
    if status == "unsupported":
        return AgentState.UNSUPPORTED
    if status == "system_error":
        return AgentState.FAILED
    return AgentState.NEEDS_FOLLOWUP


def _write_log(
    decision: qa.QuestionDecision,
    candidates: pd.DataFrame | None,
    stock_candidates: list[Any] | None = None,
) -> None:
    log_path = qa.write_decision_log(decision, candidates)
    decision.log_path = str(log_path)
    if stock_candidates is not None:
        payload_candidates = [asdict(candidate) for candidate in stock_candidates]
    elif candidates is not None:
        payload_candidates = candidates.to_dict(orient="records")
    else:
        payload_candidates = []
    log_path.write_text(
        json.dumps(
            {**asdict(decision), "candidates": payload_candidates},
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )


def _finalize_terminal(
    job_id: str | None,
    decision: qa.QuestionDecision,
    state: AgentState,
) -> None:
    if not job_id:
        return
    stage = "followup_required"
    status = "succeeded"
    if state == AgentState.UNSUPPORTED:
        stage = "general_request"
    elif state == AgentState.FAILED:
        status = "failed"
        stage = "failed"
    finish_job(
        job_id,
        status=status,
        stage=stage,
        question_flow_log=decision.log_path,
    )
