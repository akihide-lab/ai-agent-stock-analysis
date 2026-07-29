"""Generate a stock analysis report from approved database views.

The database is opened in read-only mode. Existing analysis and prediction
functions are reused, while their database-writing entry points are never
called.
"""

from __future__ import annotations

import argparse
import json
import math
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from analysis_extensions import (
    build_factor_assessment,
    build_narrative,
    build_peer_comparison,
    calculate_fundamental_changes,
    calculate_period_changes,
    fundamental_history,
    generate_charts,
)
from db_connection import (
    DatabaseConfigurationError,
    DatabaseConnectionError,
    connect_database,
    get_db_type,
    get_placeholder,
    get_view_exists_sql,
)
from html_report import build_self_contained_html
from s3_uploader import upload_report_to_s3
from legacy_analysis.correlation_regression_analysis import (
    calculate_correlation,
    calculate_standardized_regression,
    calculate_vif,
    regression_with_pvalue,
)
from legacy_analysis.feature_engineering import create_lag_features
from legacy_analysis.prediction_model import run_model_comparison


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "market_analysis.db"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "reports"
REPORT_VIEW = "v_ai_stock_report_input"
ALLOWED_VIEWS = {
    "v_stock_fundamental",
    "v_macro_economic",
    "v_ai_stock_report_input",
}
ANALYSIS_FEATURES = [
    "wti_price",
    "usd_jpy",
    "policy_rate",
    "jgb_10y_yield",
    "cpi_index",
    "gdp_growth",
]
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
SELECT_COLUMNS = [
    "stock_code",
    "stock_name",
    "market",
    "sector",
    "trade_date",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "volume",
    "fiscal_year",
    *FUNDAMENTAL_COLUMNS,
    "year",
    "year_month",
    "quarter",
    "nikkei_close_price",
    "usd_jpy",
    "jgb_10y_yield",
    "wti_price",
    "gold_close",
    "sp500_close",
    "nasdaq100_close",
    "dow_close",
    "vix_close",
    "us_10y_yield",
    "cpi_index",
    "cpi_mom",
    "gdp_amount",
    "gdp_growth",
    "policy_rate",
]


def display_database_label(db_path: Path) -> str:
    """Return a public-safe database label for generated reports."""
    try:
        relative = db_path.expanduser().resolve().relative_to(PROJECT_ROOT)
    except (OSError, RuntimeError, ValueError):
        return "SQLite Database"
    return relative.as_posix()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="承認済みSQLite VIEWから銘柄分析Markdownを生成します。"
    )
    parser.add_argument(
        "--stock-code",
        default="9202",
        help="分析対象の銘柄コード（既定: 9202）",
    )
    parser.add_argument(
        "--db",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="market_analysis.db のパス",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="出力HTMLのパス（省略時: reports/stock_report_<code>.html）",
    )
    parser.add_argument(
        "--acquisition-log",
        type=Path,
        help="Web取得結果JSON。統合実行時にレポートへ鮮度比較を掲載します。",
    )
    return parser.parse_args()


class ReportDatabaseError(RuntimeError):
    """Raised when report generation cannot read the configured database."""


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


def _fetchone(connection: Any, sql: str, params: tuple[object, ...] = ()) -> Any:
    if get_db_type() == "sqlite":
        return connection.execute(sql, params).fetchone()
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchone()


def _view_exists(connection: Any, view_name: str) -> bool:
    db_type = get_db_type()
    sql = get_view_exists_sql(db_type)
    params = (view_name,) if db_type == "sqlite" else (None, view_name)
    return _fetchone(connection, sql, params) is not None


def validate_views(connection: Any) -> None:
    missing = {
        view_name
        for view_name in ALLOWED_VIEWS
        if not _view_exists(connection, view_name)
    }
    if missing:
        raise RuntimeError(f"必要なVIEWがありません: {', '.join(sorted(missing))}")


