from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PROJECT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPT_DIR))

from generate_stock_report import DEFAULT_DB_PATH, display_database_label


class ReportPublicPathTests(unittest.TestCase):
    def test_default_database_path_is_repo_relative(self) -> None:
        self.assertEqual(
            display_database_label(DEFAULT_DB_PATH),
            "data/market_analysis.db",
        )

    def test_external_database_path_is_generic_label(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "market_analysis.db"
            self.assertEqual(display_database_label(db_path), "SQLite Database")


if __name__ == "__main__":
    unittest.main()
