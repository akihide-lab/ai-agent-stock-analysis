"""Update existing market tables from Yahoo Finance using a staging database.

This script is based on the existing acquisition scripts but adds:
- command-line database selection;
- per-source failure isolation;
- staging-copy validation;
- backup before replacement;
- updates to existing tables only (no DDL).
"""

from __future__ import annotations

import argparse
from contextlib import closing
import json
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yfinance as yf


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "market_analysis.db"
DEFAULT_START = "2020-01-01"
MARKET_TICKERS = {
    "nikkei_average": "^N225",
    "sp500_close": "^GSPC",
    "nasdaq100_close": "^NDX",
    "dow_close": "^DJI",
    "vix_close": "^VIX",
    "us_10y_yield": "^TNX",
    "gold_close": "GC=F",
    "usd_jpy": "USDJPY=X",
    "wti_price": "CL=F",
}
MIN_FETCHED_STOCK_ROWS = 20
MIN_FETCH_RATIO_FOR_EXISTING_HISTORY = 0.5


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="既存SQLiteテーブルをYahoo Financeの最新データで更新します。"
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument(
        "--skip-finance",
        action="store_true",
        help="財務データ取得を省略します。",
    )
    parser.add_argument(
        "--stock-code",
        action="append",
        dest="stock_codes",
        help="更新対象銘柄コード。複数回指定可。省略時は全銘柄。",
    )
    return parser.parse_args()


def normalize_download(frame: pd.DataFrame) -> pd.DataFrame:
    if frame.empty:
        return frame
    normalized = frame.reset_index()
    if isinstance(normalized.columns, pd.MultiIndex):
        normalized.columns = [column[0] for column in normalized.columns]
    date_column = "Date" if "Date" in normalized.columns else "Datetime"
    normalized[date_column] = pd.to_datetime(normalized[date_column]).dt.strftime(
        "%Y-%m-%d"
    )
    return normalized.rename(columns={date_column: "date"})


def download_ohlcv(ticker: str, start: str) -> pd.DataFrame:
    frame = yf.download(
        ticker,
        start=start,
        progress=False,
        auto_adjust=False,
        threads=False,
    )
    normalized = normalize_download(frame)
    required = ["date", "Open", "High", "Low", "Close", "Volume"]
    if normalized.empty or any(column not in normalized for column in required):
        raise RuntimeError(f"{ticker}: OHLCVを取得できませんでした")
    return normalized[required].dropna(subset=["Close"])


def download_close(ticker: str, start: str) -> pd.DataFrame:
    frame = download_ohlcv(ticker, start)
    return frame[["date", "Close"]].rename(columns={"Close": ticker})


def get_financial_value(
    statement: pd.DataFrame | None,
    item_name: str,
    fiscal_date: Any,
) -> float | None:
    try:
        if statement is None or statement.empty or item_name not in statement.index:
            return None
        value = statement.loc[item_name, fiscal_date]
        return None if pd.isna(value) else float(value)
    except (KeyError, TypeError, ValueError):
        return None