def load_report_input(db_path: Path, stock_code: str) -> pd.DataFrame:
    placeholder = get_placeholder()
    columns = ",\n            ".join(SELECT_COLUMNS)
    query = f"""
        SELECT
            {columns}
        FROM {REPORT_VIEW}
        WHERE stock_code = {placeholder}
        ORDER BY trade_date
    """
    connection = None
    try:
        connection = connect_read_only(db_path)
        validate_views(connection)
        frame = pd.read_sql_query(query, connection, params=(stock_code,))
    except (DatabaseConfigurationError, DatabaseConnectionError):
        raise
    except Exception:
        raise ReportDatabaseError(
            "Failed to load report input from the configured database."
        ) from None
    finally:
        if connection is not None:
            _close_connection(connection)

    if frame.empty:
        raise ValueError(f"銘柄コード {stock_code} のデータがありません。")

    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame


def load_database_freshness(db_path: Path, stock_code: str) -> pd.DataFrame:
    placeholder = get_placeholder()
    checks = [
        ("対象銘柄株価", "SELECT MAX(trade_date) FROM stock_prices WHERE stock_code = ?", (stock_code,), "Yahoo Finance"),
        ("対象銘柄財務", "SELECT MAX(fiscal_year) FROM finance WHERE stock_code = ?", (stock_code,), "Yahoo Finance"),
        ("日経平均", "SELECT MAX(trade_date) FROM nikkei_average", (), "Yahoo Finance"),
        ("米国市場指標", "SELECT MAX(trade_date) FROM us_market_indicators", (), "Yahoo Finance"),
        ("金価格", "SELECT MAX(trade_date) FROM gold_price", (), "Yahoo Finance"),
        ("ドル円", "SELECT MAX(date) FROM exchange_rates", (), "Yahoo Finance"),
        ("WTI原油", "SELECT MAX(date) FROM oil_prices", (), "Yahoo Finance"),
        ("CPI", "SELECT MAX(year_month) FROM cpi", (), "既存公的統計CSV"),
        ("GDP", "SELECT MAX(fiscal_year) FROM gdp", (), "既存公的統計CSV"),
        ("日本10年金利", "SELECT MAX(date) FROM interest_rate_long", (), "既存公的統計CSV"),
        ("政策金利", "SELECT MAX(year_month) FROM policy_rate", (), "既存公的統計CSV"),
    ]
    rows = []
    connection = None
    try:
        connection = connect_read_only(db_path)
        for label, query, params, source in checks:
            effective_query = query.replace("?", placeholder)
            latest = _fetchone(connection, effective_query, params)[0]
            rows.append({"data_source": label, "latest": latest, "source": source})
    except (DatabaseConfigurationError, DatabaseConnectionError):
        raise
    except Exception:
        raise ReportDatabaseError(
            "Failed to load database freshness from the configured database."
        ) from None
    finally:
        if connection is not None:
            _close_connection(connection)
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
        raise ReportDatabaseError(
            "Failed to load sector data from the configured database."
        ) from None
    finally:
        if connection is not None:
            _close_connection(connection)
    frame["trade_date"] = pd.to_datetime(frame["trade_date"])
    return frame


def prepare_statistical_data(frame: pd.DataFrame) -> pd.DataFrame:
    columns = ["stock_name", "close_price", *ANALYSIS_FEATURES]
    analysis = frame[columns].copy()
    for column in ["close_price", *ANALYSIS_FEATURES]:
        analysis[column] = pd.to_numeric(analysis[column], errors="coerce")
    return analysis.dropna().reset_index(drop=True)


def run_existing_statistical_analysis(
    analysis: pd.DataFrame,
) -> dict[str, pd.DataFrame]:
    if len(analysis) < 20:
        raise ValueError(
            f"統計解析に必要な完全行が不足しています（{len(analysis)}行、最低20行）。"
        )
    regression, summary = regression_with_pvalue(analysis)
    return {
        "correlation": calculate_correlation(analysis),
        "regression": regression,
        "regression_summary": summary,
        "vif": calculate_vif(analysis),
        "standardized": calculate_standardized_regression(analysis),
    }


