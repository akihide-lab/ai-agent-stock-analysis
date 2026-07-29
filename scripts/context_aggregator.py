"""Aggregate RDB and RAG retrieval results into analysis context."""

from __future__ import annotations

try:
    from .query_flow_models import (
        AnalysisContext,
        DataSourcePlan,
        NewsAnalysis,
        NewsDocument,
        QueryFlowInput,
        RagDocument,
        RdbResult,
        RetrievedContext,
    )
except ImportError:
    from query_flow_models import (
        AnalysisContext,
        DataSourcePlan,
        NewsAnalysis,
        NewsDocument,
        QueryFlowInput,
        RagDocument,
        RdbResult,
        RetrievedContext,
    )


def _first_stock_from_results(rdb_results: list[RdbResult]) -> tuple[str | None, str | None]:
    for result in rdb_results:
        if result.target != "stock_profile" or not result.rows:
            continue
        row = result.rows[0]
        return str(row.get("stock_code")), str(row.get("stock_name"))
    return None, None


def _comparison_codes(rdb_results: list[RdbResult]) -> list[str]:
    codes: list[str] = []
    for result in rdb_results:
        if result.target != "stock_profile" or not result.rows:
            continue
        code = str(result.rows[0].get("stock_code"))
        if code not in codes:
            codes.append(code)
    return codes


def build_supplemental_text_context(rag_results: list[RagDocument]) -> str:
    if not rag_results:
        return ""

    parts = []
    for index, item in enumerate(rag_results, start=1):
        source = item.metadata.get("source") or item.metadata.get("file_name") or item.document_id
        parts.append(
            "\n".join(
                [
                    f"## RAG Result {index}",
                    f"- source: {source or 'unknown'}",
                    f"- distance: {item.distance}",
                    "",
                    item.document,
                ]
            )
        )
    return "\n\n".join(parts)


def aggregate_context(
    query: QueryFlowInput,
    plan: DataSourcePlan,
    rdb_results: list[RdbResult],
    rag_results: list[RagDocument],
    news_documents: list[NewsDocument] | None = None,
    news_analysis: NewsAnalysis | None = None,
    warnings: list[str] | None = None,
) -> AnalysisContext:
    if warnings is None and news_analysis is not None and isinstance(news_analysis, list):
        warnings = news_analysis
        news_analysis = None
    if warnings is None and news_documents and all(
        isinstance(item, str) for item in news_documents
    ):
        warnings = list(news_documents)
        news_documents = []

    selected_code, selected_name = _first_stock_from_results(rdb_results)
    retrieved = RetrievedContext(
        rdb_results=rdb_results,
        rag_results=rag_results,
        news_documents=list(news_documents or []),
        warnings=list(warnings or []),
    )
    return AnalysisContext(
        query=query,
        data_source_plan=plan,
        retrieved_context=retrieved,
        selected_stock_code=selected_code,
        selected_stock_name=selected_name,
        comparison_stock_codes=_comparison_codes(rdb_results),
        news_analysis=news_analysis,
        supplemental_text_context=build_supplemental_text_context(rag_results),
        warnings=list(warnings or []),
    )
