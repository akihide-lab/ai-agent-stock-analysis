"""Generate conservative analysis text from retrieved news documents."""

from __future__ import annotations

from typing import Any

try:
    from .query_flow_models import NewsAnalysis, NewsDocument
except ImportError:
    from query_flow_models import NewsAnalysis, NewsDocument


POSITIVE_KEYWORDS = (
    "増益",
    "増収",
    "上方修正",
    "拡大",
    "提携",
    "受注",
    "成長",
    "投資",
    "新型",
    "回復",
)
NEGATIVE_KEYWORDS = (
    "減益",
    "減収",
    "下方修正",
    "不正",
    "停止",
    "リコール",
    "訴訟",
    "赤字",
    "減産",
    "不振",
)


def _document_text(news: NewsDocument | dict[str, Any]) -> str:
    if hasattr(news, "__dict__"):
        item = news.__dict__
    else:
        item = dict(news)
    return " ".join(str(item.get(key) or "") for key in ("title", "body"))


def _news_item(news: NewsDocument | dict[str, Any]) -> dict[str, Any]:
    return news.__dict__ if hasattr(news, "__dict__") else dict(news)


def _is_public_news(news: NewsDocument | dict[str, Any]) -> bool:
    item = _news_item(news)
    source = str(item.get("source") or "").lower()
    url = str(item.get("url") or "").lower()
    return source != "sample_news" and "example.com" not in url


def _matching_phrases(texts: list[str], keywords: tuple[str, ...]) -> list[str]:
    matches: list[str] = []
    joined = "\n".join(texts)
    for keyword in keywords:
        if keyword in joined and keyword not in matches:
            matches.append(keyword)
    return matches


def build_news_analysis(
    news_documents: list[NewsDocument] | None,
) -> NewsAnalysis | None:
    public_news = [news for news in news_documents or [] if _is_public_news(news)]
    if not public_news:
        return None

    texts = [_document_text(news) for news in public_news]
    positive_matches = _matching_phrases(texts, POSITIVE_KEYWORDS)
    negative_matches = _matching_phrases(texts, NEGATIVE_KEYWORDS)
    source_count = len(public_news)

    if positive_matches and not negative_matches:
        summary = "取得したニュースには、事業拡大や業績改善につながり得る表現が含まれています。"
    elif negative_matches and not positive_matches:
        summary = "取得したニュースには、業績や信頼性への注意が必要な表現が含まれています。"
    elif positive_matches and negative_matches:
        summary = "取得したニュースには、プラス材料と注意材料の両方が含まれています。"
    else:
        summary = "取得したニュースだけでは、明確なプラス材料またはマイナス材料は判定できません。"

    positives = [
        f"ニュース内で「{keyword}」に関する記述が確認されます。"
        for keyword in positive_matches[:5]
    ]
    negatives = [
        f"ニュース内で「{keyword}」に関する記述が確認されます。"
        for keyword in negative_matches[:5]
    ]

    return NewsAnalysis(
        summary=summary,
        positive_factors=positives,
        negative_factors=negatives,
        short_term_impact=(
            "短期的には、ニュース見出しへの市場反応で値動きが大きくなる可能性があります。"
            if positive_matches or negative_matches
            else "短期的な株価影響をニュースだけから判断する材料は限定的です。"
        ),
        medium_long_term_impact=(
            "中長期的な影響は、今後の業績数値や会社発表で確認する必要があります。"
        ),
        uncertainty=(
            "この考察は取得できたニュース本文と見出しに基づく整理であり、株価方向や投資判断を断定するものではありません。"
        ),
        source_count=source_count,
    )
