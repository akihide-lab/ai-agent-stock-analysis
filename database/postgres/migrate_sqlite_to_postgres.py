"""Safely copy the local SQLite market database into PostgreSQL.

The script is designed for a fresh PostgreSQL database that already has the
tables from create_tables.sql. It refuses to run against market_analysis unless
--allow-production is provided, and it refuses non-empty target tables unless
--allow-nonempty is provided.
"""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path
from typing import Iterable

import psycopg


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SQLITE_DB = PROJECT_ROOT / "data" / "market_analysis.db"
SAFE_DEFAULT_DB = "market_analysis_test"
ENV_FILES = (PROJECT_ROOT / ".env", PROJECT_ROOT / "config" / ".env")

TABLE_COLUMNS: dict[str, tuple[str, ...]] = {
    "stocks": (
        "stock_code",
        "stock_name",
        "market",
        "sector",
        "created_at",
    ),
    "stock_prices": (
        "id",
        "stock_code",
        "trade_date",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
    ),
    "finance": (
        "stock_code",
        "ticker",
        "stock_name",
        "fiscal_year",
        "sales",
        "operating_profit",
        "net_profit",
        "roe",
        "eps",
        "per",
        "pbr",
        "dividend",
        "dividend_yield",
        "market_cap",
        "total_assets",
        "total_liabilities",
        "total_debt",
        "net_debt",
        "cash",
        "current_assets",
        "current_liabilities",
        "working_capital",
        "equity",
        "equity_ratio",
        "debt_ratio",
        "debt_to_equity_ratio",
        "current_ratio",
        "updated_at",
        "fiscal_year_key",
    ),
    "calendar": ("date", "year", "year_month", "quarter", "fiscal_year"),
    "cpi": ("year_month", "cpi_index", "cpi_mom"),
    "exchange_rates": ("date", "usd_jpy"),
    "gdp": ("fiscal_year", "period", "gdp_amount", "gdp_growth"),
    "gold_price": ("trade_date", "gold_close", "updated_at"),
    "interest_rate_long": ("date", "jgb_10y_yield"),
    "nikkei_average": (
        "trade_date",
        "open_price",
        "high_price",
        "low_price",
        "close_price",
        "volume",
        "updated_at",
    ),
    "oil_prices": ("date", "wti_price"),
    "policy_rate": ("year_month", "policy_rate"),
    "us_market_indicators": (
        "trade_date",
        "sp500_close",
        "nasdaq100_close",
        "dow_close",
        "vix_close",
        "us_10y_yield",
        "updated_at",
    ),
}

PRIMARY_KEYS: dict[str, tuple[str, ...]] = {
    "stocks": ("stock_code",),
    "stock_prices": ("id",),
    "finance": ("stock_code", "fiscal_year"),
    "calendar": ("date",),
    "cpi": ("year_month",),
    "exchange_rates": ("date",),
    "gdp": ("fiscal_year",),
    "gold_price": ("trade_date",),
    "interest_rate_long": ("date",),
    "nikkei_average": ("trade_date",),
    "oil_prices": ("date",),
    "policy_rate": ("year_month",),
    "us_market_indicators": ("trade_date",),
}


def env_value(*names: str) -> str:
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value
    return ""


def load_local_env_files() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    for path in ENV_FILES:
        if path.is_file():
            load_dotenv(path, override=False)


def postgres_settings(db_name: str | None) -> dict[str, object]:
    actual_db = db_name or env_value("POSTGRES_DB", "PGDATABASE") or SAFE_DEFAULT_DB
    settings = {
        "host": env_value("POSTGRES_HOST", "PGHOST"),
        "port": int(env_value("POSTGRES_PORT", "PGPORT") or "5432"),
        "dbname": actual_db,
        "user": env_value("POSTGRES_USER", "PGUSER"),
        "password": env_value("POSTGRES_PASSWORD", "PGPASSWORD"),
        "sslmode": env_value("POSTGRES_SSLMODE", "PGSSLMODE") or "require",
    }
    missing = [key for key, value in settings.items() if key != "port" and not value]
    if missing:
        raise RuntimeError(
            "Missing PostgreSQL environment variables: " + ", ".join(sorted(missing))
        )
    return settings


def selected_tables(names: Iterable[str] | None) -> list[str]:
    if not names:
        return list(TABLE_COLUMNS)
    invalid = [name for name in names if name not in TABLE_COLUMNS]
    if invalid:
        raise ValueError("Unknown table(s): " + ", ".join(invalid))
    return list(names)


