"""Snowflake connection helper for optional analysis DWH integration."""

from __future__ import annotations

import os
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILES = (
    PROJECT_ROOT / ".env",
    PROJECT_ROOT / "config" / ".env",
    PROJECT_ROOT / "Config" / ".env",
)


class SnowflakeConfigurationError(RuntimeError):
    """Raised when Snowflake configuration is missing or disabled."""


class SnowflakeConnectionError(RuntimeError):
    """Raised when Snowflake cannot be reached safely."""

    def __init__(self, message: str, *, category: str = "connection_failed") -> None:
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class SnowflakeSettings:
    enabled: bool
    account: str = ""
    user: str = ""
    password: str = ""
    warehouse: str = "AI_AGENT_WH"
    database: str = "MARKET_ANALYSIS"
    schema: str = "MART"
    role: str = ""
    allow_accountadmin_setup: bool = False


def _clean_env_value(value: str) -> str:
    cleaned = value.strip().strip('"').strip("'")
    for marker in ("←", " #"):
        if marker in cleaned:
            cleaned = cleaned.split(marker, 1)[0].strip()
    return cleaned.strip().strip('"').strip("'")


def _load_env_files() -> dict[str, str]:
    loaded: dict[str, str] = {}
    for path in ENV_FILES:
        if not path.is_file():
            continue
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = _clean_env_value(value)
            if key:
                loaded[key] = value
    return loaded


def _env_value(name: str, env: Mapping[str, str] | None = None) -> str:
    file_values: dict[str, str] = {}
    if env is None:
        file_values = _load_env_files()
    source = {**os.environ, **file_values} if env is None else env
    return str(source.get(name, "")).strip()


def snowflake_enabled(env: Mapping[str, str] | None = None) -> bool:
    return _env_value("SNOWFLAKE_ENABLED", env).lower() == "true"


def get_snowflake_settings(env: Mapping[str, str] | None = None) -> SnowflakeSettings:
    settings = SnowflakeSettings(
        enabled=snowflake_enabled(env),
        account=_env_value("SNOWFLAKE_ACCOUNT", env),
        user=_env_value("SNOWFLAKE_USER", env),
        password=_env_value("SNOWFLAKE_PASSWORD", env),
        warehouse=_env_value("SNOWFLAKE_WAREHOUSE", env) or "AI_AGENT_WH",
        database=_env_value("SNOWFLAKE_DATABASE", env) or "MARKET_ANALYSIS",
        schema=_env_value("SNOWFLAKE_SCHEMA", env) or "MART",
        role=_env_value("SNOWFLAKE_ROLE", env),
        allow_accountadmin_setup=_env_value("SNOWFLAKE_ALLOW_ACCOUNTADMIN_SETUP", env).lower()
        == "true",
    )
    if not settings.enabled:
        return settings

    missing = [
        name
        for name, value in {
            "SNOWFLAKE_ACCOUNT": settings.account,
            "SNOWFLAKE_USER": settings.user,
            "SNOWFLAKE_PASSWORD": settings.password,
            "SNOWFLAKE_WAREHOUSE": settings.warehouse,
            "SNOWFLAKE_DATABASE": settings.database,
            "SNOWFLAKE_SCHEMA": settings.schema,
        }.items()
        if not value
    ]
    if missing:
        raise SnowflakeConfigurationError(
            "Missing required Snowflake environment variables: "
            + ", ".join(sorted(missing))
        )
    if settings.role.upper() == "ACCOUNTADMIN" and not settings.allow_accountadmin_setup:
        raise SnowflakeConfigurationError(
            "SNOWFLAKE_ROLE must be a least-privilege role, not ACCOUNTADMIN, unless SNOWFLAKE_ALLOW_ACCOUNTADMIN_SETUP=true is set for initial setup."
        )
    return settings


def _safe_error_category(exc: Exception) -> str:
    message = str(exc).lower()
    if "password" in message or "authentication" in message or "incorrect username" in message:
        return "authentication_failed"
    if "timeout" in message or "timed out" in message:
        return "connection_timeout"
    if "account" in message:
        return "account_or_host_error"
    if "warehouse" in message:
        return "warehouse_error"
    return "connection_failed"


def connect_snowflake(env: Mapping[str, str] | None = None) -> Any:
    settings = get_snowflake_settings(env)
    if not settings.enabled:
        raise SnowflakeConfigurationError("Snowflake is disabled.")

    try:
        import snowflake.connector
    except ImportError:
        raise SnowflakeConnectionError(
            "Snowflake connector is not installed.",
            category="driver_not_installed",
        ) from None

    for logger_name in (
        "snowflake.connector",
        "snowflake.connector.connection",
        "snowflake.connector.vendored.urllib3.connectionpool",
    ):
        logging.getLogger(logger_name).setLevel(logging.ERROR)

    kwargs: dict[str, Any] = {
        "account": settings.account,
        "user": settings.user,
        "password": settings.password,
        "warehouse": settings.warehouse,
        "database": settings.database,
        "schema": settings.schema,
    }
    if settings.role:
        kwargs["role"] = settings.role

    try:
        connection = snowflake.connector.connect(**kwargs)
        with connection.cursor() as cursor:
            cursor.execute(f"USE WAREHOUSE {settings.warehouse}")
        return connection
    except Exception as exc:
        raise SnowflakeConnectionError(
            "Snowflake connection failed. Check account, user, role, warehouse, database, and network settings.",
            category=_safe_error_category(exc),
        ) from None


@contextmanager
def snowflake_connection(env: Mapping[str, str] | None = None) -> Iterator[Any]:
    connection = connect_snowflake(env)
    try:
        yield connection
    finally:
        connection.close()