def run_existing_prediction(frame: pd.DataFrame) -> tuple[pd.DataFrame, str | None]:
    unique_months = frame["trade_date"].dt.to_period("M").nunique()
    if unique_months < 12:
        return pd.DataFrame(), (
            f"予測は実行していません。月次データが不足しています"
            f"（{unique_months}か月、最低12か月）。"
        )

    feature_input = frame[
        ["trade_date", "stock_code", "stock_name", "close_price", "policy_rate"]
    ].dropna()
    feature_frame = create_lag_features(feature_input.copy())
    if len(feature_frame) < 20:
        return pd.DataFrame(), (
            f"予測は実行していません。ラグ作成後のデータが不足しています"
            f"（{len(feature_frame)}行、最低20行）。"
        )

    target_month = feature_frame["trade_date"].max().strftime("%Y-%m")
    return run_model_comparison(feature_frame, target_month), None


def format_value(value: object, digits: int = 4) -> str:
    if pd.isna(value):
        return "データなし"
    if isinstance(value, (float, int)):
        numeric = float(value)
        if not math.isfinite(numeric):
            return str(numeric)
        return f"{numeric:,.{digits}f}"
    return str(value)


def markdown_table(
    frame: pd.DataFrame,
    columns: Iterable[str],
    labels: Iterable[str],
    digits: int = 4,
) -> str:
    selected_columns = list(columns)
    selected_labels = list(labels)
    lines = [
        "| " + " | ".join(selected_labels) + " |",
        "|" + "|".join("---" for _ in selected_labels) + "|",
    ]
    for _, row in frame[selected_columns].iterrows():
        lines.append(
            "| "
            + " | ".join(format_value(row[column], digits) for column in selected_columns)
            + " |"
        )
    return "\n".join(lines)


def _news_to_dict(news: Any) -> dict[str, Any]:
    return news.__dict__ if hasattr(news, "__dict__") else dict(news)


def _is_public_news(news: dict[str, Any]) -> bool:
    source = str(news.get("source") or "").lower()
    url = str(news.get("url") or "").lower()
    return source != "sample_news" and "example.com" not in url


def build_latest_news_section(
    news_documents: list[Any] | None,
    stock_code: str,
    stock_name: str,
) -> list[str]:
    lines = ["## 最新ニュース", ""]
    public_news = [
        _news_to_dict(news)
        for news in news_documents or []
        if _is_public_news(_news_to_dict(news))
    ]
    if not public_news:
        return [*lines, "現在、関連ニュースはありません。", ""]

    for index, item in enumerate(public_news, start=1):
        published_at = item.get("published_at")
        lines.extend(
            [
                f"### {index}. {item.get('title') or 'No title'}",
                "",
                f"- 銘柄コード: {item.get('stock_code') or stock_code}",
                f"- 会社名: {item.get('company_name') or stock_name}",
                f"- 出典: {item.get('source') or 'unknown'}",
                f"- 公開日時: {published_at or 'unknown'}",
                f"- URL: {item.get('url') or 'unknown'}",
                f"- 概要: {item.get('body') or '概要は取得できませんでした。'}",
                "",
            ]
        )
    return lines


def build_news_analysis_section(news_analysis: Any | None) -> list[str]:
    lines = ["## ニュースから見た注目ポイント", ""]
    if not news_analysis:
        return [
            *lines,
            "ニュースが取得できなかったため、ニュースに基づく考察は行っていません。",
            "",
        ]
    item = news_analysis.__dict__ if hasattr(news_analysis, "__dict__") else dict(news_analysis)
    positives = item.get("positive_factors") or []
    negatives = item.get("negative_factors") or []
    lines.extend(
        [
            str(item.get("summary") or ""),
            "",
            "### プラス要因",
            "",
            *[f"- {factor}" for factor in positives],
            *([] if positives else ["- 明確なプラス要因は取得ニュースからは確認できません。"]),
            "",
            "### マイナス要因",
            "",
            *[f"- {factor}" for factor in negatives],
            *([] if negatives else ["- 明確なマイナス要因は取得ニュースからは確認できません。"]),
            "",
            "### 短期的な影響",
            "",
            str(item.get("short_term_impact") or ""),
            "",
            "### 中長期的な影響",
            "",
            str(item.get("medium_long_term_impact") or ""),
            "",
            "### 不確実性",
            "",
            str(item.get("uncertainty") or ""),
            "",
        ]
    )
    return lines


