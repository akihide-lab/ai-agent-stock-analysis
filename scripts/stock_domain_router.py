"""Detect whether a user request belongs to the stock-analysis domain."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

try:
    from .stock_name_resolver import ALIAS_DICT, BRAND_DICT
except ImportError:
    from stock_name_resolver import ALIAS_DICT, BRAND_DICT


STOCK_DOMAIN_KEYWORDS = (
    "株",
    "株式",
    "銘柄",
    "株価",
    "おすすめ株",
    "配当",
    "高配当",
    "優待",
    "per",
    "pbr",
    "roe",
    "買い時",
    "売り時",
    "値上がり",
    "成長株",
    "割安株",
    "大型株",
    "小型株",
)


@dataclass
class DomainClassification:
    domain: str
    confidence: float
    reasons: list[str] = field(default_factory=list)

    @property
    def is_stock(self) -> bool:
        return self.domain == "stock"


def normalize_text(value: object) -> str:
    return str(value or "").replace("　", " ").lower()


def _contains_known_stock_name(text: str) -> bool:
    known_terms = set(ALIAS_DICT) | set(BRAND_DICT)
    return any(term and normalize_text(term) in text for term in known_terms)


def classify(user_input: str) -> DomainClassification:
    """Classify only the broad domain; do not start search or analysis."""

    normalized = normalize_text(user_input)
    if not normalized.strip():
        return DomainClassification("unknown", 0.0, ["empty_input"])
    if len(normalized) >= 4 and len(set(normalized)) <= 2:
        return DomainClassification("unknown", 0.30, ["low_information_input"])

    reasons: list[str] = []
    if any(keyword in normalized for keyword in STOCK_DOMAIN_KEYWORDS):
        reasons.append("stock_keyword")
    if re.search(r"(?<!\d)(\d{4})(?!\d)", str(user_input or "")):
        reasons.append("stock_code_pattern")
    if _contains_known_stock_name(normalized):
        reasons.append("known_stock_alias_or_brand")

    if reasons:
        return DomainClassification("stock", 0.95, reasons)

    return DomainClassification("general", 0.70, ["no_stock_signal"])
