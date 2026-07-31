from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from generate_stock_report import (
    build_latest_news_section,
    build_news_analysis_section,
    build_snowflake_analysis_section,
)
from query_flow_models import NewsAnalysis
from query_flow_models import NewsDocument


class LatestNewsReportSectionTests(unittest.TestCase):
    def test_empty_news_shows_public_empty_message(self) -> None:
        section = "\n".join(build_latest_news_section([], "7203", "Toyota"))

        self.assertIn("## 最新ニュース", section)
        self.assertIn("現在、関連ニュースはありません。", section)
        self.assertNotIn("MongoDB", section)

    def test_sample_news_is_not_displayed(self) -> None:
        section = "\n".join(
            build_latest_news_section(
                [
                    NewsDocument(
                        stock_code="7203",
                        company_name="Toyota",
                        title="Sample title",
                        body="Sample body",
                        url="https://example.com/news/toyota-001",
                        source="sample_news",
                    )
                ],
                "7203",
                "Toyota",
            )
        )

        self.assertIn("現在、関連ニュースはありません。", section)
        self.assertNotIn("Sample title", section)
        self.assertNotIn("sample_news", section)
        self.assertNotIn("example.com", section)
        self.assertNotIn("MongoDB", section)

    def test_public_news_is_displayed_without_internal_storage_name(self) -> None:
        section = "\n".join(
            build_latest_news_section(
                [
                    {
                        "stock_code": "7203",
                        "company_name": "Toyota",
                        "title": "Production update",
                        "body": "Toyota announced a production update.",
                        "url": "https://news.example.jp/toyota",
                        "source": "public_news",
                        "published_at": "2026-07-29",
                    }
                ],
                "7203",
                "Toyota",
            )
        )

        self.assertIn("## 最新ニュース", section)
        self.assertIn("Production update", section)
        self.assertIn("- 概要: Toyota announced a production update.", section)
        self.assertIn("public_news", section)
        self.assertNotIn("MongoDB", section)

    def test_missing_news_analysis_has_clear_message(self) -> None:
        section = "\n".join(build_news_analysis_section(None))

        self.assertIn("## ニュースから見た注目ポイント", section)
        self.assertIn("ニュースが取得できなかったため", section)
        self.assertNotIn("MongoDB", section)

    def test_news_analysis_is_displayed_separately(self) -> None:
        section = "\n".join(
            build_news_analysis_section(
                NewsAnalysis(
                    summary="ニュース要約",
                    positive_factors=["プラス材料"],
                    negative_factors=["注意材料"],
                    short_term_impact="短期影響",
                    medium_long_term_impact="中長期影響",
                    uncertainty="不確実性",
                    source_count=1,
                )
            )
        )

        self.assertIn("ニュース要約", section)
        self.assertIn("プラス材料", section)
        self.assertIn("注意材料", section)
        self.assertNotIn("MongoDB", section)

    def test_snowflake_section_is_hidden_without_rows(self) -> None:
        self.assertEqual(build_snowflake_analysis_section({"rows": []}), [])

    def test_snowflake_section_displays_mart_rows(self) -> None:
        section = "\n".join(
            build_snowflake_analysis_section(
                {
                    "rows": [
                        {
                            "stock_code": "9202",
                            "trade_date": "2026-07-01",
                            "close_price": 100,
                            "volume": 1000,
                            "sales": 10000,
                            "usd_jpy": 160,
                            "nikkei_close": 40000,
                        },
                        {
                            "stock_code": "9202",
                            "trade_date": "2026-07-02",
                            "close_price": 110,
                            "volume": 1200,
                            "sales": 10000,
                            "usd_jpy": 161,
                            "nikkei_close": 40100,
                        },
                    ]
                }
            )
        )

        self.assertIn("## Snowflake分析基盤による集計", section)
        self.assertIn("期間変化率", section)
        self.assertIn("データ件数", section)


if __name__ == "__main__":
    unittest.main()
