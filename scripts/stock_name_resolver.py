"""Resolve user-provided stock names, aliases, and partial names."""

from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from db_connection import (
    DatabaseConfigurationError,
    DatabaseConnectionError,
    connect_database,
    get_db_type,
    get_placeholder,
)


@dataclass
class StockCandidate:
    stock_code: str
    stock_name: str
    market: str | None = None
    sector: str | None = None
    match_type: str = ""


class StockNameResolverDatabaseError(RuntimeError):
    """Raised when stock name resolution cannot query the configured DB."""


ALIAS_DICT = {
    "トヨタ": ["トヨタ自動車"],
    "東エレ": ["東京エレクトロン"],
    "東京エレ": ["東京エレクトロン"],
    "アドテスト": ["アドバンテスト"],
    "レーザー": ["レーザーテック"],
    "任天堂": ["任天堂"],
    "NTT": ["NTT"],
    "エヌティーティー": ["NTT"],
    "KDDI": ["KDDI"],
    "ANA": ["ANAホールディングス"],
    "JAL": ["日本航空"],
    "日航": ["日本航空"],
    "ソフトバンク": ["ソフトバンク", "ソフトバンクグループ"],
    "三菱": ["三菱UFJフィナンシャル・グループ", "三菱商事"],
    "三菱UFJ": ["三菱UFJフィナンシャル・グループ"],
    "三菱商事": ["三菱商事"],
    "三井": ["三井物産", "三井住友フィナンシャルグループ"],
    "三井住友": ["三井住友フィナンシャルグループ"],
}


BRAND_DICT = {
    "ユニクロ": ["ファーストリテイリング"],
    "無印": ["良品計画"],
    "ポケモン": ["任天堂"],
}


AMBIGUOUS_ALIAS_FALLBACKS = {
    "ソフトバンク": [
        StockCandidate("9434", "ソフトバンク", "東証プライム", "情報・通信業", "alias_fallback"),
        StockCandidate("9984", "ソフトバンクグループ", "東証プライム", "情報・通信業", "alias_fallback"),
    ],
}


STOP_WORDS = (
    "を",
    "の",
    "は",
    "って",
    "株",
    "株式",
    "分析",
    "比較",
    "買い",
    "売り",
    "教えて",
    "して",
    "ください",
    "どう",
    "どうかな",
)