def build_interpretation(results: dict[str, pd.DataFrame]) -> list[str]:
    correlation = results["correlation"].dropna(subset=["correlation"]).copy()
    correlation["absolute"] = correlation["correlation"].abs()
    strongest = correlation.sort_values("absolute", ascending=False).iloc[0]

    regression = results["regression"]
    significant = regression[
        (regression["indicator"] != "const") & (regression["p_value"] < 0.05)
    ].sort_values("p_value")

    messages = [
        (
            f"単純相関が最も大きい指標は `{strongest['indicator']}` "
            f"（相関係数 {strongest['correlation']:.4f}）です。"
        )
    ]
    if significant.empty:
        messages.append(
            "重回帰分析では、5%水準で有意な説明変数は確認できませんでした。"
        )
    else:
        names = "、".join(f"`{name}`" for name in significant["indicator"].tolist())
        messages.append(f"重回帰分析で5%水準の有意性が確認された指標は {names} です。")
    messages.append(
        "相関や回帰係数は因果関係を保証しません。投資判断では最新情報と事業要因も確認してください。"
    )
    return messages


def build_report(
    frame: pd.DataFrame,
    statistical_input: pd.DataFrame,
    results: dict[str, pd.DataFrame],
    prediction: pd.DataFrame,
    prediction_note: str | None,
    period_changes: pd.DataFrame,
    fundamental_history_frame: pd.DataFrame,
    fundamental_changes: pd.DataFrame,
    peer_comparison: pd.DataFrame,
    charts: dict[str, Path],
    assessment: dict[str, object],
    narrative: list[str],
    database_freshness: pd.DataFrame,
    acquisition: dict[str, object] | None,
    news_documents: list[Any] | None,
    news_analysis: Any | None,
    db_path: Path,
) -> str:
    latest = frame.sort_values("trade_date").iloc[-1]
    stock_code = str(latest["stock_code"])
    stock_name = str(latest["stock_name"])
    generated_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")

    latest_fundamentals = (
        fundamental_history_frame.iloc[-1]
        if not fundamental_history_frame.empty
        else {}
    )
    ratio_columns = {"roe", "dividend_yield", "equity_ratio"}
    fundamentals = pd.DataFrame(
        [
            {
                "metric": f"{column}（%）" if column in ratio_columns else column,
                "value": (
                    latest_fundamentals.get(column) * 100
                    if column in ratio_columns
                    and not pd.isna(latest_fundamentals.get(column))
                    else latest_fundamentals.get(column)
                ),
            }
            for column in FUNDAMENTAL_COLUMNS
        ]
    )
    fundamental_history_display = fundamental_history_frame.copy()
    for column in ratio_columns:
        if column in fundamental_history_display:
            fundamental_history_display[column] *= 100
    fundamental_changes_display = fundamental_changes.copy()
    if not fundamental_changes_display.empty:
        ratio_mask = fundamental_changes_display["metric"].isin(ratio_columns)
        fundamental_changes_display.loc[ratio_mask, "latest"] *= 100
        fundamental_changes_display.loc[ratio_mask, "previous"] *= 100
        fundamental_changes_display.loc[ratio_mask, "metric"] += "（%）"
    peer_comparison_display = peer_comparison.copy()
    for column in ("roe", "dividend_yield"):
        if column in peer_comparison_display:
            peer_comparison_display[column] *= 100
    availability = pd.DataFrame(
        [
            {
                "column": column,
                "available": int(frame[column].notna().sum()),
                "total": len(frame),
            }
            for column in ["close_price", *ANALYSIS_FEATURES, *FUNDAMENTAL_COLUMNS]
        ]
    )

    lines = [
        f"# 銘柄分析レポート: {stock_name}（{stock_code}）",
        "",
        f"- 生成日時: {generated_at}",
        f"- 参照DB: `{display_database_label(db_path)}`",
        f"- 参照VIEW: `{REPORT_VIEW}`",
        "- DB接続: 読み取り専用",
        "- 既存分析ロジック: 相関・回帰・VIF・標準化回帰・予測モデル比較を再利用",
        "",
        "## Web取得・データ鮮度",
        "",
        markdown_table(
            database_freshness,
            ["data_source", "latest", "source"],
            ["データ", "DB最新時点", "取得元"],
            0,
        ),
        "",
    ]

    if acquisition:
        comparisons = acquisition.get("comparisons", {})
        comparison_rows = []
        status_labels = {
            "web_is_newer": "Webが新しいためDB更新",
            "database_is_current": "DBはWeb最新時点と同等以上",
        }
        for source_name, comparison in comparisons.items():
            comparison_rows.append(
                {
                    "source": source_name,
                    "database_max": comparison.get("database_max"),
                    "web_max": comparison.get("web_max"),
                    "status": status_labels.get(
                        comparison.get("status"),
                        comparison.get("status"),
                    ),
                }
            )
        if comparison_rows:
            lines.extend(
                [
                    "### 今回実行時のWeb比較",
                    "",
                    markdown_table(
                        pd.DataFrame(comparison_rows),
                        ["source", "database_max", "web_max", "status"],
                        ["取得対象", "実行前DB", "Web", "判定"],
                        0,
                    ),
                    "",
                ]
            )
        failures = acquisition.get("failures", {})
        if failures:
            failed_sources = "、".join(f"`{key}`" for key in failures)
            lines.extend(
                [
                    "### Web取得状況",
                    "",
                    f"- 一部のWeb取得を完了できませんでした（対象: {failed_sources}）。",
                    "- 詳細なエラー内容は実行ログにのみ保存し、レポート本文には表示していません。",
                    "- 該当データはDBを上書きせず、既存値を使用しました。",
                    "",
                ]
            )
        else:
            lines.extend(["今回のWeb取得で失敗した対象はありません。", ""])

    lines.extend(build_latest_news_section(news_documents, stock_code, stock_name))
    lines.extend(build_news_analysis_section(news_analysis))

    lines.extend(
        [
        "## データ概要",
        "",
        f"- 対象期間: {frame['trade_date'].min():%Y-%m-%d} ～ {frame['trade_date'].max():%Y-%m-%d}",
        f"- VIEW取得行数: {len(frame):,}",
        f"- 統計解析の完全行数: {len(statistical_input):,}",
        f"- 市場: {format_value(latest['market'])}",
        f"- セクター: {format_value(latest['sector'])}",
        "",
        "## AIによる考察",
        "",
        *narrative,
        "",
        "### 上昇要因",
        "",
        *[f"- {factor}" for factor in assessment["positive_factors"]],
        "",
        "### リスク要因",
        "",
        *[f"- {factor}" for factor in assessment["risk_factors"]],
        "",
        "### 総合判断",
        "",
        f"**{assessment['judgment']}**（機械的評価スコア: {assessment['score']:+d}）",
        "",
        "## 最新市場データ",
        "",
        "| 項目 | 値 |",
        "|---|---:|",
        f"| 取引日 | {latest['trade_date']:%Y-%m-%d} |",
        f"| 始値 | {format_value(latest['open_price'], 2)} |",
        f"| 高値 | {format_value(latest['high_price'], 2)} |",
        f"| 安値 | {format_value(latest['low_price'], 2)} |",
        f"| 終値 | {format_value(latest['close_price'], 2)} |",
        f"| 出来高 | {format_value(latest['volume'], 0)} |",
        "",
        "## ファンダメンタル",
        "",
        markdown_table(fundamentals, ["metric", "value"], ["指標", "最新値"], 4),
        "",
        "## 時系列変化",
        "",
        markdown_table(
            period_changes,
            ["period", "base_date", "base_close", "latest_close", "change_pct"],
            ["比較期間", "基準日", "基準終値", "最新終値", "騰落率（%）"],
            2,
        ),
        "",
        "## 財務推移",
        "",
        ]
    )

    if fundamental_history_frame.empty:
        lines.append("財務データが取得できないため、年度比較は生成していません。")
    else:
        lines.extend(
            [
                markdown_table(
                    fundamental_history_display,
                    ["fiscal_year", *FUNDAMENTAL_COLUMNS],
                    [
                        "年度",
                        "sales",
                        "operating_profit",
                        "net_profit",
                        "ROE（%）",
                        "EPS",
                        "PER",
                        "PBR",
                        "配当利回り（%）",
                        "自己資本比率（%）",
                    ],
                    2,
                ),
                "",
                "### 最新年度と前年度の比較",
                "",
                markdown_table(
                    fundamental_changes_display,
                    ["metric", "latest", "previous", "change_pct"],
                    ["指標", "最新年度", "前年度", "変化率（%）"],
                    2,
                ),
            ]
        )

    lines.extend(
        [
        "",
        "## 業界・競合比較",
        "",
        markdown_table(
            peer_comparison_display.sort_values(
                "one_year_change_pct", ascending=False, na_position="last"
            ),
            [
                "stock_code",
                "stock_name",
                "latest_close",
                "one_year_change_pct",
                "roe",
                "per",
                "pbr",
                "dividend_yield",
            ],
            [
                "コード",
                "銘柄",
                "最新終値",
                "1年騰落率（%）",
                "ROE（%）",
                "PER",
                "PBR",
                "配当利回り（%）",
            ],
            2,
        ),
        "",
        "## グラフ",
        "",
        f"![株価推移](assets/{charts['price_history'].name})",
        "",
        f"![業界比較](assets/{charts['peer_performance'].name})",
        "",
        "## データ充足状況",
        "",
        markdown_table(
            availability,
            ["column", "available", "total"],
            ["列", "利用可能行", "総行数"],
            0,
        ),
        "",
        "## 統計分析サマリー",
        "",
        *[f"- {message}" for message in build_interpretation(results)],
        "",
        "## 相関分析",
        "",
        markdown_table(
            results["correlation"].sort_values(
                "correlation", key=lambda series: series.abs(), ascending=False
            ),
            ["indicator", "correlation"],
            ["指標", "相関係数"],
        ),
        "",
        "## 重回帰分析",
        "",
        markdown_table(
            results["regression_summary"],
            ["stock_name", "r2"],
            ["銘柄", "決定係数 R²"],
        ),
        "",
        markdown_table(
            results["regression"],
            ["indicator", "coefficient", "t_value", "p_value"],
            ["指標", "回帰係数", "t値", "p値"],
        ),
        "",
        "## VIF",
        "",
        markdown_table(
            results["vif"].sort_values("vif", ascending=False),
            ["indicator", "vif"],
            ["指標", "VIF"],
        ),
        "",
        "## 標準化回帰係数",
        "",
        markdown_table(
            results["standardized"].sort_values(
                "standardized_coefficient",
                key=lambda series: series.abs(),
                ascending=False,
            ),
            ["indicator", "standardized_coefficient"],
            ["指標", "標準化回帰係数"],
        ),
        "",
        "## 既存予測モデル比較",
        "",
    ]
    )

    if prediction_note:
        lines.append(prediction_note)
    else:
        lines.extend(
            [
                markdown_table(
                    prediction.sort_values(["rmse", "mae"]),
                    [
                        "model_name",
                        "feature",
                        "forecast_target_month",
                        "predicted_close_price",
                        "actual_close_price",
                        "r2",
                        "mae",
                        "rmse",
                    ],
                    [
                        "モデル",
                        "特徴量",
                        "対象月",
                        "予測終値",
                        "実績終値",
                        "R²",
                        "MAE",
                        "RMSE",
                    ],
                ),
                "",
                "予測値は既存モデルによるバックテスト用途の出力であり、将来収益を保証しません。",
            ]
        )

    lines.extend(
        [
            "",
            "## 実行上の制約",
            "",
            "- 生テーブルは参照していません。",
            "- DBへの `INSERT`、`UPDATE`、`DELETE`、DDLは実行していません。",
            "- 既存PythonのDB保存関数は呼び出していません。",
            "- 本レポートは情報提供用であり、投資助言ではありません。",
            "",
        ]
    )
    return "\n".join(lines)