def fetch_financial_rows(
    stock_code: str,
    ticker: str,
    stock_name: str,
) -> list[tuple[Any, ...]]:
    instrument = yf.Ticker(ticker)
    try:
        info = instrument.info or {}
    except Exception:
        info = {}
    try:
        financials = instrument.financials
    except Exception:
        financials = pd.DataFrame()
    try:
        balance_sheet = instrument.balance_sheet
    except Exception:
        balance_sheet = pd.DataFrame()
    if financials is None or financials.empty:
        raise RuntimeError(f"{ticker}: 財務諸表を取得できませんでした")

    dividend_yield = info.get("dividendYield")
    if dividend_yield is not None and dividend_yield > 1:
        dividend_yield /= 100
    updated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    rows: list[tuple[Any, ...]] = []

    for fiscal_date in financials.columns:
        sales = get_financial_value(financials, "Total Revenue", fiscal_date)
        if sales is None:
            continue
        operating_profit = get_financial_value(
            financials, "Operating Income", fiscal_date
        )
        net_profit = get_financial_value(financials, "Net Income", fiscal_date)
        equity = get_financial_value(
            balance_sheet, "Stockholders Equity", fiscal_date
        )
        total_assets = get_financial_value(balance_sheet, "Total Assets", fiscal_date)
        total_liabilities = get_financial_value(
            balance_sheet,
            "Total Liabilities Net Minority Interest",
            fiscal_date,
        )
        total_debt = get_financial_value(balance_sheet, "Total Debt", fiscal_date)
        net_debt = get_financial_value(balance_sheet, "Net Debt", fiscal_date)
        cash = get_financial_value(
            balance_sheet, "Cash And Cash Equivalents", fiscal_date
        )
        current_assets = get_financial_value(
            balance_sheet, "Current Assets", fiscal_date
        )
        current_liabilities = get_financial_value(
            balance_sheet, "Current Liabilities", fiscal_date
        )
        working_capital = get_financial_value(
            balance_sheet, "Working Capital", fiscal_date
        )
        roe = (
            net_profit / equity
            if net_profit is not None and equity not in (None, 0)
            else None
        )
        equity_ratio = (
            equity / total_assets
            if equity is not None and total_assets not in (None, 0)
            else None
        )
        debt_ratio = (
            total_liabilities / total_assets
            if total_liabilities is not None and total_assets not in (None, 0)
            else None
        )
        debt_to_equity = (
            total_debt / equity
            if total_debt is not None and equity not in (None, 0)
            else None
        )
        current_ratio = (
            current_assets / current_liabilities
            if current_assets is not None and current_liabilities not in (None, 0)
            else None
        )
        rows.append(
            (
                stock_code,
                ticker,
                stock_name,
                str(pd.Timestamp(fiscal_date).date()),
                sales,
                operating_profit,
                net_profit,
                roe,
                info.get("trailingEps"),
                info.get("trailingPE"),
                info.get("priceToBook"),
                info.get("dividendRate"),
                dividend_yield,
                info.get("marketCap"),
                total_assets,
                total_liabilities,
                total_debt,
                net_debt,
                cash,
                current_assets,
                current_liabilities,
                working_capital,
                equity,
                equity_ratio,
                debt_ratio,
                debt_to_equity,
                current_ratio,
                updated_at,
                str(pd.Timestamp(fiscal_date).year - 1),
            )
        )
    if not rows:
        raise RuntimeError(f"{ticker}: 保存可能な財務年度がありませんでした")
    return rows


def fetch_all_sources(
    stocks: list[tuple[str, str]],
    start: str,
    include_finance: bool,
) -> tuple[dict[str, Any], dict[str, str]]:
    fetched: dict[str, Any] = {
        "stock_prices": {},
        "finance": {},
        "market": {},
    }
    failures: dict[str, str] = {}

    for stock_code, stock_name in stocks:
        ticker = f"{stock_code}.T"
        try:
            fetched["stock_prices"][stock_code] = download_ohlcv(ticker, start)
            print(f"株価取得完了: {ticker}")
        except Exception as error:
            failures[f"stock_prices:{stock_code}"] = str(error)
            print(f"株価取得失敗: {ticker}: {error}")
        if include_finance:
            try:
                fetched["finance"][stock_code] = fetch_financial_rows(
                    stock_code, ticker, stock_name
                )
                print(f"財務取得完了: {ticker}")
            except Exception as error:
                failures[f"finance:{stock_code}"] = str(error)
                print(f"財務取得失敗: {ticker}: {error}")

    for name, ticker in MARKET_TICKERS.items():
        try:
            fetched["market"][name] = download_ohlcv(ticker, start)
            print(f"市場データ取得完了: {ticker}")
        except Exception as error:
            failures[f"market:{name}"] = str(error)
            print(f"市場データ取得失敗: {ticker}: {error}")

    if not fetched["stock_prices"]:
        raise RuntimeError("株価を1銘柄も取得できなかったため更新を中止します")
    return fetched, failures


def stock_price_summary(
    connection: sqlite3.Connection,
    stock_code: str,
) -> dict[str, Any]:
    count, min_date, max_date = connection.execute(
        """
        SELECT COUNT(*), MIN(trade_date), MAX(trade_date)
        FROM stock_prices
        WHERE stock_code = ?
        """,
        (stock_code,),
    ).fetchone()
    return {
        "count": int(count or 0),
        "min_date": min_date,
        "max_date": max_date,
    }


def fetched_stock_price_summary(frame: pd.DataFrame) -> dict[str, Any]:
    valid = frame.dropna(subset=["Close"])
    return {
        "count": int(len(valid)),
        "min_date": None if valid.empty else str(valid["date"].min()),
        "max_date": None if valid.empty else str(valid["date"].max()),
    }


