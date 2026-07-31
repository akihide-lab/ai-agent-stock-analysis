"""Repository functions for the optional Snowflake analysis DWH."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Iterable, Mapping

try:
    from .snowflake_connection import (
        SnowflakeConfigurationError,
        SnowflakeConnectionError,
        get_snowflake_settings,
        snowflake_connection,
        snowflake_enabled,
    )
except ImportError:
    from snowflake_connection import (
        SnowflakeConfigurationError,
        SnowflakeConnectionError,
        get_snowflake_settings,
        snowflake_connection,
        snowflake_enabled,
    )


STOCK_ANALYSIS_COLUMNS = [
    "STOCK_CODE",
    "TRADE_DATE",
    "CLOSE_PRICE",
    "VOLUME",
    "PRICE_CHANGE",
    "CHANGE_RATE",
    "SALES",
    "OPERATING_PROFIT",
    "NET_PROFIT",
    "ROE",
    "PER",
    "PBR",
    "DIVIDEND_YIELD",
    "USD_JPY",
    "NIKKEI_CLOSE",
]


def _normalize_key(key: str) -> str:
    return key.lower()


def _row_get(row: Mapping[str, Any], key: str) -> Any:
    if key in row:
        return row[key]
    lower = key.lower()
    upper = key.upper()
    return row.get(lower, row.get(upper))


def _to_date(value: Any) -> Any:
    if value in ("", None):
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return str(value)[:10]


def _execute_merge(connection: Any, sql: str, params: tuple[Any, ...]) -> None:
    with connection.cursor() as cursor:
        cursor.execute(sql, params)


def _dict_rows(cursor: Any) -> list[dict[str, Any]]:
    columns = [description[0].lower() for description in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def check_connection() -> dict[str, Any]:
    if not snowflake_enabled():
        return {"enabled": False, "ok": False, "message": "Snowflake is disabled."}

    settings = get_snowflake_settings()
    with snowflake_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT CURRENT_DATABASE(), CURRENT_SCHEMA(), CURRENT_WAREHOUSE()"
            )
            row = cursor.fetchone()

    return {
        "enabled": True,
        "ok": bool(row),
        "database": row[0] if row else None,
        "schema": row[1] if row else None,
        "warehouse": row[2] if row else None,
        "expected_database": settings.database,
        "expected_schema": settings.schema,
        "expected_warehouse": settings.warehouse,
    }


def fetch_stock_analysis(stock_code: str, limit: int = 120) -> list[dict[str, Any]]:
    if not snowflake_enabled():
        return []
    if not isinstance(limit, int) or limit < 1:
        raise ValueError("limit must be a positive integer")

    columns = ", ".join(STOCK_ANALYSIS_COLUMNS)
    sql = f"""
        SELECT {columns}
        FROM MART.STOCK_ANALYSIS
        WHERE STOCK_CODE = %s
        ORDER BY TRADE_DATE DESC
        LIMIT %s
    """
    with snowflake_connection() as connection:
        with connection.cursor() as cursor:
            cursor.execute(sql, (str(stock_code), limit))
            rows = _dict_rows(cursor)
    return list(reversed(rows))


def fetch_stock_analysis_context(stock_code: str, limit: int = 120) -> dict[str, Any]:
    if not snowflake_enabled():
        return {
            "rows": [],
            "metadata": {"available": False, "stock_code": stock_code, "enabled": False},
            "warnings": [],
        }
    try:
        rows = fetch_stock_analysis(stock_code, limit)
        return {"rows": rows, "metadata": {"available": True, "stock_code": stock_code}, "warnings": []}
    except (SnowflakeConfigurationError, SnowflakeConnectionError) as exc:
        return {
            "rows": [],
            "metadata": {"available": False, "stock_code": stock_code, "error_category": getattr(exc, "category", "configuration_error")},
            "warnings": [f"Snowflake analysis skipped: {exc}"],
        }
    except Exception as exc:
        return {
            "rows": [],
            "metadata": {"available": False, "stock_code": stock_code, "error_category": type(exc).__name__},
            "warnings": ["Snowflake analysis failed. Existing analysis continued."],
        }


def insert_raw_stock_prices(rows: Iterable[Mapping[str, Any]]) -> int:
    count = 0
    sql = """
        MERGE INTO RAW.STOCK_PRICES target
        USING (
            SELECT %s AS STOCK_CODE, %s AS TRADE_DATE, %s AS OPEN_PRICE,
                   %s AS HIGH_PRICE, %s AS LOW_PRICE, %s AS CLOSE_PRICE,
                   %s AS VOLUME
        ) source
        ON target.STOCK_CODE = source.STOCK_CODE
       AND target.TRADE_DATE = TO_DATE(source.TRADE_DATE)
        WHEN MATCHED THEN UPDATE SET
            OPEN_PRICE = source.OPEN_PRICE,
            HIGH_PRICE = source.HIGH_PRICE,
            LOW_PRICE = source.LOW_PRICE,
            CLOSE_PRICE = source.CLOSE_PRICE,
            VOLUME = source.VOLUME,
            LOADED_AT = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED THEN INSERT
            (STOCK_CODE, TRADE_DATE, OPEN_PRICE, HIGH_PRICE, LOW_PRICE, CLOSE_PRICE, VOLUME)
        VALUES
            (source.STOCK_CODE, TO_DATE(source.TRADE_DATE), source.OPEN_PRICE,
             source.HIGH_PRICE, source.LOW_PRICE, source.CLOSE_PRICE, source.VOLUME)
    """
    with snowflake_connection() as connection:
        for row in rows:
            params = (
                str(_row_get(row, "stock_code")),
                _to_date(_row_get(row, "trade_date")),
                _row_get(row, "open_price"),
                _row_get(row, "high_price"),
                _row_get(row, "low_price"),
                _row_get(row, "close_price"),
                _row_get(row, "volume"),
            )
            _execute_merge(connection, sql, params)
            count += 1
        connection.commit()
    return count


def insert_raw_finance(rows: Iterable[Mapping[str, Any]]) -> int:
    count = 0
    sql = """
        MERGE INTO RAW.FINANCE target
        USING (
            SELECT %s AS STOCK_CODE, %s AS FISCAL_YEAR, %s AS SALES,
                   %s AS OPERATING_PROFIT, %s AS NET_PROFIT, %s AS ROE,
                   %s AS PER, %s AS PBR, %s AS DIVIDEND_YIELD
        ) source
        ON target.STOCK_CODE = source.STOCK_CODE
       AND target.FISCAL_YEAR = source.FISCAL_YEAR
        WHEN MATCHED THEN UPDATE SET
            SALES = source.SALES,
            OPERATING_PROFIT = source.OPERATING_PROFIT,
            NET_PROFIT = source.NET_PROFIT,
            ROE = source.ROE,
            PER = source.PER,
            PBR = source.PBR,
            DIVIDEND_YIELD = source.DIVIDEND_YIELD,
            LOADED_AT = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED THEN INSERT
            (STOCK_CODE, FISCAL_YEAR, SALES, OPERATING_PROFIT, NET_PROFIT, ROE, PER, PBR, DIVIDEND_YIELD)
        VALUES
            (source.STOCK_CODE, source.FISCAL_YEAR, source.SALES,
             source.OPERATING_PROFIT, source.NET_PROFIT, source.ROE,
             source.PER, source.PBR, source.DIVIDEND_YIELD)
    """
    with snowflake_connection() as connection:
        for row in rows:
            params = (
                str(_row_get(row, "stock_code")),
                _row_get(row, "fiscal_year_key") or _row_get(row, "fiscal_year"),
                _row_get(row, "sales"),
                _row_get(row, "operating_profit"),
                _row_get(row, "net_profit"),
                _row_get(row, "roe"),
                _row_get(row, "per"),
                _row_get(row, "pbr"),
                _row_get(row, "dividend_yield"),
            )
            _execute_merge(connection, sql, params)
            count += 1
        connection.commit()
    return count


def insert_raw_macro(rows: Iterable[Mapping[str, Any]]) -> int:
    count = 0
    sql = """
        MERGE INTO RAW.MACRO_ECONOMIC target
        USING (
            SELECT %s AS TRADE_DATE, %s AS USD_JPY, %s AS NIKKEI_CLOSE
        ) source
        ON target.TRADE_DATE = TO_DATE(source.TRADE_DATE)
        WHEN MATCHED THEN UPDATE SET
            USD_JPY = source.USD_JPY,
            NIKKEI_CLOSE = source.NIKKEI_CLOSE,
            LOADED_AT = CURRENT_TIMESTAMP()
        WHEN NOT MATCHED THEN INSERT
            (TRADE_DATE, USD_JPY, NIKKEI_CLOSE)
        VALUES
            (TO_DATE(source.TRADE_DATE), source.USD_JPY, source.NIKKEI_CLOSE)
    """
    with snowflake_connection() as connection:
        for row in rows:
            params = (
                _to_date(_row_get(row, "trade_date") or _row_get(row, "date")),
                _row_get(row, "usd_jpy"),
                _row_get(row, "nikkei_close") or _row_get(row, "nikkei_close_price"),
            )
            _execute_merge(connection, sql, params)
            count += 1
        connection.commit()
    return count
