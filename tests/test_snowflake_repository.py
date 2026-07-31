from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from snowflake_connection import (
    SnowflakeConfigurationError,
    get_snowflake_settings,
    snowflake_enabled,
)
from snowflake_repository import fetch_stock_analysis_context


class SnowflakeRepositoryTests(unittest.TestCase):
    def test_disabled_snowflake_does_not_connect(self) -> None:
        with patch("snowflake_connection._load_env_files", return_value={}):
            with patch.dict("os.environ", {"SNOWFLAKE_ENABLED": "false"}, clear=True):
                result = fetch_stock_analysis_context("9202")

        self.assertEqual(result["rows"], [])
        self.assertFalse(result["metadata"]["available"])
        self.assertEqual(result["warnings"], [])

    def test_clean_env_value_removes_inline_operator_notes(self) -> None:
        from snowflake_connection import _clean_env_value

        self.assertEqual(_clean_env_value("MARKET_ANALYSIS ←基本そのまま"), "MARKET_ANALYSIS")
        self.assertEqual(_clean_env_value("AI_AGENT_WH # warehouse"), "AI_AGENT_WH")

    def test_settings_do_not_require_credentials_when_disabled(self) -> None:
        with patch("snowflake_connection._load_env_files", return_value={}):
            with patch.dict("os.environ", {"SNOWFLAKE_ENABLED": "false"}, clear=True):
                settings = get_snowflake_settings()

        self.assertFalse(settings.enabled)
        with patch("snowflake_connection._load_env_files", return_value={}):
            with patch.dict("os.environ", {"SNOWFLAKE_ENABLED": "false"}, clear=True):
                self.assertFalse(snowflake_enabled())

    def test_accountadmin_role_is_rejected(self) -> None:
        env = {
            "SNOWFLAKE_ENABLED": "true",
            "SNOWFLAKE_ACCOUNT": "account",
            "SNOWFLAKE_USER": "user",
            "SNOWFLAKE_PASSWORD": "password",
            "SNOWFLAKE_WAREHOUSE": "AI_AGENT_WH",
            "SNOWFLAKE_DATABASE": "MARKET_ANALYSIS",
            "SNOWFLAKE_SCHEMA": "MART",
            "SNOWFLAKE_ROLE": "ACCOUNTADMIN",
        }

        with self.assertRaises(SnowflakeConfigurationError):
            get_snowflake_settings(env)

    def test_accountadmin_role_can_be_allowed_for_initial_setup(self) -> None:
        env = {
            "SNOWFLAKE_ENABLED": "true",
            "SNOWFLAKE_ACCOUNT": "account",
            "SNOWFLAKE_USER": "user",
            "SNOWFLAKE_PASSWORD": "password",
            "SNOWFLAKE_WAREHOUSE": "AI_AGENT_WH",
            "SNOWFLAKE_DATABASE": "MARKET_ANALYSIS",
            "SNOWFLAKE_SCHEMA": "MART",
            "SNOWFLAKE_ROLE": "ACCOUNTADMIN",
            "SNOWFLAKE_ALLOW_ACCOUNTADMIN_SETUP": "true",
        }

        self.assertTrue(get_snowflake_settings(env).allow_accountadmin_setup)


if __name__ == "__main__":
    unittest.main()
