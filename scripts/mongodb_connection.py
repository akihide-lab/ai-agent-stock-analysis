"""MongoDB connection helper for source news storage."""

from __future__ import annotations

import logging
import os
from typing import Any

from dotenv import load_dotenv


LOGGER = logging.getLogger(__name__)
DEFAULT_SERVER_SELECTION_TIMEOUT_MS = 5000
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
ENV_FILES = (
    os.path.join(PROJECT_ROOT, ".env"),
    os.path.join(PROJECT_ROOT, "config", ".env"),
    os.path.join(PROJECT_ROOT, "Config", ".env"),
)


class MongoDBConfigurationError(RuntimeError):
    """Raised when MongoDB settings are missing or unusable."""


class MongoDBConnectionError(RuntimeError):
    """Raised when MongoDB cannot be reached."""


def mongodb_enabled(env: dict[str, str] | None = None) -> bool:
    values = env if env is not None else os.environ
    return str(values.get("MONGODB_ENABLED", "false")).strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def get_mongodb_database(
    env: dict[str, str] | None = None,
    server_selection_timeout_ms: int = DEFAULT_SERVER_SELECTION_TIMEOUT_MS,
) -> tuple[Any, Any]:
    """Return ``(client, database)`` after a ping check.

    The URI is intentionally never logged or included in raised messages.
    """

    for env_file in ENV_FILES:
        load_dotenv(env_file)
    values = env if env is not None else os.environ
    uri = values.get("MONGODB_URI")
    database_name = values.get("MONGODB_DATABASE")

    if not uri:
        raise MongoDBConfigurationError("MONGODB_URI is not configured.")
    if not database_name:
        raise MongoDBConfigurationError("MONGODB_DATABASE is not configured.")

    LOGGER.info("MongoDB connection starting")
    try:
        from pymongo import MongoClient
        from pymongo.errors import PyMongoError
    except ImportError as exc:
        raise MongoDBConfigurationError("pymongo is not installed.") from exc

    try:
        client = MongoClient(
            uri,
            serverSelectionTimeoutMS=server_selection_timeout_ms,
        )
        client.admin.command("ping")
    except PyMongoError as exc:
        raise MongoDBConnectionError("MongoDB connection failed.") from exc

    LOGGER.info("MongoDB connection succeeded")
    return client, client[database_name]
