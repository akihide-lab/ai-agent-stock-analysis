"""Search stocks with simple Japanese natural-language conditions."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

import pandas as pd

from db_connection import (
    DatabaseConfigurationError,
    DatabaseConnectionError,
    connect_database,
    get_db_type,
    get_placeholder,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "market_analysis.db"
VIEW_NAME = "v_agent_stock_candidates"


class StockSearchDatabaseError(RuntimeError):
    """Raised when stock candidate retrieval fails safely."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="自然言語の条件で銘柄候補を探索します。")
    parser.add_argument("query", help="例: 航空でROEが高くPERが低い銘柄")
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--limit", type=int, default=10)
    return parser.parse_args()


def _sqlite_env_for_path(path: Path | None) -> dict[str, str]:
    env = dict(os.environ)
    env["DB_TYPE"] = "sqlite"
    if path is not None:
        env["SQLITE_DB_PATH"] = str(path)
    return env


def connect_read_only(path: Path | None = None) -> Any:
    db_type = get_db_type()
    env = _sqlite_env_for_path(path) if db_type == "sqlite" else None
    return connect_database(read_only=True, env=env)


def _close_connection(connection: Any) -> None:
    close = getattr(connection, "close", None)
    if callable(close):
        close()


def _view_exists(connection: Any, db_type: str) -> bool:
    placeholder = get_placeholder(db_type)
    if db_type == "sqlite":
        sql = f"""
            SELECT 1
            FROM sqlite_master
            WHERE type = 'view'
              AND name = {placeholder}
            LIMIT 1
        """
    else:
        sql = f"""
            SELECT 1
            FROM information_schema.views
            WHERE table_schema = COALESCE({placeholder}, current_schema())
              AND table_name = {placeholder}
            LIMIT 1
        """
    params: tuple[object, ...]
    if db_type == "sqlite":
        params = (VIEW_NAME,)
    else:
        params = (None, VIEW_NAME)

    if db_type == "sqlite":
        row = connection.execute(sql, params).fetchone()
    else:
        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            row = cursor.fetchone()
    return row is not None


def load_candidates(db_path: Path) -> pd.DataFrame:
    db_type = get_db_type()
    query = """
        SELECT
            stock_code,
            stock_name,
            market,
            sector,
            latest_trade_date AS trade_date,
            latest_close_price AS close_price,
            volume,
            latest_fiscal_year AS fiscal_year,
            roe,
            per,
            pbr,
            dividend_yield,
            equity_ratio
        FROM v_agent_stock_candidates
        ORDER BY stock_code
    """
    connection = None
    try:
        connection = connect_read_only(db_path)
        if not _view_exists(connection, db_type):
            raise StockSearchDatabaseError(
                f"Required view is not available: {VIEW_NAME}"
            )
        frame = pd.read_sql_query(query, connection)
    except StockSearchDatabaseError:
        raise
    except (DatabaseConfigurationError, DatabaseConnectionError):
        raise
    except Exception as exc:
        raise StockSearchDatabaseError(
            "Failed to load stock candidates from the configured database."
        ) from exc
    finally:
        if connection is not None:
            _close_connection(connection)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame


def summarize_stocks(frame: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (code, name, sector), group in frame.groupby(
        ["stock_code", "stock_name", "sector"], dropna=False
    ):
        group = group.sort_values("trade_date")
        latest = group.iloc[-1]
        rows.append(
            {
                "stock_code": code,
                "stock_name": name,
                "sector": sector,
                "latest_trade_date": latest["trade_date"],
                "latest_close_price": latest["close_price"],
                "volume": latest.get("volume"),
                "one_year_change_pct": None,
                "roe": latest.get("roe"),
                "per": latest.get("per"),
                "pbr": latest.get("pbr"),
                "dividend_yield": latest.get("dividend_yield"),
                "equity_ratio": latest.get("equity_ratio"),
                "usd_jpy_correlation": None,
                "wti_correlation": None,
            }
        )
    return pd.DataFrame(rows)


def natural_language_search(summary: pd.DataFrame, query: str) -> tuple[pd.DataFrame, list[str]]:
    result = summary.copy()
    reasons: list[str] = []

    def has_values(column: str) -> bool:
        return column in result and result[column].notna().any()

    sectors = [str(value) for value in result["sector"].dropna().unique()]
    matched_sector = next((sector for sector in sectors if sector in query), None)
    if matched_sector:
        result = result[result["sector"] == matched_sector]
        reasons.append(f"業界を「{matched_sector}」に限定")

    wants_roe = "ROE" in query.upper() or "収益性" in query
    wants_value = "割安" in query or "PERが低" in query or "低PER" in query
    wants_dividend = "高配当" in query or "配当" in query
    wants_momentum = "上昇" in query or "好調" in query or "強い" in query
    wants_stability = "安定" in query or "安全" in query or "初心者" in query
    wants_weak_yen = "円安に強" in query
    wants_oil_risk = "原油高に弱" in query
    required_columns = []
    if wants_roe and has_values("roe"):
        required_columns.append("roe")
    if wants_value and has_values("per"):
        required_columns.append("per")
    if wants_dividend and has_values("dividend_yield"):
        required_columns.append("dividend_yield")
    if wants_momentum and has_values("one_year_change_pct"):
        required_columns.append("one_year_change_pct")
    if wants_stability and has_values("equity_ratio"):
        required_columns.append("equity_ratio")
    if wants_weak_yen and has_values("usd_jpy_correlation"):
        required_columns.append("usd_jpy_correlation")
    if wants_oil_risk and has_values("wti_correlation"):
        required_columns.append("wti_correlation")
    if required_columns:
        result = result.dropna(subset=required_columns)

    score = pd.Series(0.0, index=result.index)
    if wants_roe and has_values("roe"):
        score += result["roe"].rank(pct=True, na_option="bottom")
        reasons.append("ROEが高い銘柄を優先")
    if wants_value and has_values("per"):
        score += result["per"].rank(ascending=False, pct=True, na_option="bottom")
        reasons.append("PERが低い銘柄を優先")
    if wants_dividend and has_values("dividend_yield"):
        score += result["dividend_yield"].rank(pct=True, na_option="bottom")
        reasons.append("配当利回りが高い銘柄を優先")
    if wants_momentum and has_values("one_year_change_pct"):
        score += result["one_year_change_pct"].rank(pct=True, na_option="bottom")
        reasons.append("1年騰落率が高い銘柄を優先")
    elif wants_momentum and has_values("volume"):
        score += result["volume"].rank(pct=True, na_option="bottom")
        reasons.append("軽量候補VIEWで確認できる出来高が大きい銘柄を優先")
    if wants_stability and has_values("equity_ratio"):
        score += result["equity_ratio"].rank(pct=True, na_option="bottom")
        reasons.append("自己資本比率が高い銘柄を優先")
    if wants_weak_yen and has_values("usd_jpy_correlation"):
        score += result["usd_jpy_correlation"].rank(pct=True, na_option="bottom")
        reasons.append("ドル円との正の相関が高い銘柄を優先")
    if wants_oil_risk and has_values("wti_correlation"):
        score += (-result["wti_correlation"]).rank(pct=True, na_option="bottom")
        reasons.append("原油価格との負の相関が強い銘柄を優先")
    if not reasons:
        if has_values("volume"):
            score += result["volume"].rank(pct=True, na_option="bottom")
            reasons.append("軽量候補VIEWで確認できる出来高で並べ替え")
        else:
            reasons.append("軽量候補VIEWで取得できる銘柄を表示")

    result["match_score"] = score
    return result.sort_values("match_score", ascending=False), reasons


def main() -> None:
    args = parse_args()
    summary = summarize_stocks(load_candidates(args.db))
    results, reasons = natural_language_search(summary, args.query)
    print("解釈:", " / ".join(reasons))
    columns = [
        "stock_code",
        "stock_name",
        "sector",
        "latest_trade_date",
        "latest_close_price",
        "volume",
        "one_year_change_pct",
        "roe",
        "per",
        "dividend_yield",
        "equity_ratio",
        "match_score",
    ]
    display = results[columns].head(args.limit).copy()
    display["roe"] *= 100
    display["dividend_yield"] *= 100
    display["equity_ratio"] *= 100
    display = display.rename(
        columns={
            "roe": "roe_pct",
            "dividend_yield": "dividend_yield_pct",
            "equity_ratio": "equity_ratio_pct",
        }
    )
    print(display.to_string(index=False))


if __name__ == "__main__":
    main()
