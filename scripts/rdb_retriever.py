"""Read-only RDB retrieval for the V1 analysis context flow."""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Any

try:
    from .query_flow_models import DataSourcePlan, QueryFlowInput, RdbResult
except ImportError:
    from query_flow_models import DataSourcePlan, QueryFlowInput, RdbResult


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "market_analysis.db"


def connect_read_only(db_path: Path = DEFAULT_DB_PATH) -> sqlite3.Connection:
    resolved = db_path.expanduser().resolve(strict=True)
    connection = sqlite3.connect(resolved.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    return connection


def table_or_view_exists(connection: sqlite3.Connection, name: str) -> bool:
    row = connection.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE name = ?
          AND type IN ('table', 'view')
        LIMIT 1
        """,
        (name,),
    ).fetchone()
    return row is not None


def _rows(connection: sqlite3.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(sql, params).fetchall()]


def _code_candidates(text: str) -> list[str]:
    return re.findall(r"(?<!\d)(\d{4})(?!\d)", text or "")


COMMON_STOCK_ALIASES = {
    "トヨタ": "7203",
    "toyota": "7203",
    "ソニー": "6758",
    "sony": "6758",
    "任天堂": "7974",
    "nintendo": "7974",
    "ntt": "9432",
    "ソフトバンク": "9434",
    "ana": "9202",
}


def _name_terms(text: str) -> list[str]:
    terms = re.split(r"[\s、。,.・/／]+|を|は|って|分析|して|比較|買|売", text or "")
    return [term.strip().lower() for term in terms if len(term.strip()) >= 2]


def load_stock_master(connection: sqlite3.Connection) -> list[dict[str, Any]]:
    if not table_or_view_exists(connection, "v_agent_stock_master"):
        return []
    return _rows(
        connection,
        """
        SELECT stock_code, stock_name, sector
        FROM v_agent_stock_master
        ORDER BY stock_code
        """,
    )


def resolve_stocks(
    question: str,
    entities: dict[str, Any] | None,
    connection: sqlite3.Connection,
) -> list[dict[str, Any]]:
    """Resolve stock codes from explicit entities, 4-digit codes, or names."""

    entities = entities or {}
    explicit = entities.get("stock_code") or entities.get("stock_codes")
    explicit_codes: list[str] = []
    if isinstance(explicit, str):
        explicit_codes = [explicit]
    elif isinstance(explicit, list):
        explicit_codes = [str(item) for item in explicit]

    normalized_question = str(question or "").lower()
    alias_codes = [
        code
        for alias, code in COMMON_STOCK_ALIASES.items()
        if alias.lower() in normalized_question
    ]
    codes = explicit_codes + _code_candidates(question) + alias_codes
    master = load_stock_master(connection)

    if codes:
        code_set = set(codes)
        return [row for row in master if str(row.get("stock_code")) in code_set]

    terms = _name_terms(question)
    matches = []
    for row in master:
        name = str(row.get("stock_name") or "")
        code = str(row.get("stock_code") or "")
        if not name:
            continue
        compact = (
            name.replace("株式会社", "")
            .replace("(株)", "")
            .replace("（株）", "")
            .strip()
        )
        if name.lower() in normalized_question or compact.lower() in normalized_question:
            matches.append(row)
        elif any(term in name.lower() or term in compact.lower() for term in terms):
            matches.append(row)
        elif code and code in normalized_question:
            matches.append(row)
    return matches


def fetch_data_freshness(connection: sqlite3.Connection) -> RdbResult:
    if not table_or_view_exists(connection, "v_agent_data_freshness"):
        return RdbResult(target="data_freshness", metadata={"available": False})
    rows = _rows(
        connection,
        """
        SELECT *
        FROM v_agent_data_freshness
        ORDER BY data_name
        LIMIT 50
        """,
    )
    return RdbResult(target="data_freshness", rows=rows, metadata={"available": True})


def fetch_stock_profile(connection: sqlite3.Connection, stock_code: str) -> RdbResult:
    rows = []
    if table_or_view_exists(connection, "v_agent_stock_master"):
        rows = _rows(
            connection,
            """
            SELECT stock_code, stock_name, sector
            FROM v_agent_stock_master
            WHERE stock_code = ?
            LIMIT 1
            """,
            (stock_code,),
        )
    return RdbResult(target="stock_profile", rows=rows, metadata={"stock_code": stock_code})


def fetch_latest_candidate_row(connection: sqlite3.Connection, stock_code: str) -> RdbResult:
    if not table_or_view_exists(connection, "v_agent_stock_candidates"):
        return RdbResult(
            target="latest_candidate_row",
            metadata={"stock_code": stock_code, "available": False},
        )
    rows = _rows(
        connection,
        """
        SELECT *
        FROM v_agent_stock_candidates
        WHERE stock_code = ?
        ORDER BY latest_trade_date DESC
        LIMIT 1
        """,
        (stock_code,),
    )
    return RdbResult(
        target="latest_candidate_row",
        rows=rows,
        metadata={"stock_code": stock_code, "available": True},
    )


def fetch_report_input_summary(connection: sqlite3.Connection, stock_code: str) -> RdbResult:
    if not table_or_view_exists(connection, "v_ai_stock_report_input"):
        return RdbResult(
            target="report_input_summary",
            metadata={"stock_code": stock_code, "available": False},
        )
    rows = _rows(
        connection,
        """
        SELECT
            stock_code,
            stock_name,
            MIN(trade_date) AS first_trade_date,
            MAX(trade_date) AS latest_trade_date,
            COUNT(*) AS row_count
        FROM v_ai_stock_report_input
        WHERE stock_code = ?
        GROUP BY stock_code, stock_name
        """,
        (stock_code,),
    )
    return RdbResult(
        target="report_input_summary",
        rows=rows,
        metadata={"stock_code": stock_code, "available": True},
    )


def fetch_analysis_readiness(connection: sqlite3.Connection, stock_code: str) -> RdbResult:
    if not table_or_view_exists(connection, "v_ai_stock_report_input"):
        return RdbResult(
            target="analysis_readiness",
            metadata={"stock_code": stock_code, "available": False},
        )
    rows = _rows(
        connection,
        """
        SELECT
            stock_code,
            stock_name,
            COUNT(*) AS total_rows,
            SUM(
                CASE
                    WHEN close_price IS NOT NULL
                     AND wti_price IS NOT NULL
                     AND usd_jpy IS NOT NULL
                     AND policy_rate IS NOT NULL
                     AND jgb_10y_yield IS NOT NULL
                     AND cpi_index IS NOT NULL
                     AND gdp_growth IS NOT NULL
                    THEN 1
                    ELSE 0
                END
            ) AS complete_rows,
            MIN(trade_date) AS first_trade_date,
            MAX(trade_date) AS latest_trade_date,
            MAX(fiscal_year) AS latest_fiscal_year
        FROM v_ai_stock_report_input
        WHERE stock_code = ?
        GROUP BY stock_code, stock_name
        """,
        (stock_code,),
    )
    return RdbResult(
        target="analysis_readiness",
        rows=rows,
        metadata={
            "stock_code": stock_code,
            "available": True,
            "minimum_complete_rows": 20,
        },
    )


def fetch_candidate_stocks(
    connection: sqlite3.Connection,
    intent_id: str,
    limit: int = 10,
) -> RdbResult:
    if not table_or_view_exists(connection, "v_agent_stock_candidates"):
        return RdbResult(target="candidate_stocks", metadata={"available": False})

    order_by = "volume DESC"
    if intent_id == "Intent003":
        order_by = "dividend_yield DESC"
    elif intent_id == "Intent002":
        order_by = "volume DESC"

    rows = _rows(
        connection,
        f"""
        SELECT *
        FROM v_agent_stock_candidates
        ORDER BY {order_by}
        LIMIT ?
        """,
        (limit,),
    )
    return RdbResult(
        target="candidate_stocks",
        rows=rows,
        metadata={"available": True, "order_by": order_by},
    )


def retrieve_rdb_context(
    query: QueryFlowInput,
    plan: DataSourcePlan,
    db_path: Path = DEFAULT_DB_PATH,
    limit: int = 10,
) -> tuple[list[RdbResult], list[dict[str, Any]], list[str]]:
    """Retrieve V1 RDB context without mutating the database."""

    warnings: list[str] = []
    results: list[RdbResult] = []
    resolved_stocks: list[dict[str, Any]] = []

    with connect_read_only(db_path) as connection:
        resolved_stocks = resolve_stocks(query.user_question, query.entities, connection)
        results.append(fetch_data_freshness(connection))

        if plan.intent_id in {"Intent001", "Intent002", "Intent003"}:
            results.append(fetch_candidate_stocks(connection, plan.intent_id, limit=limit))
            if resolved_stocks:
                stock_code = str(resolved_stocks[0].get("stock_code"))
                results.append(fetch_stock_profile(connection, stock_code))
                results.append(fetch_latest_candidate_row(connection, stock_code))
                results.append(fetch_report_input_summary(connection, stock_code))
                results.append(fetch_analysis_readiness(connection, stock_code))

        if plan.intent_id in {"Intent008", "Intent009", "Intent010"}:
            if not resolved_stocks:
                warnings.append("No stock could be resolved from the question or entities.")
            for stock in resolved_stocks[: max(1, limit)]:
                stock_code = str(stock.get("stock_code"))
                results.append(fetch_stock_profile(connection, stock_code))
                results.append(fetch_latest_candidate_row(connection, stock_code))
                results.append(fetch_report_input_summary(connection, stock_code))
                results.append(fetch_analysis_readiness(connection, stock_code))

    return results, resolved_stocks, warnings
