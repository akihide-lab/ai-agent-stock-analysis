"""Optional ChromaDB retrieval for supplemental text context."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

try:
    from .query_flow_models import DataSourcePlan, QueryFlowInput, RagDocument
except ImportError:
    from query_flow_models import DataSourcePlan, QueryFlowInput, RagDocument


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CHROMA_DIR = PROJECT_ROOT / "chroma_db"
DEFAULT_COLLECTION_NAMES = ("news_chunks", "documents")


def _stop_chroma_client(client: Any) -> None:
    system = getattr(client, "_system", None)
    stop = getattr(system, "stop", None)
    if callable(stop):
        stop()
    clear = getattr(client, "clear_system_cache", None)
    if callable(clear):
        clear()


def build_rag_query(query: QueryFlowInput, plan: DataSourcePlan) -> str:
    parts = [query.user_question, plan.intent_id, plan.action_name]
    stocks = query.entities.get("stocks") or query.entities.get("stock_code")
    if stocks:
        parts.append(str(stocks))
    if plan.rag_targets:
        parts.append(" ".join(plan.rag_targets))
    return " ".join(part for part in parts if part)


def search_rag_context(
    query: QueryFlowInput,
    plan: DataSourcePlan,
    chroma_dir: Path = DEFAULT_CHROMA_DIR,
    collection_names: tuple[str, ...] = DEFAULT_COLLECTION_NAMES,
    n_results: int = 5,
) -> tuple[list[RagDocument], list[str]]:
    """Search ChromaDB if available; otherwise return an empty result safely."""

    warnings: list[str] = []
    if not plan.rag_targets:
        return [], warnings

    if not chroma_dir.exists():
        warnings.append(f"ChromaDB directory not found: {chroma_dir}")
        return [], warnings

    try:
        import chromadb  # type: ignore
    except ImportError:
        warnings.append("chromadb is not installed; using SQLite text fallback.")
        return search_chroma_sqlite_fallback(query, chroma_dir, n_results), warnings

    client = chromadb.PersistentClient(path=str(chroma_dir))
    try:
        query_text = build_rag_query(query, plan)

        for collection_name in collection_names:
            try:
                collection = client.get_collection(name=collection_name)
                raw_results: dict[str, Any] = collection.query(
                    query_texts=[query_text],
                    n_results=n_results,
                )
                documents = raw_results.get("documents", [[]])[0]
                metadatas = raw_results.get("metadatas", [[]])[0]
                distances = raw_results.get("distances", [[]])[0]
                ids = raw_results.get("ids", [[]])[0]

                results = []
                for index, document in enumerate(documents):
                    results.append(
                        RagDocument(
                            document=document,
                            metadata=metadatas[index] if index < len(metadatas) else {},
                            distance=distances[index] if index < len(distances) else None,
                            document_id=ids[index] if index < len(ids) else None,
                        )
                    )
                return results, warnings
            except Exception as exc:
                warnings.append(f"RAG collection skipped ({collection_name}): {exc}")
    finally:
        _stop_chroma_client(client)

    return [], warnings


def _search_terms(query_text: str) -> list[str]:
    terms = re.split(r"[\s、。,.・/／]+|を|は|って|分析|して|比較|買|売", query_text)
    return [term for term in terms if len(term) >= 2 and not term.startswith("Intent")]


def search_chroma_sqlite_fallback(
    query: QueryFlowInput,
    chroma_dir: Path,
    n_results: int = 5,
) -> list[RagDocument]:
    """Best-effort text search against Chroma's SQLite metadata.

    This is not vector similarity search. It is a no-network fallback so the
    pipeline can still inspect local Chroma documents when the chromadb package
    is unavailable.
    """

    sqlite_path = chroma_dir / "chroma.sqlite3"
    if not sqlite_path.exists():
        return []

    query_text = query.user_question
    terms = _search_terms(query_text)
    connection = sqlite3.connect(sqlite_path.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        rows = [
            dict(row)
            for row in connection.execute(
                """
                SELECT
                    id,
                    key,
                    string_value
                FROM embedding_metadata
                WHERE key = 'chroma:document'
                ORDER BY id
                """
            ).fetchall()
        ]
        scored = []
        for row in rows:
            document = str(row.get("string_value") or "")
            score = sum(1 for term in terms if term.lower() in document.lower())
            if score > 0:
                scored.append((score, row))
        scored.sort(key=lambda item: (-item[0], item[1]["id"]))
        selected = [row for _, row in scored[:n_results]]
        return [
            RagDocument(
                document=str(row.get("string_value") or ""),
                metadata={"source_type": "chroma_sqlite_fallback"},
                distance=None,
                document_id=str(row.get("id")),
            )
            for row in selected
        ]
    finally:
        connection.close()