def validate_stock_price_fetch(
    stock_code: str,
    before: dict[str, Any],
    fetched: dict[str, Any],
) -> None:
    fetched_count = int(fetched["count"])
    before_count = int(before["count"])
    if fetched_count < MIN_FETCHED_STOCK_ROWS:
        raise RuntimeError(
            f"stock_prices:{stock_code} fetched too few rows: {fetched_count}"
        )
    if before_count >= MIN_FETCHED_STOCK_ROWS and fetched_count < before_count * MIN_FETCH_RATIO_FOR_EXISTING_HISTORY:
        raise RuntimeError(
            f"stock_prices:{stock_code} fetched row count looks partial: "
            f"before={before_count}, fetched={fetched_count}"
        )


def upsert_stock_prices(
    connection: sqlite3.Connection,
    frames: dict[str, pd.DataFrame],
) -> dict[str, dict[str, Any]]:
    insert_sql = """
        INSERT INTO stock_prices (
            stock_code, trade_date, open_price, high_price,
            low_price, close_price, volume
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
    """
    update_sql = """
        UPDATE stock_prices
        SET open_price = ?,
            high_price = ?,
            low_price = ?,
            close_price = ?,
            volume = ?
        WHERE stock_code = ?
          AND trade_date = ?
    """
    summaries: dict[str, dict[str, Any]] = {}
    for stock_code, frame in frames.items():
        before = stock_price_summary(connection, stock_code)
        fetched = fetched_stock_price_summary(frame)
        validate_stock_price_fetch(stock_code, before, fetched)
        rows = [
            (
                stock_code,
                row["date"],
                float(row["Open"]),
                float(row["High"]),
                float(row["Low"]),
                float(row["Close"]),
                int(row["Volume"]),
            )
            for _, row in frame.iterrows()
            if pd.notna(row["Close"])
        ]
        for row in rows:
            _, trade_date, open_price, high_price, low_price, close_price, volume = row
            cursor = connection.execute(
                update_sql,
                (
                    open_price,
                    high_price,
                    low_price,
                    close_price,
                    volume,
                    stock_code,
                    trade_date,
                ),
            )
            if cursor.rowcount == 0:
                connection.execute(insert_sql, row)
        after = stock_price_summary(connection, stock_code)
        if int(after["count"]) < int(before["count"]):
            raise RuntimeError(
                f"stock_prices:{stock_code} row count decreased after update: "
                f"before={before['count']}, after={after['count']}"
            )
        summaries[stock_code] = {
            "before_count": before["count"],
            "before_min_date": before["min_date"],
            "before_max_date": before["max_date"],
            "fetched_count": fetched["count"],
            "fetched_min_date": fetched["min_date"],
            "fetched_max_date": fetched["max_date"],
            "after_count": after["count"],
            "after_min_date": after["min_date"],
            "after_max_date": after["max_date"],
        }
    return summaries


def replace_finance(
    connection: sqlite3.Connection,
    finance_rows: dict[str, list[tuple[Any, ...]]],
) -> None:
    sql = """
        INSERT INTO finance (
            stock_code, ticker, stock_name, fiscal_year,
            sales, operating_profit, net_profit, roe, eps, per, pbr,
            dividend, dividend_yield, market_cap,
            total_assets, total_liabilities, total_debt, net_debt, cash,
            current_assets, current_liabilities, working_capital,
            equity, equity_ratio, debt_ratio, debt_to_equity_ratio,
            current_ratio, updated_at, fiscal_year_key
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
    """
    for stock_code, rows in finance_rows.items():
        connection.execute("DELETE FROM finance WHERE stock_code = ?", (stock_code,))
        connection.executemany(sql, rows)


