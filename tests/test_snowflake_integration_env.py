from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from snowflake_connection import SnowflakeConnectionError, snowflake_connection, snowflake_enabled


@unittest.skipUnless(
    os.environ.get("RUN_SNOWFLAKE_INTEGRATION_TESTS") == "true",
    "Set RUN_SNOWFLAKE_INTEGRATION_TESTS=true to run Snowflake live tests.",
)
class SnowflakeLiveConnectionTests(unittest.TestCase):
    def test_current_context_can_be_read(self) -> None:
        self.assertTrue(snowflake_enabled())
        try:
            with snowflake_connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT CURRENT_DATABASE(), CURRENT_SCHEMA(), CURRENT_WAREHOUSE()"
                    )
                    row = cursor.fetchone()
        except SnowflakeConnectionError as exc:
            self.fail(f"Snowflake connection failed safely: {exc.category}")

        self.assertEqual(row[0], "MARKET_ANALYSIS")
        self.assertEqual(row[1], "MART")
        self.assertEqual(row[2], "AI_AGENT_WH")


if __name__ == "__main__":
    unittest.main()
