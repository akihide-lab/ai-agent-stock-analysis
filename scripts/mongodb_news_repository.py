"""Repository for storing and retrieving original news documents in MongoDB."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from dotenv import load_dotenv

try:
    from .mongodb_connection import ENV_FILES, get_mongodb_database, mongodb_enabled
    from .query_flow_models import NewsDocument
except ImportError:
    from mongodb_connection import ENV_FILES, get_mongodb_database, mongodb_enabled
    from query_flow_models import NewsDocument


LOGGER = logging.getLogger(__name__)
ASCENDING = 1
DESCENDING = -1
VECTOR_STATUSES = {"pending", "completed", "failed"}
DEFAULT_COLLECTION_NAME = "news"


@dataclass(frozen=True)
class NewsSaveSummary:
    attempted: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    raise ValueError(f"Unsupported datetime value: {type(value).__name__}")


def normalize_news_document(news: dict[str, Any]) -> dict[str, Any]:
    required = {"stock_code", "title", "body", "url", "published_at", "source"}
    missing = sorted(field for field in required if not news.get(field))
    if missing:
        raise ValueError(f"Required news fields are missing: {missing}")

    now = utc_now()
    published_at = _as_utc_datetime(news.get("published_at"))
    fetched_at = _as_utc_datetime(news.get("fetched_at")) or now
    vector_status = news.get("vector_status") or "pending"
    if vector_status not in VECTOR_STATUSES:
        raise ValueError(f"Unsupported vector_status: {vector_status}")

    return {
        "stock_code": str(news["stock_code"]),
        "company_name": news.get("company_name"),
        "title": str(news["title"]),
        "body": str(news["body"]),
        "url": str(news["url"]),
        "published_at": published_at,
        "fetched_at": fetched_at,
        "source": str(news["source"]),
        "category": news.get("category"),
        "vector_status": vector_status,
    }


class MongoDBNewsRepository:
    def __init__(self, collection: Any) -> None:
        self.collection = collection

    def ensure_indexes(self) -> None:
        self.collection.create_index(
            [("url", ASCENDING)],
            unique=True,
            name="unique_news_url",
        )
        self.collection.create_index(
            [("stock_code", ASCENDING), ("published_at", DESCENDING)],
            name="stock_code_published_at",
        )

    def save_many(self, news_items: list[dict[str, Any]]) -> NewsSaveSummary:
        LOGGER.info("MongoDB save target news count: %s", len(news_items))
        summary = NewsSaveSummary(attempted=len(news_items))
        inserted = 0
        updated = 0
        skipped = 0
        now = utc_now()

        for raw_news in news_items:
            try:
                news = normalize_news_document(raw_news)
            except ValueError:
                skipped += 1
                LOGGER.exception("MongoDB news normalization failed")
                continue

            result = self.collection.update_one(
                {"url": news["url"]},
                {
                    "$set": {**news, "updated_at": now},
                    "$setOnInsert": {"created_at": now},
                },
                upsert=True,
            )
            if getattr(result, "upserted_id", None) is not None:
                inserted += 1
            elif getattr(result, "matched_count", 0):
                updated += 1

        LOGGER.info("MongoDB inserted news count: %s", inserted)
        LOGGER.info("MongoDB updated news count: %s", updated)
        return NewsSaveSummary(
            attempted=len(news_items),
            inserted=inserted,
            updated=updated,
            skipped=skipped,
        )

    def find_by_stock_code(self, stock_code: str, limit: int = 10) -> list[NewsDocument]:
        if limit < 1:
            raise ValueError("limit must be greater than zero.")
        LOGGER.info("MongoDB news fetch stock_code: %s", stock_code)
        cursor = (
            self.collection.find({"stock_code": str(stock_code)})
            .sort("published_at", DESCENDING)
            .limit(limit)
        )
        documents = [to_news_document(item) for item in cursor]
        LOGGER.info("MongoDB fetched news count: %s", len(documents))
        return documents

    def find_by_id(self, document_id: str) -> NewsDocument | None:
        try:
            from bson import ObjectId
        except ImportError as exc:
            raise RuntimeError("bson is not installed.") from exc

        document = self.collection.find_one({"_id": ObjectId(document_id)})
        return to_news_document(document) if document else None


def to_news_document(document: dict[str, Any]) -> NewsDocument:
    return NewsDocument(
        stock_code=str(document.get("stock_code") or ""),
        company_name=document.get("company_name"),
        title=str(document.get("title") or ""),
        body=str(document.get("body") or ""),
        url=str(document.get("url") or ""),
        published_at=document.get("published_at"),
        fetched_at=document.get("fetched_at"),
        source=document.get("source"),
        category=document.get("category"),
        vector_status=str(document.get("vector_status") or "pending"),
        document_id=str(document.get("_id")) if document.get("_id") is not None else None,
    )


def is_public_news_document(document: NewsDocument) -> bool:
    source = str(document.source or "").lower()
    url = str(document.url or "").lower()
    return source != "sample_news" and "example.com" not in url


def get_news_repository_from_env() -> tuple[Any, MongoDBNewsRepository]:
    client, database = get_mongodb_database()
    collection_name = os.getenv("MONGODB_NEWS_COLLECTION", DEFAULT_COLLECTION_NAME)
    repository = MongoDBNewsRepository(database[collection_name])
    repository.ensure_indexes()
    return client, repository


def fetch_mongodb_news_for_stock(
    stock_code: str | None,
    limit: int = 10,
    public_only: bool = True,
) -> tuple[list[NewsDocument], list[str]]:
    for env_file in ENV_FILES:
        load_dotenv(env_file)
    if not mongodb_enabled():
        return [], []
    if not stock_code:
        return [], ["MongoDB news retrieval skipped because no stock_code was selected."]

    client = None
    try:
        client, repository = get_news_repository_from_env()
        raw_limit = min(max(limit * 2, limit), 50) if public_only else limit
        documents = repository.find_by_stock_code(stock_code, raw_limit)
        if public_only:
            documents = [item for item in documents if is_public_news_document(item)]
        return documents[:limit], []
    except Exception as exc:
        LOGGER.exception("MongoDB processing failed")
        return [], [f"MongoDB processing failed: {exc}"]
    finally:
        if client is not None:
            client.close()
