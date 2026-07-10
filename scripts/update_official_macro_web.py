"""Update selected Japanese macro series from official Web sources."""

from __future__ import annotations

import argparse
import io
import json
import os
import re
import shutil
import sqlite3
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import requests
from bs4 import BeautifulSoup


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = PROJECT_ROOT / "data" / "market_analysis.db"
CPI_URL = "https://www.stat.go.jp/data/cpi/sokuhou/tsuki/index-z.html"
BOJ_URL = "https://www.stat-search.boj.or.jp/ssi/mtshtml/fm02_m_1.html"
JGB_URL = "https://www.mof.go.jp/jgbs/reference/interest_rate/data/jgbcm_all.csv"
USER_AGENT = "stock-analysis-local-agent/1.0"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="公式WebからCPI・政策金利・日本10年金利を更新します。"
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    return parser.parse_args()


def get(url: str) -> requests.Response:
    response = requests.get(
        url,
        timeout=45,
        headers={"User-Agent": USER_AGENT},
    )
    response.raise_for_status()
    return response


def fetch_latest_cpi() -> tuple[str, float]:
    response = get(CPI_URL)
    text = response.content.decode(response.apparent_encoding or "cp932", "replace")
    plain = " ".join(BeautifulSoup(text, "html.parser").get_text(" ", strip=True).split())
    period_match = re.search(r"([0-9]{4})年（[^）]+）([0-9]{1,2})月分", plain)
    index_match = re.search(
        r"総合指数\s*は2020年を100として([0-9]+(?:\.[0-9]+)?)",
        plain,
    )
    if not period_match or not index_match:
        raise RuntimeError("統計局ページからCPI最新値を抽出できませんでした")
    year, month = int(period_match.group(1)), int(period_match.group(2))
    return f"{year:04d}-{month:02d}", float(index_match.group(1))


def fetch_policy_rates() -> list[tuple[str, float]]:
    response = get(BOJ_URL)
    text = response.content.decode("cp932", "replace")
    soup = BeautifulSoup(text, "html.parser")
    rows: list[tuple[str, float]] = []
    for table_row in soup.find_all("tr"):
        cells = [
            " ".join(cell.get_text(" ", strip=True).split())
            for cell in table_row.find_all(["th", "td"])
        ]
        if len(cells) < 2 or not re.fullmatch(r"20[0-9]{2}/[0-9]{2}", cells[0]):
            continue
        try:
            rows.append((cells[0].replace("/", "-"), float(cells[1])))
        except ValueError:
            continue
    if not rows:
        raise RuntimeError("日本銀行ページから政策金利系列を抽出できませんでした")
    return rows


def japanese_era_to_iso(value: Any) -> str | None:
    text = str(value).strip()
    match = re.fullmatch(r"([RHS])([0-9]+)\.([0-9]+)\.([0-9]+)", text)
    if not match:
        return None
    era, year_text, month_text, day_text = match.groups()
    offsets = {"R": 2018, "H": 1988, "S": 1925}
    year = offsets[era] + int(year_text)
    return f"{year:04d}-{int(month_text):02d}-{int(day_text):02d}"


def fetch_jgb_10y() -> list[tuple[str, float]]:
    response = get(JGB_URL)
    frame = pd.read_csv(
        io.BytesIO(response.content),
        encoding="cp932",
        header=1,
    )
    if "基準日" not in frame or "10年" not in frame:
        raise RuntimeError("財務省CSVに基準日または10年列がありません")
    selected = frame[["基準日", "10年"]].copy()
    selected["date"] = selected["基準日"].map(japanese_era_to_iso)
    selected["jgb_10y_yield"] = pd.to_numeric(selected["10年"], errors="coerce")
    selected = selected.dropna(subset=["date", "jgb_10y_yield"])
    rows = list(selected[["date", "jgb_10y_yield"]].itertuples(index=False, name=None))
    if not rows:
        raise RuntimeError("財務省CSVから10年金利を抽出できませんでした")
    return [(str(date), float(value)) for date, value in rows]


