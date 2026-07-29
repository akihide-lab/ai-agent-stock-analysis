from __future__ import annotations

import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from news_analysis import build_news_analysis
from query_flow_models import NewsDocument


class NewsAnalysisTests(unittest.TestCase):
    def test_no_news_returns_none(self) -> None:
        self.assertIsNone(build_news_analysis([]))

    def test_builds_conservative_analysis_from_news(self) -> None:
        analysis = build_news_analysis(
            [
                NewsDocument(
                    stock_code="7203",
                    title="Toyota expands production",
                    body="新型車の需要に対応するため生産を拡大する。",
                    url="https://news.example.jp/toyota",
                    source="Public News",
                )
            ]
        )

        self.assertIsNotNone(analysis)
        self.assertEqual(analysis.source_count, 1)
        self.assertTrue(analysis.positive_factors)
        self.assertIn("断定するものではありません", analysis.uncertainty)

    def test_sample_news_is_excluded_from_analysis(self) -> None:
        analysis = build_news_analysis(
            [
                NewsDocument(
                    stock_code="7203",
                    title="Sample title",
                    body="拡大",
                    url="https://example.com/news/toyota-001",
                    source="sample_news",
                )
            ]
        )

        self.assertIsNone(analysis)


if __name__ == "__main__":
    unittest.main()
