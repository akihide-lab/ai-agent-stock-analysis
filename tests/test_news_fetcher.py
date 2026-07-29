from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import news_fetcher


class FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return b"""<?xml version="1.0" encoding="UTF-8"?>
<rss><channel>
<item>
<title>Toyota expands production</title>
<link>https://news.example.jp/toyota</link>
<pubDate>Wed, 29 Jul 2026 09:00:00 GMT</pubDate>
<source>Public News</source>
<description>Toyota announced production expansion.</description>
</item>
</channel></rss>"""


class NewsFetcherTests(unittest.TestCase):
    def test_disabled_by_default(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(news_fetcher.news_fetch_enabled())

    def test_fetch_news_for_stock_normalizes_rss_items(self) -> None:
        with patch.object(news_fetcher.urllib.request, "urlopen", return_value=FakeResponse()):
            result = news_fetcher.fetch_news_for_stock("7203", "Toyota", limit=1)

        self.assertEqual(result.warnings, [])
        self.assertEqual(len(result.news_items), 1)
        self.assertEqual(result.news_items[0]["stock_code"], "7203")
        self.assertEqual(result.news_items[0]["source"], "Public News")

    def test_fetch_failure_returns_warning_and_empty_items(self) -> None:
        with patch.object(news_fetcher.urllib.request, "urlopen", side_effect=OSError("offline")):
            result = news_fetcher.fetch_news_for_stock("7203", "Toyota", limit=1)

        self.assertEqual(result.news_items, [])
        self.assertTrue(result.warnings)


if __name__ == "__main__":
    unittest.main()