class StockNameResolver:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)

    def resolve(self, user_input: str) -> list[StockCandidate]:
        keywords = self._keywords(user_input)
        if not keywords:
            return []

        candidates: list[StockCandidate] = []
        connection = self._connect_read_only()
        try:
            for keyword in keywords:
                candidates = self._search_by_code(connection, keyword)
                if candidates:
                    return candidates

            for keyword in keywords:
                candidates += self._search_by_exact_name(connection, keyword)
            if candidates:
                return self._with_ambiguous_alias_fallbacks(keywords, candidates)

            for keyword in keywords:
                for name in ALIAS_DICT.get(keyword, []):
                    candidates += self._search_by_exact_name(connection, name, "alias")
            if candidates:
                return self._with_ambiguous_alias_fallbacks(keywords, candidates)

            for keyword in keywords:
                for name in BRAND_DICT.get(keyword, []):
                    candidates += self._search_by_exact_name(connection, name, "brand")
            if candidates:
                return self._deduplicate(candidates)

            for keyword in keywords:
                candidates += self._search_by_partial_name(connection, keyword)
        finally:
            close = getattr(connection, "close", None)
            if callable(close):
                close()

        return self._deduplicate(candidates)

    def _with_ambiguous_alias_fallbacks(
        self,
        keywords: list[str],
        candidates: list[StockCandidate],
    ) -> list[StockCandidate]:
        combined = self._deduplicate(candidates)
        for keyword in keywords:
            fallbacks = AMBIGUOUS_ALIAS_FALLBACKS.get(keyword)
            if not fallbacks:
                continue
            known_codes = {candidate.stock_code for candidate in combined}
            for fallback in fallbacks:
                if fallback.stock_code not in known_codes:
                    combined.append(fallback)
                    known_codes.add(fallback.stock_code)
        return combined

    def _connect_read_only(self) -> Any:
        db_type = self._db_type()
        env = None
        if db_type == "sqlite":
            env = dict(os.environ)
            env["DB_TYPE"] = "sqlite"
            env["SQLITE_DB_PATH"] = str(self.db_path)
        return connect_database(read_only=True, env=env)

    def _db_type(self) -> str:
        if self.db_path.exists():
            return "sqlite"
        return get_db_type()

    def _keywords(self, user_input: str) -> list[str]:
        text = str(user_input or "").strip()
        if not text:
            return []

        code_matches = re.findall(r"(?<!\d)(\d{4})(?!\d)", text)
        if code_matches:
            return code_matches

        cleaned = text
        for word in STOP_WORDS:
            cleaned = cleaned.replace(word, " ")
        raw_terms = re.split(r"[\s、。,.・/／（）()]+", cleaned)
        terms = [term.strip() for term in raw_terms if len(term.strip()) >= 2]

        # Try the original compact text first so aliases like "三菱UFJ" survive.
        compact = cleaned.replace(" ", "").strip()
        ordered = []
        for term in [compact, *terms]:
            if term and term not in ordered:
                ordered.append(term)
        return ordered

    def _search_by_code(self, connection: Any, keyword: str) -> list[StockCandidate]:
        placeholder = get_placeholder(self._db_type())
        return self._fetch(
            connection,
            f"""
            SELECT stock_code, stock_name, market, sector
            FROM v_agent_stock_master
            WHERE stock_code = {placeholder}
            """,
            (keyword,),
            "code_exact",
        )

    def _search_by_exact_name(
        self,
        connection: Any,
        keyword: str,
        match_type: str = "name_exact",
    ) -> list[StockCandidate]:
        placeholder = get_placeholder(self._db_type())
        return self._fetch(
            connection,
            f"""
            SELECT stock_code, stock_name, market, sector
            FROM v_agent_stock_master
            WHERE stock_name = {placeholder}
            """,
            (keyword,),
            match_type,
        )

    def _search_by_partial_name(
        self,
        connection: Any,
        keyword: str,
    ) -> list[StockCandidate]:
        placeholder = get_placeholder(self._db_type())
        return self._fetch(
            connection,
            f"""
            SELECT stock_code, stock_name, market, sector
            FROM v_agent_stock_master
            WHERE stock_name LIKE {placeholder}
            ORDER BY stock_code
            LIMIT 10
            """,
            (f"%{keyword}%",),
            "name_partial",
        )

    def _fetch(
        self,
        connection: Any,
        sql: str,
        params: tuple[object, ...],
        match_type: str,
    ) -> list[StockCandidate]:
        try:
            rows = self._fetch_dicts(connection, sql, params)
        except (DatabaseConfigurationError, DatabaseConnectionError):
            raise
        except Exception as exc:
            raise StockNameResolverDatabaseError(
                "Failed to resolve stock names from the configured database."
            ) from None
        return [
            StockCandidate(
                stock_code=str(row["stock_code"]),
                stock_name=str(row["stock_name"]),
                market=row["market"],
                sector=row["sector"],
                match_type=match_type,
            )
            for row in rows
        ]

    def _fetch_dicts(
        self,
        connection: Any,
        sql: str,
        params: tuple[object, ...],
    ) -> list[dict[str, Any]]:
        db_type = "sqlite" if isinstance(connection, sqlite3.Connection) else "postgres"
        if db_type == "sqlite":
            cursor = connection.execute(sql, params)
            columns = [description[0] for description in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

        with connection.cursor() as cursor:
            cursor.execute(sql, params)
            columns = [description[0] for description in cursor.description]
            return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def _deduplicate(self, candidates: list[StockCandidate]) -> list[StockCandidate]:
        seen: set[str] = set()
        unique: list[StockCandidate] = []
        for candidate in candidates:
            if candidate.stock_code in seen:
                continue
            seen.add(candidate.stock_code)
            unique.append(candidate)
        return unique
