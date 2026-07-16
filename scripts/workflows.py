"""Workflow definitions for the stock question orchestration layer."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class AgentState(str, Enum):
    RECEIVED = "RECEIVED"
    NEEDS_FOLLOWUP = "NEEDS_FOLLOWUP"
    READY_FOR_DATA = "READY_FOR_DATA"
    DATA_READY = "DATA_READY"
    ANALYZED = "ANALYZED"
    COMPLETED = "COMPLETED"
    UNSUPPORTED = "UNSUPPORTED"
    FAILED = "FAILED"


TERMINAL_STATES = {
    AgentState.NEEDS_FOLLOWUP,
    AgentState.UNSUPPORTED,
    AgentState.FAILED,
    AgentState.COMPLETED,
}


@dataclass(frozen=True)
class WorkflowDefinition:
    name: str
    required_inputs: tuple[str, ...]
    steps: tuple[str, ...]
    update_allowed: bool
    stop_conditions: tuple[str, ...] = field(default_factory=tuple)


SINGLE_STOCK_ANALYSIS = "single_stock_analysis"
STOCK_SCREENING = "stock_screening"
FOLLOWUP_REQUIRED = "followup_required"
UNSUPPORTED = "unsupported"
SYSTEM_ERROR = "system_error"


WORKFLOWS: dict[str, WorkflowDefinition] = {
    SINGLE_STOCK_ANALYSIS: WorkflowDefinition(
        name=SINGLE_STOCK_ANALYSIS,
        required_inputs=(
            "selected_stock_code",
            "db_path",
            "skip_web_update",
            "skip_finance",
            "limit",
        ),
        steps=("validate_selected_stock", "delegate_to_analysis_connector"),
        update_allowed=True,
        stop_conditions=("missing_selected_stock_code",),
    ),
    STOCK_SCREENING: WorkflowDefinition(
        name=STOCK_SCREENING,
        required_inputs=(
            "user_question",
            "primary_intent",
            "entities",
            "db_path",
            "limit",
            "skip_web_update",
            "skip_finance",
        ),
        steps=("select_candidate", "delegate_selected_stock_to_analysis_connector"),
        update_allowed=True,
        stop_conditions=("missing_required_information", "no_candidate"),
    ),
    FOLLOWUP_REQUIRED: WorkflowDefinition(
        name=FOLLOWUP_REQUIRED,
        required_inputs=("message",),
        steps=("return_followup_message",),
        update_allowed=False,
        stop_conditions=("always_terminal",),
    ),
    UNSUPPORTED: WorkflowDefinition(
        name=UNSUPPORTED,
        required_inputs=("message",),
        steps=("return_unsupported_message",),
        update_allowed=False,
        stop_conditions=("always_terminal",),
    ),
    SYSTEM_ERROR: WorkflowDefinition(
        name=SYSTEM_ERROR,
        required_inputs=("error_code",),
        steps=("return_safe_error_response",),
        update_allowed=False,
        stop_conditions=("always_terminal",),
    ),
}


def get_workflow(name: str) -> WorkflowDefinition:
    try:
        return WORKFLOWS[name]
    except KeyError as exc:
        raise ValueError(f"Unknown workflow: {name}") from exc
