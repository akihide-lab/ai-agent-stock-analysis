from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PROJECT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

import question_agent
import stock_domain_router


def make_stock_db(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute(
            """
            CREATE TABLE v_agent_stock_master (
                stock_code TEXT,
                stock_name TEXT,
                market TEXT,
                sector TEXT
            )
            """
        )
        connection.executemany(
            """
            INSERT INTO v_agent_stock_master
                (stock_code, stock_name, market, sector)
            VALUES (?, ?, ?, ?)
            """,
            [
                ("7203", "トヨタ自動車", "東証プライム", "輸送用機器"),
                ("9983", "ファーストリテイリング", "東証プライム", "小売業"),
                ("9434", "ソフトバンク株式会社", "東証プライム", "情報・通信業"),
                ("9984", "ソフトバンクグループ株式会社", "東証プライム", "情報・通信業"),
            ],
        )


def make_master_frame() -> pd.DataFrame:
    rows = [
        {
            "stock_code": "7203",
            "stock_name": "トヨタ自動車",
            "sector": "輸送用機器",
        },
        {
            "stock_code": "9983",
            "stock_name": "ファーストリテイリング",
            "sector": "小売業",
        },
        {
            "stock_code": "9434",
            "stock_name": "ソフトバンク株式会社",
            "sector": "情報・通信業",
        },
        {
            "stock_code": "9984",
            "stock_name": "ソフトバンクグループ株式会社",
            "sector": "情報・通信業",
        },
    ]
    frame = pd.DataFrame(rows)
    frame["name_norm"] = frame["stock_name"].map(question_agent.normalize_text)
    return frame


class UncertainQuestionFlowTest(unittest.TestCase):
    def test_ambiguous_intent_stops_before_db(self) -> None:
        result = question_agent.classify_pre_db("トヨタどう？")
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "ambiguous")
        self.assertGreaterEqual(len(result.intent_candidates), 2)

    def test_stock_domain_detects_stock_keywords(self) -> None:
        result = stock_domain_router.classify("おすすめの株教えて")
        self.assertEqual(result.domain, "stock")

    def test_stock_domain_detects_brand_name(self) -> None:
        result = stock_domain_router.classify("ユニクロの株教えて")
        self.assertEqual(result.domain, "stock")

    def test_general_domain_does_not_enter_stock_flow(self) -> None:
        result = stock_domain_router.classify("今日の天気を教えて")
        self.assertEqual(result.domain, "general")

    def test_low_information_input_is_unknown(self) -> None:
        result = stock_domain_router.classify("ああああああああ")
        self.assertEqual(result.domain, "unknown")

    def test_insufficient_search_conditions_stop_before_db(self) -> None:
        domain = stock_domain_router.classify("良さそうな株を探して")
        result = question_agent.classify_pre_db("良さそうな株を探して", domain)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "insufficient")
        self.assertIn("投資目的", result.missing_fields)

    def test_user_recommendation_phrase_stops_before_db(self) -> None:
        domain = stock_domain_router.classify("オススメの株をおしえて")
        result = question_agent.classify_pre_db("オススメの株をおしえて", domain)
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "insufficient")
        self.assertIn("投資目的", result.missing_fields)

    def test_stock_brand_continues_to_name_resolution(self) -> None:
        domain = stock_domain_router.classify("ユニクロの株教えて")
        result = question_agent.classify_pre_db("ユニクロの株教えて", domain)
        self.assertIsNone(result)

    def test_gibberish_is_not_forced_to_search(self) -> None:
        result = question_agent.classify_pre_db("ああああああああ")
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "unsupported")

    def test_unsupported_request_is_not_forced_to_existing_intent(self) -> None:
        result = question_agent.classify_pre_db("メールでこの分析を送信して")
        self.assertIsNotNone(result)
        self.assertEqual(result.status, "unsupported")

    def test_clear_stock_code_is_classified(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "stocks.db"
            make_stock_db(db_path)

            result, candidates, _ = question_agent.classify_with_db(
                "7203を分析して",
                db_path,
                make_master_frame(),
            )

        self.assertEqual(result.status, "classified")
        self.assertEqual(result.intent, "Intent008 単一銘柄分析")
        self.assertEqual(candidates[0].stock_code, "7203")

    def test_brand_name_is_resolved_to_listed_company(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "stocks.db"
            make_stock_db(db_path)

            result, candidates, _ = question_agent.classify_with_db(
                "ユニクロの株教えて",
                db_path,
                make_master_frame(),
            )

        self.assertEqual(result.status, "classified")
        self.assertEqual(result.intent, "Intent008 単一銘柄分析")
        self.assertEqual(candidates[0].stock_code, "9983")

    def test_multiple_stock_candidates_are_ambiguous(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "stocks.db"
            make_stock_db(db_path)

            result, candidates, _ = question_agent.classify_with_db(
                "ソフトバンクを分析して",
                db_path,
                make_master_frame(),
            )

        self.assertEqual(result.status, "ambiguous")
        self.assertEqual({candidate.stock_code for candidate in candidates}, {"9434", "9984"})

    def test_unknown_stock_is_insufficient_not_guessed(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            db_path = Path(temp_dir) / "stocks.db"
            make_stock_db(db_path)

            result, candidates, _ = question_agent.classify_with_db(
                "存在しない銘柄名を分析して",
                db_path,
                make_master_frame(),
            )

        self.assertEqual(result.status, "insufficient")
        self.assertEqual(candidates, [])
        self.assertIn("銘柄", result.missing_fields)

    def test_stock_resolver_exception_becomes_system_error(self) -> None:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as temp_dir:
            original_log_directory = question_agent.LOG_DIRECTORY
            question_agent.LOG_DIRECTORY = Path(temp_dir)
            try:
                result, _, _ = question_agent.classify_with_db(
                    "7203を分析して",
                    Path("missing.db"),
                    make_master_frame(),
                )
            finally:
                question_agent.LOG_DIRECTORY = original_log_directory
        self.assertEqual(result.status, "system_error")
        self.assertIsNotNone(result.error_code)

    def test_confidence_thresholds(self) -> None:
        self.assertEqual(question_agent.classify_confidence(0.49), "insufficient")
        self.assertEqual(question_agent.classify_confidence(0.50), "ambiguous")
        self.assertEqual(question_agent.classify_confidence(0.79), "ambiguous")
        self.assertEqual(question_agent.classify_confidence(0.80), "classified")


if __name__ == "__main__":
    unittest.main()