def replace_simple_market_tables(
    connection: sqlite3.Connection,
    market: dict[str, pd.DataFrame],
) -> None:
    updated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")

    if "nikkei_average" in market:
        frame = market["nikkei_average"]
        connection.execute("DELETE FROM nikkei_average")
        connection.executemany(
            """
            INSERT INTO nikkei_average (
                trade_date, open_price, high_price, low_price,
                close_price, volume, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row["date"],
                    float(row["Open"]),
                    float(row["High"]),
                    float(row["Low"]),
                    float(row["Close"]),
                    float(row["Volume"]),
                    updated_at,
                )
                for _, row in frame.iterrows()
            ],
        )

    for source_name, table_name, date_name, value_name in (
        ("gold_close", "gold_price", "trade_date", "gold_close"),
        ("usd_jpy", "exchange_rates", "date", "usd_jpy"),
        ("wti_price", "oil_prices", "date", "wti_price"),
    ):
        if source_name not in market:
            continue
        connection.execute(f"DELETE FROM {table_name}")
        extra = ", updated_at" if table_name == "gold_price" else ""
        placeholders = "?, ?, ?" if table_name == "gold_price" else "?, ?"
        rows = [
            (
                (row["date"], float(row["Close"]), updated_at)
                if table_name == "gold_price"
                else (row["date"], float(row["Close"]))
            )
            for _, row in market[source_name].iterrows()
        ]
        connection.executemany(
            f"INSERT INTO {table_name} ({date_name}, {value_name}{extra}) "
            f"VALUES ({placeholders})",
            rows,
        )

    indicator_names = [
        "sp500_close",
        "nasdaq100_close",
        "dow_close",
        "vix_close",
        "us_10y_yield",
    ]
    available = [name for name in indicator_names if name in market]
    if available:
        merged: pd.DataFrame | None = None
        for name in available:
            part = market[name][["date", "Close"]].rename(columns={"Close": name})
            merged = part if merged is None else merged.merge(part, on="date", how="outer")
        assert merged is not None
        for missing in set(indicator_names) - set(available):
            merged[missing] = None
        connection.execute("DELETE FROM us_market_indicators")
        connection.executemany(
            """
            INSERT INTO us_market_indicators (
                trade_date, sp500_close, nasdaq100_close, dow_close,
                vix_close, us_10y_yield, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    row["date"],
                    value_or_none(row["sp500_close"]),
                    value_or_none(row["nasdaq100_close"]),
                    value_or_none(row["dow_close"]),
                    value_or_none(row["vix_close"]),
                    value_or_none(row["us_10y_yield"]),
                    updated_at,
                )
                for _, row in merged.sort_values("date").iterrows()
            ],
        )


def value_or_none(value: Any) -> float | None:
    return None if pd.isna(value) else float(value)


def filter_newer_than_database(
    connection: sqlite3.Connection,
    fetched: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    comparisons: dict[str, dict[str, Any]] = {}

    for stock_code, frame in list(fetched["stock_prices"].items()):
        database_max = connection.execute(
            "SELECT MAX(trade_date) FROM stock_prices WHERE stock_code = ?",
            (stock_code,),
        ).fetchone()[0]
        web_max = str(frame["date"].max())
        is_newer = database_max is None or web_max > str(database_max)
        comparisons[f"stock_prices:{stock_code}"] = {
            "database_max": database_max,
            "web_max": web_max,
            "updated": is_newer,
            "status": "web_is_newer" if is_newer else "database_is_current",
        }
        if not is_newer:
            del fetched["stock_prices"][stock_code]

    for stock_code, rows in list(fetched["finance"].items()):
        database_max = connection.execute(
            "SELECT MAX(fiscal_year) FROM finance WHERE stock_code = ?",
            (stock_code,),
        ).fetchone()[0]
        web_max = max(str(row[3]) for row in rows)
        is_newer = database_max is None or web_max > str(database_max)
        comparisons[f"finance:{stock_code}"] = {
            "database_max": database_max,
            "web_max": web_max,
            "updated": is_newer,
            "status": "web_is_newer" if is_newer else "database_is_current",
        }
        if not is_newer:
            del fetched["finance"][stock_code]

    simple_sources = {
        "nikkei_average": ("nikkei_average", "trade_date"),
        "gold_close": ("gold_price", "trade_date"),
        "usd_jpy": ("exchange_rates", "date"),
        "wti_price": ("oil_prices", "date"),
    }
    for source, (table, date_column) in simple_sources.items():
        if source not in fetched["market"]:
            continue
        database_max = connection.execute(
            f"SELECT MAX({date_column}) FROM {table}"
        ).fetchone()[0]
        web_max = str(fetched["market"][source]["date"].max())
        is_newer = database_max is None or web_max > str(database_max)
        comparisons[f"market:{source}"] = {
            "database_max": database_max,
            "web_max": web_max,
            "updated": is_newer,
            "status": "web_is_newer" if is_newer else "database_is_current",
        }
        if not is_newer:
            del fetched["market"][source]

    indicator_sources = [
        "sp500_close",
        "nasdaq100_close",
        "dow_close",
        "vix_close",
        "us_10y_yield",
    ]
    available = [name for name in indicator_sources if name in fetched["market"]]
    if available:
        database_max = connection.execute(
            "SELECT MAX(trade_date) FROM us_market_indicators"
        ).fetchone()[0]
        web_max = max(str(fetched["market"][name]["date"].max()) for name in available)
        is_newer = database_max is None or web_max > str(database_max)
        for source in available:
            comparisons[f"market:{source}"] = {
                "database_max": database_max,
                "web_max": str(fetched["market"][source]["date"].max()),
                "updated": is_newer,
                "status": "web_is_newer" if is_newer else "database_is_current",
            }
            if not is_newer:
                del fetched["market"][source]
    return comparisons


def validate_database(connection: sqlite3.Connection) -> dict[str, Any]:
    quick_check = connection.execute("PRAGMA quick_check").fetchone()[0]
    if quick_check != "ok":
        raise RuntimeError(f"SQLite quick_checkに失敗しました: {quick_check}")
    required_views = {
        "v_stock_fundamental",
        "v_macro_economic",
        "v_ai_stock_report_input",
    }
    found = {
        row[0]
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'view'"
        ).fetchall()
    }
    if required_views - found:
        raise RuntimeError("必要なVIEWが不足しています")
    return {
        "stock_prices": connection.execute(
            "SELECT COUNT(*), MIN(trade_date), MAX(trade_date) FROM stock_prices"
        ).fetchone(),
        "finance": connection.execute(
            "SELECT COUNT(*), COUNT(DISTINCT stock_code) FROM finance"
        ).fetchone(),
        "ai_view": connection.execute(
            "SELECT COUNT(*), MIN(trade_date), MAX(trade_date) "
            "FROM v_ai_stock_report_input"
        ).fetchone(),
    }


