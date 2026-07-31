"""Shared data models for the V1 query-to-analysis flow."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from pathlib import Path
from typing import Any, Literal


ClassificationStatus = Literal[
    "classified",
    "ambiguous",
    "insufficient",
    "unsupported",
    "system_error",
]


@dataclass
class ClassificationResult:
    status: ClassificationStatus
    intent: str | None = None
    intent_candidates: list[str] = field(default_factory=list)
    entities: dict[str, Any] = field(default_factory=dict)
    missing_fields: list[str] = field(default_factory=list)
    confidence: float | None = None
    error_code: str | None = None
    error_message: str | None = None


@dataclass
class MissingInformation:
    required: list[str] = field(default_factory=list)
    optional: list[str] = field(default_factory=list)
    defaulted: list[str] = field(default_factory=list)


@dataclass
class QueryFlowInput:
    user_question: str
    primary_intent: str
    secondary_intents: list[str] = field(default_factory=list)
    entities: dict[str, Any] = field(default_factory=dict)
    missing_information: MissingInformation = field(default_factory=MissingInformation)


@dataclass
class DataSourcePlan:
    intent_id: str
    action_name: str
    rdb_targets: list[str]
    rag_targets: list[str]
    next_flow: str
    api_required: bool = False
    web_required: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass
class RdbResult:
    target: str
    rows: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RagDocument:
    document: str
    metadata: dict[str, Any] = field(default_factory=dict)
    distance: float | None = None
    document_id: str | None = None


@dataclass
class NewsDocument:
    stock_code: str
    company_name: str | None = None
    title: str = ""
    body: str = ""
    url: str = ""
    published_at: Any = None
    fetched_at: Any = None
    source: str | None = None
    category: str | None = None
    vector_status: str = "pending"
    document_id: str | None = None


@dataclass
class NewsAnalysis:
    summary: str = ""
    positive_factors: list[str] = field(default_factory=list)
    negative_factors: list[str] = field(default_factory=list)
    short_term_impact: str = ""
    medium_long_term_impact: str = ""
    uncertainty: str = ""
    source_count: int = 0


@dataclass
class SnowflakeAnalysis:
    rows: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)


@dataclass
class RetrievedContext:
    rdb_results: list[RdbResult] = field(default_factory=list)
    rag_results: list[RagDocument] = field(default_factory=list)
    news_documents: list[NewsDocument] = field(default_factory=list)
    snowflake_analysis: SnowflakeAnalysis | None = None
    warnings: list[str] = field(default_factory=list)


@dataclass
class AnalysisContext:
    query: QueryFlowInput
    data_source_plan: DataSourcePlan
    retrieved_context: RetrievedContext
    selected_stock_code: str | None = None
    selected_stock_name: str | None = None
    comparison_stock_codes: list[str] = field(default_factory=list)
    news_analysis: NewsAnalysis | None = None
    supplemental_text_context: str = ""
    warnings: list[str] = field(default_factory=list)


@dataclass
class AnalysisRunResult:
    analysis_context: AnalysisContext
    report_path: str | None = None
    route: str = "context_only"
    succeeded: bool = False
    warnings: list[str] = field(default_factory=list)
    followup_question: str | None = None
    stock_candidates: list[dict[str, Any]] = field(default_factory=list)


def to_plain_data(value: Any) -> Any:
    """Convert dataclasses and common path-like values to JSON-safe data."""

    if is_dataclass(value):
        return to_plain_data(asdict(value))
    if isinstance(value, dict):
        return {str(key): to_plain_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [to_plain_data(item) for item in value]
    if isinstance(value, tuple):
        return [to_plain_data(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    return value
