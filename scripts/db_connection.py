"""Common database connection helpers for SQLite and PostgreSQL.

The existing application still calls SQLite directly. This module is the
shared connection layer that later steps can adopt incrementally.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SQLITE_DB_PATH = PROJECT_ROOT / "data" / "market_analysis.db"
SUPPORTED_DB_TYPES = {"sqlite", "postgres"}
ENV_FILES = (
    PROJECT_ROOT / ".env",
    PROJECT_ROOT / "config" / ".env",
    PROJECT_ROOT / "Config" / ".env",
)


class DatabaseConfigurationError(RuntimeError):
    """Raised when database environment variables are missing or invalid."""


class DatabaseConnectionError(RuntimeError):
    """Raised when a database connection cannot be created safely."""


def _load_env_files() -> None:
    for path in ENV_FILES:
        if not path.is_file():
            continue
        try:
            for raw_line in path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
        except OSError as exc:
            raise DatabaseConfigurationError(
                "Failed to read database environment configuration."
            ) from exc


def _env_value(name: str, env: Mapping[str, str] | None = None) -> str:
    if env is None:
        _load_env_files()
    source = os.environ if env is None else env
    return str(source.get(name, "")).strip()


def _first_env_value(
    names: tuple[str, ...],
    env: Mapping[str, str] | None = None,
) -> str:
    for name in names:
        value = _env_value(name, env)
        if value:
            return value
    return ""


def get_db_type(env: Mapping[str, str] | None = None) -> str:
    """Return the configured database type.

    Defaults to SQLite to preserve the current local behavior.
    """

    db_type = (_env_value("DB_TYPE", env) or "sqlite").lower()
    if db_type not in SUPPORTED_DB_TYPES:
        raise DatabaseConfigurationError(
            f"Unsupported DB_TYPE '{db_type}'. Expected one of: postgres, sqlite."
        )
    return db_type


def get_sqlite_db_path(env: Mapping[str, str] | None = None) -> Path:
    """Return the SQLite database path from SQLITE_DB_PATH or the default."""

    configured = _env_value("SQLITE_DB_PATH", env)
    if not configured:
        return DEFAULT_SQLITE_DB_PATH
    path = Path(configured).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


def connect_sqlite(
    *,
    read_only: bool = True,
    env: Mapping[str, str] | None = None,
) -> sqlite3.Connection:
    """Create a SQLite connection, read-only by default."""

    db_path = get_sqlite_db_path(env)
    try:
        if read_only:
            resolved = db_path.resolve(strict=True)
            connection = sqlite3.connect(resolved.as_uri() + "?mode=ro", uri=True)
            connection.execute("PRAGMA query_only=ON")
        else:
            db_path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(db_path)
        return connection
    except sqlite3.Error as exc:
        raise DatabaseConnectionError("Failed to connect to SQLite database.") from None
    except OSError as exc:
        raise DatabaseConnectionError("SQLite database path is not accessible.") from None


def _postgres_settings(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    required = {
        "POSTGRES_HOST": _first_env_value(("POSTGRES_HOST", "PGHOST"), env),
        "POSTGRES_DB": _first_env_value(("POSTGRES_DB", "PGDATABASE"), env),
        "POSTGRES_USER": _first_env_value(("POSTGRES_USER", "PGUSER"), env),
        "POSTGRES_PASSWORD": _first_env_value(
            ("POSTGRES_PASSWORD", "PGPASSWORD"),
            env,
        ),
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        raise DatabaseConfigurationError(
            "Missing required PostgreSQL environment variables: "
            + ", ".join(sorted(missing))
        )

    port_text = _first_env_value(("POSTGRES_PORT", "PGPORT"), env) or "5432"
    try:
        port = int(port_text)
    except ValueError as exc:
        raise DatabaseConfigurationError("POSTGRES_PORT must be an integer.") from exc

    return {
        "host": required["POSTGRES_HOST"],
        "port": port,
        "dbname": required["POSTGRES_DB"],
        "user": required["POSTGRES_USER"],
        "password": required["POSTGRES_PASSWORD"],
        "sslmode": _first_env_value(("POSTGRES_SSLMODE", "PGSSLMODE"), env)
        or "require",
    }


def connect_postgres(
    *,
    read_only: bool = True,
    env: Mapping[str, str] | None = None,
) -> Any:
    """Create a PostgreSQL connection using psycopg.

    Connection details are passed as keyword arguments so no full DSN is built
    or exposed in errors.
    """

    settings = _postgres_settings(env)
    try:
        import psycopg
    except ImportError as exc:
        raise DatabaseConnectionError(
            "PostgreSQL driver 'psycopg' is not installed."
        ) from None

    try:
        connection = psycopg.connect(**settings)
        if read_only:
            with connection.cursor() as cursor:
                cursor.execute("SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY")
        return connection
    except Exception as exc:
        raise DatabaseConnectionError(
            "Failed to connect to PostgreSQL database."
        ) from None


def connect_database(
    *,
    read_only: bool = True,
    env: Mapping[str, str] | None = None,
) -> Any:
    """Return a connection for the configured database type."""

    db_type = get_db_type(env)
    if db_type == "sqlite":
        return connect_sqlite(read_only=read_only, env=env)
    return connect_postgres(read_only=read_only, env=env)


def get_placeholder(db_type: str | None = None) -> str:
    """Return the DB-API placeholder for the database type."""

    actual = get_db_type({"DB_TYPE": db_type}) if db_type else get_db_type()
    return "?" if actual == "sqlite" else "%s"


def get_view_exists_sql(db_type: str | None = None) -> str:
    """Return SQL that checks whether a view exists.

    SQLite expects one parameter: view name.
    PostgreSQL expects two parameters: schema name, then view name. Passing
    None for schema uses the current schema.
    """

    actual = get_db_type({"DB_TYPE": db_type}) if db_type else get_db_type()
    if actual == "sqlite":
        return """
            SELECT 1
            FROM sqlite_master
            WHERE type = 'view'
              AND name = ?
            LIMIT 1
        """
    return """
        SELECT 1
        FROM information_schema.views
        WHERE table_schema = COALESCE(%s, current_schema())
          AND table_name = %s
        LIMIT 1
    """


def smoke_test_connection(env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Run a lightweight connection check for the configured database."""

    db_type = get_db_type(env)
    connection = connect_database(read_only=True, env=env)
    try:
        if db_type == "sqlite":
            row = connection.execute("SELECT 1").fetchone()
            return {"db_type": db_type, "ok": row[0] == 1, "result": row[0]}

        with connection.cursor() as cursor:
            cursor.execute("SELECT current_database()")
            row = cursor.fetchone()
        return {"db_type": db_type, "ok": bool(row and row[0]), "database": row[0]}
    finally:
        connection.close()