def generate_report(
    stock_code: str,
    db_path: Path,
    output_path: Path | None = None,
    acquisition: dict[str, object] | None = None,
    news_documents: list[Any] | None = None,
    news_analysis: Any | None = None,
) -> Path:
    destination = output_path or (
        DEFAULT_REPORT_DIR / f"stock_report_{stock_code}.html"
    )
    destination = destination.expanduser().resolve()
    if destination.suffix.lower() != ".html":
        raise ValueError("--outputには.htmlファイルを指定してください。")
    frame = load_report_input(db_path, stock_code)
    statistical_input = prepare_statistical_data(frame)
    results = run_existing_statistical_analysis(statistical_input)
    prediction, prediction_note = run_existing_prediction(frame)
    period_changes = calculate_period_changes(frame)
    fundamental_history_frame = fundamental_history(frame)
    fundamental_changes = calculate_fundamental_changes(fundamental_history_frame)
    sector_frame = load_sector_data(db_path, str(frame.iloc[-1]["sector"]))
    peer_comparison = build_peer_comparison(sector_frame)
    chart_directory = destination.parent / "assets"
    charts = generate_charts(
        frame,
        sector_frame,
        chart_directory,
        stock_code,
    )
    assessment = build_factor_assessment(
        period_changes,
        fundamental_changes,
        peer_comparison,
        stock_code,
        results,
    )
    narrative = build_narrative(
        frame,
        period_changes,
        fundamental_history_frame,
        fundamental_changes,
        peer_comparison,
        stock_code,
        results,
        assessment,
    )
    database_freshness = load_database_freshness(db_path, stock_code)
    report = build_report(
        frame,
        statistical_input,
        results,
        prediction,
        prediction_note,
        period_changes,
        fundamental_history_frame,
        fundamental_changes,
        peer_comparison,
        charts,
        assessment,
        narrative,
        database_freshness,
        acquisition,
        news_documents,
        news_analysis,
        db_path,
    )

    destination.parent.mkdir(parents=True, exist_ok=True)
    markdown_path = destination.with_suffix(".md")
    markdown_path.write_text(report, encoding="utf-8")
    title = f"銘柄分析レポート {frame.iloc[-1]['stock_name']}（{stock_code}）"
    html_report = build_self_contained_html(
        report,
        destination.parent,
        title,
    )
    destination.write_text(html_report, encoding="utf-8")
    try:
        upload_report_to_s3(str(destination))
    except Exception as exc:
        print("[WARNING] S3アップロード処理中に予期しないエラーが発生しました")
        print(f"対象: {destination}")
        print(f"理由: {exc}")
    return destination


def main() -> None:
    args = parse_args()
    acquisition = None
    if args.acquisition_log:
        acquisition = json.loads(
            args.acquisition_log.read_text(encoding="utf-8")
        )
    destination = generate_report(
        args.stock_code,
        args.db,
        args.output,
        acquisition,
    )
    print(f"HTMLレポートを生成しました: {destination}")


if __name__ == "__main__":
    main()
