from __future__ import annotations

import sqlite3
import sys
import tempfile
import types
import unittest
from contextlib import closing
from pathlib import Path
from unittest import mock


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import db_connection


class DbConnectionTests(unittest.TestCase):
    def test_sqlite_connection_smoke_test(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "market_analysis.db"
            with closing(sqlite3.connect(db_path)) as connection:
                connection.execute("CREATE TABLE sample (id INTEGER)")
                connection.commit()

            result = db_connection.smoke_test_connection(
                {
                    "DB_TYPE": "sqlite",
                    "SQLITE_DB_PATH": str(db_path),
                }
            )

        self.assertEqual(result["db_type"], "sqlite")
        self.assertTrue(result["ok"])
        self.assertEqual(result["result"], 1)

    def test_invalid_db_type_raises_clear_error(self) -> None:
        with self.assertRaisesRegex(
            db_connection.DatabaseConfigurationError,
            "Unsupported DB_TYPE",
        ):
            db_connection.get_db_type({"DB_TYPE": "mysql"})

    def test_postgres_missing_env_raises_safe_error(self) -> None:
        env = {
            "DB_TYPE": "postgres",
            "POSTGRES_PASSWORD": "super-secret-password",
        }

        with self.assertRaises(db_connection.DatabaseConfigurationError) as context:
            db_connection.connect_database(env=env)

        message = str(context.exception)
        self.assertIn("Missing required PostgreSQL environment variables", message)
        self.assertIn("POSTGRES_HOST", message)
        self.assertNotIn("super-secret-password", message)
        self.assertNotIn("postgres://", message)

    def test_postgres_connection_error_hides_driver_details(self) -> None:
        secret = "super-secret-password"
        endpoint = "example-rds-endpoint"

        def fail_connect(**_: object) -> object:
            raise RuntimeError(f"could not connect to {endpoint} with {secret}")

        fake_psycopg = types.SimpleNamespace(connect=fail_connect)
        env = {
            "DB_TYPE": "postgres",
            "POSTGRES_HOST": endpoint,
            "POSTGRES_DB": "market_analysis",
            "POSTGRES_USER": "user",
            "POSTGRES_PASSWORD": secret,
        }

        previous = sys.modules.get("psycopg")
        sys.modules["psycopg"] = fake_psycopg
        try:
            with self.assertRaises(db_connection.DatabaseConnectionError) as context:
                db_connection.connect_database(env=env)
        finally:
            if previous is None:
                sys.modules.pop("psycopg", None)
            else:
                sys.modules["psycopg"] = previous

        message = str(context.exception)
        self.assertEqual(message, "Failed to connect to PostgreSQL database.")
        self.assertIsNone(context.exception.__cause__)
        self.assertEqual(
            context.exception.diagnostics["category"],
            "unknown_connection_error",
        )
        self.assertNotIn(secret, message)
        self.assertNotIn(endpoint, message)

    def test_postgres_connection_error_writes_safe_diagnostics(self) -> None:
        secret = "super-secret-password"
        endpoint = "example-rds-endpoint"

        def fail_connect(**_: object) -> object:
            raise RuntimeError(
                f'connection to server at "{endpoint}" failed: '
                f"Permission denied (0x0000271D/10013) using {secret}"
            )

        fake_psycopg = types.SimpleNamespace(connect=fail_connect)
        env = {
            "DB_TYPE": "postgres",
            "POSTGRES_HOST": endpoint,
            "POSTGRES_DB": "market_analysis",
            "POSTGRES_USER": "user",
            "POSTGRES_PASSWORD": secret,
        }

        previous = sys.modules.get("psycopg")
        sys.modules["psycopg"] = fake_psycopg
        with tempfile.TemporaryDirectory() as temp_dir:
            try:
                with mock.patch.object(db_connection, "LOG_DIRECTORY", Path(temp_dir)):
                    with self.assertRaises(db_connection.DatabaseConnectionError) as context:
                        db_connection.connect_database(env=env)
            finally:
                if previous is None:
                    sys.modules.pop("psycopg", None)
                else:
                    sys.modules["psycopg"] = previous

            error = context.exception
            self.assertEqual(error.diagnostics["db_type"], "postgres")
            self.assertEqual(error.diagnostics["stage"], "postgres_connect")
            self.assertEqual(error.diagnostics["exception_type"], "RuntimeError")
            self.assertEqual(error.diagnostics["category"], "network_permission_denied")
            self.assertIn("ネットワーク", error.user_message)
            self.assertIsNotNone(error.diagnostic_log_path)

            log_text = Path(error.diagnostic_log_path).read_text(encoding="utf-8")

        self.assertIn("network_permission_denied", log_text)
        self.assertIn("postgres_connect", log_text)
        self.assertNotIn(secret, log_text)
        self.assertNotIn(endpoint, log_text)
        self.assertNotIn("POSTGRES_PASSWORD", log_text)
        self.assertNotIn("PGPASSWORD", log_text)

    def test_connection_error_category_examples(self) -> None:
        examples = {
            "Permission denied (10013)": "network_permission_denied",
            "connection timed out": "connection_timeout",
            "password authentication failed for user": "authentication_failed",
            "database does not exist": "database_not_found",
            "could not translate host name": "host_resolution_failed",
            "sslmode value is invalid": "ssl_error",
            "unexpected failure": "unknown_connection_error",
        }

        for message, expected in examples.items():
            with self.subTest(message=message):
                self.assertEqual(
                    db_connection._safe_connection_error_category(RuntimeError(message)),
                    expected,
                )

    def test_placeholder_by_db_type(self) -> None:
        self.assertEqual(db_connection.get_placeholder("sqlite"), "?")
        self.assertEqual(db_connection.get_placeholder("postgres"), "%s")


if __name__ == "__main__":
    unittest.main()
