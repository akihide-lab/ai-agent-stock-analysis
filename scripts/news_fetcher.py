"""Fetch public stock-related news and normalize it for storage."""

from __future__ import annotations

import logging
import os
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any

from dotenv import load_dotenv

try:
    from .mongodb_connection import ENV_FILES
except ImportError:
    from mongodb_connection import ENV_FILES


LOGGER = logging.getLogger(__name__)
DEFAULT_NEWS_FETCH_LIMIT = 5
DEFAULT_TIMEOUT_SECONDS = 10
GOOGLE_NEWS_RSS_URL = "https://news.google.com/rss/search"


@dataclass(frozen=True)
class NewsFetchResult:
    news_items: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _load_env() -> None:
    for env_file in ENV_FILES:
        load_dotenv(env_file)


def news_fetch_enabled(env: dict[str, str] | None = None) -> bool:
    _load_env()
    values = env if env is not None else os.environ
    return str(values.get("NEWS_FETCH_ENABLED", "false")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def news_fetch_limit(env: dict[str, str] | None = None) -> int:
    _load_env()
    values = env if env is not None else os.environ
    raw_value = values.get("NEWS_FETCH_LIMIT", str(DEFAULT_NEWS_FETCH_LIMIT))
    try:
        limit = int(raw_value)
    except ValueError:
        return DEFAULT_NEWS_FETCH_LIMIT
    return min(max(limit, 1), 10)


def _parse_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _strip_html(value: str | None) -> str:
    text = unescape(value or "")
    output: list[str] = []
    in_tag = False
    for char in text:
        if char == "<":
            in_tag = True
            continue
        if char == ">":
            in_tag = False
            continue
        if not in_tag:
            output.append(char)
    return " ".join("".join(output).split())


def build_google_news_rss_url(stock_code: str, company_name: str | None) -> str:
    terms = [term for term in [company_name, stock_code, "株", "決算"] if term]
    query = " ".join(str(term) for term in terms)
    return GOOGLE_NEWS_RSS_URL + "?" + urllib.parse.urlencode(
        {"q": query, "hl": "ja", "gl": "JP", "ceid": "JP:ja"}
    )


def fetch_news_for_stock(
    stock_code: str,
    company_name: str | None = None,
    limit: int | None = None,
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
) -> NewsFetchResult:
    _load_env()
    effective_limit = limit or news_fetch_limit()
    LOGGER.info("News fetch started")
    LOGGER.info("News fetch target stock_code: %s", stock_code)

    try:
        url = build_google_news_rss_url(stock_code, company_name)
        request = urllib.request.Request(
            url,
            headers={"User-Agent": "stock-analysis-local-agent/1.0"},
        )
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = response.read()
    except Exception as exc:
        LOGGER.warning("News fetch failed: %s", exc)
        return NewsFetchResult(warnings=[f"News fetch failed: {exc}"])

    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        LOGGER.warning("News fetch RSS parse failed: %s", exc)
        return NewsFetchResult(warnings=[f"News fetch RSS parse failed: {exc}"])

    fetched_at = datetime.now(timezone.utc)
    news_items: list[dict[str, Any]] = []
    for item in root.findall("./channel/item"):
        if len(news_items) >= effective_limit:
            break
        title = _strip_html(item.findtext("title"))
        link = (item.findtext("link") or "").strip()
        published_at = _parse_datetime(item.findtext("pubDate"))
        source_node = item.find("source")
        source = _strip_html(source_node.text if source_node is not None else None)
        body = _strip_html(item.findtext("description"))
        if not title or not link:
            continue
        news_items.append(
            {
                "stock_code": str(stock_code),
                "company_name": company_name,
                "title": title,
                "body": body or title,
                "url": link,
                "published_at": published_at,
                "fetched_at": fetched_at,
                "source": source or "Google News RSS",
                "category": "business",
            }
        )

    LOGGER.info("News fetch count: %s", len(news_items))
    return NewsFetchResult(news_items=news_items)
