"""Sync one stock code from PostgreSQL source tables to Snowflake RAW tables."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from .db_connection import connect_postgres
    from .snowflake_repository import (
        insert_raw_finance,
        insert_raw_macro,
        insert_raw_stock_prices,
    )
except ImportError:
    from db_connection import connect_postgres
    from snowflake_repository import (
        insert_raw_finance,
        insert_raw_macro,
        insert_raw_stock_prices,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _fetch_rows(connection: Any, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        columns = [description[0] for description in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]


def fetch_postgres_source_rows(stock_code: str, limit: int) -> dict[str, list[dict[str, Any]]]:
    connection = connect_postgres(read_only=True)
    try:
        stock_prices = _fetch_rows(
            connection,
            """
            SELECT *
            FROM (
                SELECT stock_code, trade_date, open_price, high_price, low_price, close_price, volume
                FROM stock_prices
                WHERE stock_code = %s
                ORDER BY trade_date DESC
                LIMIT %s
            ) recent_stock_prices
            ORDER BY trade_date
            """,
            (stock_code, limit),
        )
        finance = _fetch_rows(
            connection,
            """
            SELECT stock_code, fiscal_year_key, fiscal_year, sales, operating_profit,
                   net_profit, roe, per, pbr, dividend_yield
            FROM finance
            WHERE stock_code = %s
            ORDER BY fiscal_year_key NULLS LAST, fiscal_year
            """,
            (stock_code,),
        )
        macro = _fetch_rows(
            connection,
            """
            SELECT *
            FROM (
                SELECT DISTINCT trade_date, usd_jpy, nikkei_close_price
                FROM v_ai_stock_report_input
                WHERE stock_code = %s
                ORDER BY trade_date DESC
                LIMIT %s
            ) recent_macro
            ORDER BY trade_date
            """,
            (stock_code, limit),
        )
    finally:
        connection.close()
    return {"stock_prices": stock_prices, "finance": finance, "macro": macro}


def sync_stock_code(stock_code: str, limit: int = 200) -> dict[str, Any]:
    rows = fetch_postgres_source_rows(stock_code, limit)
    result: dict[str, Any] = {
        "stock_code": stock_code,
        "limit": limit,
        "sync_mode": "limited_recent_rows",
        "postgres_counts": {name: len(items) for name, items in rows.items()},
        "snowflake_counts": {"stock_prices": 0, "finance": 0, "macro": 0},
        "duplicate_prevention": "MERGE by natural key",
        "ok": False,
        "errors": [],
    }
    try:
        result["snowflake_counts"]["stock_prices"] = insert_raw_stock_prices(rows["stock_prices"])
        result["snowflake_counts"]["finance"] = insert_raw_finance(rows["finance"])
        result["snowflake_counts"]["macro"] = insert_raw_macro(rows["macro"])
        result["ok"] = True
    except Exception as exc:
        result["errors"].append(
            {
                "type": type(exc).__name__,
                "message": "Snowflake RAW sync failed. Partial counts are included.",
            }
        )
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Sync PostgreSQL rows for one stock code to Snowflake RAW.")
    parser.add_argument("--stock-code", required=True, help="4 digit stock code, for example 9202")
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Maximum recent stock-price and macro rows to sync. Finance rows are synced by fiscal year.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = sync_stock_code(str(args.stock_code), limit=args.limit)
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
