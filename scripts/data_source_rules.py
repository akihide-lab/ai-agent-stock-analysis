"""V1 data source rules for supported stock-analysis intents."""

from __future__ import annotations

try:
    from .intent_actions import action_name_for_intent, normalize_intent_id
    from .query_flow_models import DataSourcePlan
except ImportError:
    from intent_actions import action_name_for_intent, normalize_intent_id
    from query_flow_models import DataSourcePlan


DATA_SOURCE_RULES_V1 = {
    "Intent001": {
        "rdb_targets": ["candidate_stocks"],
        "rag_targets": [],
        "next_flow": "candidate_selection_then_existing_analysis",
        "notes": ["RDB candidates are enough for the first V1 pass."],
    },
    "Intent002": {
        "rdb_targets": ["candidate_stocks", "finance", "prediction"],
        "rag_targets": ["related_news"],
        "next_flow": "candidate_selection_then_existing_analysis",
        "notes": ["Prediction is represented by existing DB/view data when available."],
    },
    "Intent003": {
        "rdb_targets": ["dividend_yield", "finance"],
        "rag_targets": ["dividend_news"],
        "next_flow": "candidate_selection_then_existing_analysis",
        "notes": ["High dividend screening is RDB-first."],
    },
    "Intent008": {
        "rdb_targets": ["stock_price", "finance", "macro"],
        "rag_targets": ["ir", "news"],
        "next_flow": "single_stock_report",
        "notes": ["RAG context is supplemental and must not enter statistical data frames."],
    },
    "Intent009": {
        "rdb_targets": ["comparison_targets"],
        "rag_targets": ["comparison_news"],
        "next_flow": "comparison_context",
        "notes": ["V1 builds comparison context; full comparison report can follow later."],
    },
    "Intent010": {
        "rdb_targets": ["stock_price", "finance", "prediction"],
        "rag_targets": ["news", "ir"],
        "next_flow": "single_stock_report_with_context",
        "notes": ["No automated buy/sell judgment is performed in V1."],
    },
}


def build_data_source_plan(intent_id: str) -> DataSourcePlan:
    normalized = normalize_intent_id(intent_id)
    if normalized not in DATA_SOURCE_RULES_V1:
        raise ValueError(f"No V1 data source rule for intent: {intent_id}")

    rule = DATA_SOURCE_RULES_V1[normalized]
    return DataSourcePlan(
        intent_id=normalized,
        action_name=action_name_for_intent(normalized),
        rdb_targets=list(rule["rdb_targets"]),
        rag_targets=list(rule["rag_targets"]),
        next_flow=str(rule["next_flow"]),
        api_required=False,
        web_required=False,
        notes=list(rule.get("notes", [])),
    )
