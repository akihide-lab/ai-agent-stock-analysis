"""Execute selected workflows by delegating to existing stock-analysis code."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from analysis_connector import run_v1_analysis_flow
import question_agent as qa
from workflows import (
    FOLLOWUP_REQUIRED,
    SINGLE_STOCK_ANALYSIS,
    STOCK_SCREENING,
    SYSTEM_ERROR,
    UNSUPPORTED,
    WorkflowDefinition,
)


@dataclass
class DispatchResult:
    workflow_name: str
    succeeded: bool
    report_path: str | None = None
    candidates: pd.DataFrame | None = None
    reasons: list[str] = field(default_factory=list)
    message: str = ""
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def execute(
    workflow: WorkflowDefinition,
    *,
    decision: Any,
    db_path: Path,
    skip_web_update: bool,
    skip_finance: bool,
    dry_run: bool,
    limit: int,
) -> DispatchResult:
    """Run only the workflow selected by the orchestrator."""

    if workflow.name in {FOLLOWUP_REQUIRED, UNSUPPORTED, SYSTEM_ERROR}:
        return DispatchResult(
            workflow_name=workflow.name,
            succeeded=workflow.name != SYSTEM_ERROR,
            message=getattr(decision, "message", ""),
            error=getattr(decision, "error_code", None),
        )

    if workflow.name == SINGLE_STOCK_ANALYSIS:
        return _execute_single_stock_analysis(
            workflow,
            decision=decision,
            db_path=db_path,
            skip_web_update=skip_web_update,
            skip_finance=skip_finance,
            dry_run=dry_run,
            limit=limit,
        )

    if workflow.name == STOCK_SCREENING:
        return _execute_stock_screening(
            workflow,
            decision=decision,
            db_path=db_path,
            skip_web_update=skip_web_update,
            skip_finance=skip_finance,
            dry_run=dry_run,
            limit=limit,
        )

    raise ValueError(f"Unsupported workflow for dispatcher: {workflow.name}")


def _execute_single_stock_analysis(
    workflow: WorkflowDefinition,
    *,
    decision: Any,
    db_path: Path,
    skip_web_update: bool,
    skip_finance: bool,
    dry_run: bool,
    limit: int,
) -> DispatchResult:
    if not getattr(decision, "selected_stock_code", None):
        return DispatchResult(
            workflow_name=workflow.name,
            succeeded=False,
            message="分析対象の銘柄が未確定です。",
            error="missing_selected_stock_code",
        )

    if dry_run:
        return DispatchResult(workflow_name=workflow.name, succeeded=True)

    return _run_single_stock_flow(
        workflow,
        stock_code=str(decision.selected_stock_code),
        db_path=db_path,
        skip_web_update=skip_web_update,
        skip_finance=skip_finance,
        limit=limit,
    )


def _run_single_stock_flow(
    workflow: WorkflowDefinition,
    *,
    stock_code: str,
    db_path: Path,
    skip_web_update: bool,
    skip_finance: bool,
    limit: int,
) -> DispatchResult:
    result = run_v1_analysis_flow(
        question=stock_code,
        intent_id="Intent008",
        db_path=db_path,
        output_json=None,
        generate_report=True,
        allow_update=not skip_web_update,
        limit=limit,
        skip_finance=skip_finance,
    )
    return DispatchResult(
        workflow_name=workflow.name,
        succeeded=bool(result.succeeded),
        report_path=result.report_path,
        message=result.followup_question or "",
        error=None if result.succeeded else result.route,
        metadata={"route": result.route},
    )


def _execute_stock_screening(
    workflow: WorkflowDefinition,
    *,
    decision: Any,
    db_path: Path,
    skip_web_update: bool,
    skip_finance: bool,
    dry_run: bool,
    limit: int,
) -> DispatchResult:
    candidates, reasons = qa.select_candidate(
        decision.user_question,
        db_path,
        decision.primary_intent,
        decision.entities,
        limit,
    )
    if candidates.empty:
        return DispatchResult(
            workflow_name=workflow.name,
            succeeded=False,
            candidates=candidates,
            reasons=reasons,
            message="条件に合う候補銘柄が見つかりませんでした。",
            error="no_candidate",
        )

    selected = candidates.iloc[0]
    decision.route = "select_and_analyze"
    decision.selected_stock_code = str(selected["stock_code"])
    decision.selected_stock_name = str(selected["stock_name"])
    decision.selection_reasons = reasons
    decision.selected_flow = "select_and_analyze"

    report_path = None
    if not dry_run:
        dispatched = _run_single_stock_flow(
            workflow,
            stock_code=decision.selected_stock_code,
            db_path=db_path,
            skip_web_update=skip_web_update,
            skip_finance=skip_finance,
            limit=limit,
        )
        if not dispatched.succeeded:
            dispatched.candidates = candidates
            dispatched.reasons = reasons
            return dispatched
        report_path = dispatched.report_path
        decision.report_path = str(report_path) if report_path else None

    return DispatchResult(
        workflow_name=workflow.name,
        succeeded=True,
        report_path=str(report_path) if report_path else None,
        candidates=candidates,
        reasons=reasons,
    )