def update_staging(
    connection: sqlite3.Connection,
    cpi: tuple[str, float],
    policy_rates: list[tuple[str, float]],
    jgb_rows: list[tuple[str, float]],
) -> dict[str, dict[str, Any]]:
    comparisons: dict[str, dict[str, Any]] = {}

    cpi_period, cpi_index = cpi
    cpi_db_max = connection.execute("SELECT MAX(year_month) FROM cpi").fetchone()[0]
    cpi_updated = cpi_db_max is None or cpi_period > str(cpi_db_max)
    if cpi_db_max is None or cpi_period >= str(cpi_db_max):
        connection.execute(
            "INSERT INTO cpi (year_month, cpi_index, cpi_mom) VALUES (?, ?, ?) "
            "ON CONFLICT(year_month) DO UPDATE SET "
            "cpi_index=excluded.cpi_index, cpi_mom=excluded.cpi_mom",
            (cpi_period, cpi_index, None),
        )
    comparisons["official:cpi"] = {
        "database_max": cpi_db_max,
        "web_max": cpi_period,
        "updated": cpi_updated,
        "status": "web_is_newer" if cpi_updated else "database_is_current",
        "url": CPI_URL,
        "note": "公式概要から前月比を直接取得できないためcpi_momはNULL",
    }

    policy_db_max = connection.execute(
        "SELECT MAX(year_month) FROM policy_rate"
    ).fetchone()[0]
    policy_web_max = max(row[0] for row in policy_rates)
    policy_updated = policy_db_max is None or policy_web_max > str(policy_db_max)
    if policy_updated:
        connection.executemany(
            "INSERT INTO policy_rate (year_month, policy_rate) VALUES (?, ?) "
            "ON CONFLICT(year_month) DO UPDATE SET policy_rate=excluded.policy_rate",
            policy_rates,
        )
    comparisons["official:policy_rate"] = {
        "database_max": policy_db_max,
        "web_max": policy_web_max,
        "updated": policy_updated,
        "status": "web_is_newer" if policy_updated else "database_is_current",
        "url": BOJ_URL,
    }

    jgb_db_max = connection.execute(
        "SELECT MAX(date) FROM interest_rate_long"
    ).fetchone()[0]
    jgb_web_max = max(row[0] for row in jgb_rows)
    jgb_updated = jgb_db_max is None or jgb_web_max > str(jgb_db_max)
    if jgb_updated:
        connection.executemany(
            "INSERT INTO interest_rate_long (date, jgb_10y_yield) VALUES (?, ?) "
            "ON CONFLICT(date) DO UPDATE SET "
            "jgb_10y_yield=excluded.jgb_10y_yield",
            jgb_rows,
        )
    comparisons["official:jgb_10y"] = {
        "database_max": jgb_db_max,
        "web_max": jgb_web_max,
        "updated": jgb_updated,
        "status": "web_is_newer" if jgb_updated else "database_is_current",
        "url": JGB_URL,
    }
    return comparisons


def main() -> None:
    args = parse_args()
    database = args.db.expanduser().resolve(strict=True)
    timestamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    staging = database.with_name(f"{database.stem}.official_{timestamp}.db")
    backup_directory = database.parent / "backups"
    backup_directory.mkdir(exist_ok=True)
    backup = backup_directory / f"{database.stem}_before_official_{timestamp}.db"

    cpi = fetch_latest_cpi()
    policy_rates = fetch_policy_rates()
    jgb_rows = fetch_jgb_10y()
    shutil.copy2(database, staging)
    try:
        with closing(sqlite3.connect(staging)) as connection:
            connection.execute("BEGIN")
            comparisons = update_staging(connection, cpi, policy_rates, jgb_rows)
            connection.commit()
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise RuntimeError("SQLite quick_checkに失敗しました")
        shutil.copy2(database, backup)
        os.replace(staging, database)
    except Exception:
        if staging.exists():
            staging.unlink()
        raise

    summary = {
        "updated_at": datetime.now().astimezone().isoformat(),
        "database": str(database),
        "backup": str(backup),
        "comparisons": comparisons,
        "failures": {},
    }
    log_path = PROJECT_ROOT / "logs" / f"official_macro_update_{timestamp}.json"
    log_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"更新ログ: {log_path}")


if __name__ == "__main__":
    main()