def main() -> None:
    args = parse_args()
    database = args.db.expanduser().resolve(strict=True)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    staging = database.with_name(f"{database.stem}.staging_{timestamp}.db")
    backup_directory = database.parent / "backups"
    backup_directory.mkdir(parents=True, exist_ok=True)
    backup = backup_directory / f"{database.stem}_{timestamp}.db"

    with closing(sqlite3.connect(database)) as connection:
        stocks = connection.execute(
            "SELECT stock_code, stock_name FROM stocks ORDER BY stock_code"
        ).fetchall()
    if args.stock_codes:
        requested = set(args.stock_codes)
        known = {stock_code for stock_code, _ in stocks}
        unknown = requested - known
        if unknown:
            raise ValueError(f"未登録の銘柄コードです: {', '.join(sorted(unknown))}")
        stocks = [stock for stock in stocks if stock[0] in requested]

    fetched, failures = fetch_all_sources(
        stocks,
        args.start,
        include_finance=not args.skip_finance,
    )
    shutil.copy2(database, staging)
    try:
        with closing(sqlite3.connect(staging)) as connection:
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("BEGIN")
            comparisons = filter_newer_than_database(connection, fetched)
            stock_price_update_summaries = upsert_stock_prices(
                connection,
                fetched["stock_prices"],
            )
            replace_finance(connection, fetched["finance"])
            replace_simple_market_tables(connection, fetched["market"])
            connection.commit()
            validation = validate_database(connection)

        shutil.copy2(database, backup)
        os.replace(staging, database)
    except Exception:
        if staging.exists():
            try:
                staging.unlink()
            except PermissionError:
                pass
        raise

    summary = {
        "updated_at": datetime.now().astimezone().isoformat(),
        "database": str(database),
        "backup": str(backup),
        "stock_price_successes": sorted(fetched["stock_prices"]),
        "finance_successes": sorted(fetched["finance"]),
        "market_successes": sorted(fetched["market"]),
        "failures": failures,
        "comparisons": comparisons,
        "stock_price_update_summaries": stock_price_update_summaries,
        "validation": validation,
        "not_updated": [
            "cpi",
            "gdp",
            "interest_rate_long",
            "policy_rate",
        ],
    }
    log_path = PROJECT_ROOT / "logs" / f"market_data_update_{timestamp}.json"
    log_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"更新ログ: {log_path}")


if __name__ == "__main__":
    main()