def ensure_target_empty(connection: psycopg.Connection, tables: list[str]) -> None:
    nonempty: list[str] = []
    with connection.cursor() as cursor:
        for table in tables:
            cursor.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            if count:
                nonempty.append(f"{table}={count}")
    if nonempty:
        raise RuntimeError(
            "Target tables are not empty. Refusing to migrate: " + ", ".join(nonempty)
        )


def fetch_sqlite_rows(connection: sqlite3.Connection, table: str) -> list[tuple]:
    columns = TABLE_COLUMNS[table]
    quoted = ", ".join(columns)
    return list(connection.execute(f"SELECT {quoted} FROM {table}"))


def insert_rows(
    connection: psycopg.Connection,
    table: str,
    rows: list[tuple],
    *,
    mode: str,
) -> int:
    if not rows:
        return 0
    columns = TABLE_COLUMNS[table]
    placeholders = ", ".join(["%s"] * len(columns))
    column_sql = ", ".join(columns)
    conflict = ", ".join(PRIMARY_KEYS[table])

    if mode == "insert":
        sql = f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders})"
    elif mode == "skip":
        sql = (
            f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict}) DO NOTHING"
        )
    elif mode == "upsert":
        updates = ", ".join(
            f"{column}=EXCLUDED.{column}"
            for column in columns
            if column not in PRIMARY_KEYS[table]
        )
        sql = (
            f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders}) "
            f"ON CONFLICT ({conflict}) DO UPDATE SET {updates}"
        )
    else:
        raise ValueError(f"Unsupported mode: {mode}")

    with connection.cursor() as cursor:
        cursor.executemany(sql, rows)
    return len(rows)


def migrate(args: argparse.Namespace) -> int:
    sqlite_path = args.sqlite_db.expanduser().resolve()
    if not sqlite_path.is_file():
        raise RuntimeError("SQLite database does not exist.")

    settings = postgres_settings(args.postgres_db)
    db_name = str(settings["dbname"])
    if db_name == "market_analysis" and not args.allow_production:
        raise RuntimeError(
            "Refusing to migrate into market_analysis without --allow-production."
        )

    tables = selected_tables(args.table)

    with closing(sqlite3.connect(sqlite_path)) as sqlite_connection:
        sqlite_connection.row_factory = None
        with psycopg.connect(**settings) as postgres_connection:
            try:
                with postgres_connection.cursor() as cursor:
                    cursor.execute("SELECT current_database()")
                    current_database = cursor.fetchone()[0]
                print(f"connected_database={current_database}")

                if not args.allow_nonempty:
                    ensure_target_empty(postgres_connection, tables)

                for table in tables:
                    rows = fetch_sqlite_rows(sqlite_connection, table)
                    copied = insert_rows(
                        postgres_connection,
                        table,
                        rows,
                        mode=args.mode,
                    )
                    print(f"{table}: copied={copied}")
                postgres_connection.commit()
            except Exception:
                postgres_connection.rollback()
                raise
    return 0


def parse_args() -> argparse.Namespace:
    load_local_env_files()
    parser = argparse.ArgumentParser(
        description="Copy SQLite market_analysis tables into PostgreSQL safely."
    )
    parser.add_argument("--sqlite-db", type=Path, default=DEFAULT_SQLITE_DB)
    parser.add_argument(
        "--postgres-db",
        default=SAFE_DEFAULT_DB,
        help="Target PostgreSQL database. Defaults to market_analysis_test.",
    )
    parser.add_argument(
        "--table",
        action="append",
        choices=sorted(TABLE_COLUMNS),
        help="Copy one table. Repeat to copy multiple tables. Defaults to all.",
    )
    parser.add_argument(
        "--mode",
        choices=("insert", "skip", "upsert"),
        default="insert",
        help="insert fails on duplicates; skip/upsert require --allow-nonempty.",
    )
    parser.add_argument(
        "--allow-nonempty",
        action="store_true",
        help="Allow target tables with existing rows.",
    )
    parser.add_argument(
        "--allow-production",
        action="store_true",
        help="Allow target database name market_analysis.",
    )
    args = parser.parse_args()
    if args.mode in {"skip", "upsert"} and not args.allow_nonempty:
        parser.error("--mode skip/upsert requires --allow-nonempty")
    return args


def main() -> int:
    try:
        return migrate(parse_args())
    except Exception as exc:
        print(f"migration failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
