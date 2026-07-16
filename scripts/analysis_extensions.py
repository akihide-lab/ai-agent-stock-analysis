"""Read-only reporting extensions built on top of the legacy analysis results."""

from __future__ import annotations

import math
import os
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pandas as pd

from db_connection import (
    DatabaseConfigurationError,
    DatabaseConnectionError,
    connect_database,
    get_db_type,
    get_placeholder,
)


FUNDAMENTAL_COLUMNS = [
    "sales",
    "operating_profit",
    "net_profit",
    "roe",
    "eps",
    "per",
    "pbr",
    "dividend_yield",
    "equity_ratio",
]
PERIODS = {"1年前": 1, "3年前": 3}


class AnalysisExtensionDatabaseError(RuntimeError):
    """Raised when reporting extensions cannot read the configured database."""


def _sqlite_env_for_path(db_path: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["DB_TYPE"] = "sqlite"
    env["SQLITE_DB_PATH"] = str(db_path)
    return env


def connect_read_only(db_path: Path) -> Any:
    db_type = get_db_type()
    env = _sqlite_env_for_path(db_path) if db_type == "sqlite" else None
    return connect_database(read_only=True, env=env)


def _close_connection(connection: Any) -> None:
    close = getattr(connection, "close", None)
    if callable(close):
        close()


def calculate_period_changes(frame: pd.DataFrame) -> pd.DataFrame:
    ordered = frame.dropna(subset=["trade_date", "close_price"]).sort_values("trade_date")
    latest = ordered.iloc[-1]
    results: list[dict[str, object]] = []
    for label, years in PERIODS.items():
        target_date = latest["trade_date"] - pd.DateOffset(years=years)
        candidates = ordered[ordered["trade_date"] <= target_date]
        if candidates.empty:
            results.append(
                {
                    "period": label,
                    "base_date": None,
                    "base_close": None,
                    "latest_close": latest["close_price"],
                    "change_pct": None,
                }
            )
            continue
        base = candidates.iloc[-1]
        change = (latest["close_price"] / base["close_price"] - 1) * 100
        results.append(
            {
                "period": label,
                "base_date": base["trade_date"],
                "base_close": base["close_price"],
                "latest_close": latest["close_price"],
                "change_pct": change,
            }
        )
    return pd.DataFrame(results)


def fundamental_history(frame: pd.DataFrame) -> pd.DataFrame:
    available = frame.dropna(subset=["fiscal_year"]).copy()
    available = available.dropna(subset=FUNDAMENTAL_COLUMNS, how="all")
    if available.empty:
        return pd.DataFrame(columns=["fiscal_year", *FUNDAMENTAL_COLUMNS])
    available["fiscal_year"] = available["fiscal_year"].astype(str)
    return (
        available.sort_values("trade_date")
        .drop_duplicates(subset=["fiscal_year"], keep="last")
        [["fiscal_year", *FUNDAMENTAL_COLUMNS]]
        .reset_index(drop=True)
    )


def calculate_fundamental_changes(history: pd.DataFrame) -> pd.DataFrame:
    if history.empty:
        return pd.DataFrame(columns=["metric", "latest", "previous", "change_pct"])
    latest = history.iloc[-1]
    previous = history.iloc[-2] if len(history) >= 2 else None
    rows = []
    for metric in FUNDAMENTAL_COLUMNS:
        current = latest[metric]
        prior = previous[metric] if previous is not None else None
        if (
            prior is not None
            and not pd.isna(prior)
            and float(prior) != 0
            and not pd.isna(current)
        ):
            change = (float(current) / float(prior) - 1) * 100
        else:
            change = None
        rows.append(
            {
                "metric": metric,
                "latest": current,
                "previous": prior,
                "change_pct": change,
            }
        )
    return pd.DataFrame(rows)


def load_sector_data(db_path: Path, sector: str) -> pd.DataFrame:
    placeholder = get_placeholder()
    query = f"""
        SELECT
            stock_code,
            stock_name,
            sector,
            trade_date,
            close_price,
            fiscal_year,
            sales,
            operating_profit,
            net_profit,
            roe,
            eps,
            per,
            pbr,
            dividend_yield,
            equity_ratio
        FROM v_ai_stock_report_input
        WHERE sector = {placeholder}
        ORDER BY stock_code, trade_date
    """
    connection = None
    try:
        connection = connect_read_only(db_path)
        frame = pd.read_sql_query(query, connection, params=(sector,))
    except (DatabaseConfigurationError, DatabaseConnectionError):
        raise
    except Exception:
        raise AnalysisExtensionDatabaseError(
            "Failed to load sector data from the configured database."
        ) from None
    finally:
        if connection is not None:
            _close_connection(connection)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame


def build_peer_comparison(sector_frame: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for (stock_code, stock_name), group in sector_frame.groupby(
        ["stock_code", "stock_name"], sort=True
    ):
        group = group.sort_values("trade_date")
        latest = group.dropna(subset=["close_price"]).iloc[-1]
        changes = calculate_period_changes(group)
        one_year = changes.loc[changes["period"] == "1年前", "change_pct"].iloc[0]
        history = fundamental_history(group)
        fundamentals = history.iloc[-1] if not history.empty else {}
        row: dict[str, object] = {
            "stock_code": stock_code,
            "stock_name": stock_name,
            "latest_close": latest["close_price"],
            "one_year_change_pct": one_year,
        }
        for metric in FUNDAMENTAL_COLUMNS:
            row[metric] = fundamentals.get(metric) if len(fundamentals) else None
        rows.append(row)
    comparison = pd.DataFrame(rows)
    if not comparison.empty:
        comparison["one_year_rank"] = comparison["one_year_change_pct"].rank(
            ascending=False, method="min"
        )
        comparison["roe_rank"] = comparison["roe"].rank(ascending=False, method="min")
        comparison["per_rank"] = comparison["per"].rank(ascending=True, method="min")
    return comparison


def _chart_style() -> None:
    plt.style.use("seaborn-v0_8-whitegrid")
    plt.rcParams["axes.unicode_minus"] = False


def generate_charts(
    frame: pd.DataFrame,
    sector_frame: pd.DataFrame,
    output_dir: Path,
    stock_code: str,
) -> dict[str, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    _chart_style()
    paths: dict[str, Path] = {}

    price_path = output_dir / f"{stock_code}_price_history.png"
    fig, axis = plt.subplots(figsize=(10, 4.8))
    axis.plot(frame["trade_date"], frame["close_price"], linewidth=1.5)
    axis.set_title(f"{stock_code} Close Price")
    axis.set_xlabel("Date")
    axis.set_ylabel("Close")
    fig.tight_layout()
    fig.savefig(price_path, dpi=150)
    plt.close(fig)
    paths["price_history"] = price_path

    peer_path = output_dir / f"{stock_code}_peer_performance.png"
    fig, axis = plt.subplots(figsize=(10, 4.8))
    comparison_end = sector_frame["trade_date"].max()
    comparison_start = comparison_end - pd.DateOffset(years=1)
    for (code, _), group in sector_frame.groupby(["stock_code", "stock_name"]):
        usable = (
            group[group["trade_date"] >= comparison_start]
            .dropna(subset=["close_price"])
            .sort_values("trade_date")
        )
        if usable.empty:
            continue
        normalized = usable["close_price"] / usable["close_price"].iloc[0] * 100
        width = 2.2 if str(code) == str(stock_code) else 1.0
        axis.plot(usable["trade_date"], normalized, label=str(code), linewidth=width)
    axis.set_title("1-Year Sector Peer Performance (Start = 100)")
    axis.set_xlabel("Date")
    axis.set_ylabel("Indexed Close")
    axis.legend()
    fig.tight_layout()
    fig.savefig(peer_path, dpi=150)
    plt.close(fig)
    paths["peer_performance"] = peer_path

    return paths


def _safe_number(value: object) -> float | None:
    if value is None or pd.isna(value):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def build_factor_assessment(
    period_changes: pd.DataFrame,
    fundamental_changes: pd.DataFrame,
    peer_comparison: pd.DataFrame,
    stock_code: str,
    statistical_results: dict[str, pd.DataFrame],
) -> dict[str, object]:
    positives: list[str] = []
    risks: list[str] = []
    score = 0

    one_year_series = period_changes.loc[
        period_changes["period"] == "1年前", "change_pct"
    ]
    one_year = _safe_number(one_year_series.iloc[0]) if not one_year_series.empty else None
    if one_year is not None:
        if one_year >= 10:
            positives.append(f"1年間の株価騰落率が {one_year:.1f}% と堅調")
            score += 1
        elif one_year <= -10:
            risks.append(f"1年間の株価騰落率が {one_year:.1f}% と軟調")
            score -= 1

    changes = fundamental_changes.set_index("metric") if not fundamental_changes.empty else None
    if changes is not None:
        for metric, label in (
            ("sales", "売上高"),
            ("operating_profit", "営業利益"),
            ("net_profit", "純利益"),
        ):
            if metric not in changes.index:
                continue
            change = _safe_number(changes.loc[metric, "change_pct"])
            if change is not None and change >= 5:
                positives.append(f"{label}が前期比 {change:.1f}% 増加")
                score += 1
            elif change is not None and change <= -5:
                risks.append(f"{label}が前期比 {change:.1f}% 減少")
                score -= 1

    target = peer_comparison[
        peer_comparison["stock_code"].astype(str) == str(stock_code)
    ]
    if not target.empty:
        row = target.iloc[0]
        roe = _safe_number(row.get("roe"))
        per = _safe_number(row.get("per"))
        median_per = _safe_number(peer_comparison["per"].median())
        if roe is not None:
            if roe >= 0.10:
                positives.append(f"ROEが {roe * 100:.1f}%")
                score += 1
            elif roe < 0.05:
                risks.append(f"ROEが {roe * 100:.1f}% と低い")
                score -= 1
        if per is not None and median_per is not None:
            if per < median_per * 0.8:
                positives.append(
                    f"PER {per:.1f}倍は業界中央値 {median_per:.1f}倍を下回る"
                )
                score += 1
            elif per > median_per * 1.2:
                risks.append(
                    f"PER {per:.1f}倍は業界中央値 {median_per:.1f}倍を上回る"
                )
                score -= 1

    correlation = statistical_results["correlation"].dropna(subset=["correlation"]).copy()
    if not correlation.empty:
        correlation["absolute"] = correlation["correlation"].abs()
        strongest = correlation.sort_values("absolute", ascending=False).iloc[0]
        direction = "正" if strongest["correlation"] >= 0 else "負"
        risks.append(
            f"`{strongest['indicator']}`との{direction}の相関が比較的大きい"
            f"（{strongest['correlation']:.2f}）"
        )

    if score >= 2:
        judgment = "データ上はやや強気"
    elif score <= -2:
        judgment = "データ上は慎重"
    else:
        judgment = "データ上は中立"
    return {
        "positive_factors": positives or ["明確な上昇要因はデータから確認できませんでした"],
        "risk_factors": risks or ["明確なリスク要因はデータから確認できませんでした"],
        "score": score,
        "judgment": judgment,
    }


def build_narrative(
    frame: pd.DataFrame,
    period_changes: pd.DataFrame,
    fundamental_history_frame: pd.DataFrame,
    fundamental_changes: pd.DataFrame,
    peer_comparison: pd.DataFrame,
    stock_code: str,
    statistical_results: dict[str, pd.DataFrame],
    assessment: dict[str, object],
) -> list[str]:
    name = str(frame.iloc[-1]["stock_name"])
    paragraphs: list[str] = []

    one_year = period_changes.loc[
        period_changes["period"] == "1年前", "change_pct"
    ].iloc[0]
    three_year = period_changes.loc[
        period_changes["period"] == "3年前", "change_pct"
    ].iloc[0]
    period_parts = []
    if not pd.isna(one_year):
        period_parts.append(f"1年間で {one_year:.1f}%")
    if not pd.isna(three_year):
        period_parts.append(f"3年間で {three_year:.1f}%")
    if period_parts:
        paragraphs.append(
            f"{name}の株価は、取得可能な営業日ベースで"
            + "、".join(period_parts)
            + "変化しています。"
        )

    if not fundamental_history_frame.empty:
        latest_year = fundamental_history_frame.iloc[-1]["fiscal_year"]
        latest = fundamental_changes.set_index("metric")
        values = []
        for metric, label in (
            ("sales", "売上高"),
            ("operating_profit", "営業利益"),
            ("net_profit", "純利益"),
        ):
            change = _safe_number(latest.loc[metric, "change_pct"])
            if change is not None:
                values.append(f"{label}は前期比 {change:+.1f}%")
        if values:
            paragraphs.append(
                f"最新の財務年度（{latest_year}）では、" + "、".join(values) + "です。"
            )
        else:
            paragraphs.append(
                f"最新の財務年度は {latest_year} ですが、前期比較に必要な年度数が不足しています。"
            )
    else:
        paragraphs.append("財務指標はVIEW上で取得できないため、財務面の評価は保留します。")

    target = peer_comparison[
        peer_comparison["stock_code"].astype(str) == str(stock_code)
    ]
    if not target.empty and len(peer_comparison) > 1:
        row = target.iloc[0]
        rank = _safe_number(row.get("one_year_rank"))
        if rank is not None:
            paragraphs.append(
                f"同一業界 {len(peer_comparison)}銘柄の1年騰落率比較では"
                f" {int(rank)} 位です。"
            )

    summary = statistical_results["regression_summary"].iloc[0]
    significant = statistical_results["regression"][
        (statistical_results["regression"]["indicator"] != "const")
        & (statistical_results["regression"]["p_value"] < 0.05)
    ]
    if significant.empty:
        significant_text = "5%水準で有意な説明変数は確認されませんでした"
    else:
        significant_text = (
            "5%水準で有意な指標は "
            + "、".join(f"`{item}`" for item in significant["indicator"])
            + " です"
        )
    paragraphs.append(
        f"マクロ6指標による重回帰の決定係数は {summary['r2']:.3f} で、"
        f"{significant_text}。相関・回帰は因果関係を示すものではありません。"
    )
    paragraphs.append(
        f"以上を機械的に集約した総合判断は「{assessment['judgment']}」です。"
        "これは投資推奨ではなく、現在のVIEWデータに基づく整理です。"
    )
    return paragraphs
