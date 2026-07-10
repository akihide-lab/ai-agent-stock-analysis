"""Intent IDs and V1 action names.

The design documents use IntentXXX IDs as the source of truth. Internal action
names are only implementation labels.
"""

from __future__ import annotations


INTENT_ACTION_MAP = {
    "Intent001": "recommend_stock_search",
    "Intent002": "growth_stock_search",
    "Intent003": "high_dividend_search",
    "Intent008": "single_stock_analysis",
    "Intent009": "stock_comparison",
    "Intent010": "trade_consultation",
}

DEFERRED_INTENTS = {
    "Intent004": "shareholder_benefit_search",
    "Intent005": "stable_stock_search",
    "Intent006": "growth_company_search",
    "Intent007": "industry_analysis",
    "Intent011": "portfolio_creation",
}

V1_SUPPORTED_INTENTS = set(INTENT_ACTION_MAP)


def normalize_intent_id(value: str) -> str:
    """Return the IntentXXX prefix from a full label or raw ID."""

    text = str(value or "").strip()
    for intent_id in sorted(V1_SUPPORTED_INTENTS | set(DEFERRED_INTENTS)):
        if text.startswith(intent_id):
            return intent_id
    return text


def action_name_for_intent(intent_id: str) -> str:
    normalized = normalize_intent_id(intent_id)
    if normalized not in INTENT_ACTION_MAP:
        raise ValueError(f"Unsupported V1 intent: {intent_id}")
    return INTENT_ACTION_MAP[normalized]


def is_supported_v1_intent(intent_id: str) -> bool:
    return normalize_intent_id(intent_id) in V1_SUPPORTED_INTENTS
