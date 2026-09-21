"""Database connection configuration."""

from __future__ import annotations

import os

from sqlalchemy import URL


def database_url() -> str:
    """Build the database URL from the PostgreSQL environment variables."""
    try:
        database = os.environ["POSTGRES_DB"]
        username = os.environ["POSTGRES_USER"]
        password = os.environ["POSTGRES_PASSWORD"]
    except KeyError as error:
        message = "POSTGRES_DB, POSTGRES_USER, and POSTGRES_PASSWORD must be set."
        raise RuntimeError(message) from error

    return URL.create(
        "postgresql+psycopg",
        username=username,
        password=password,
        host=os.environ.get("DB_HOST", "localhost"),
        port=int(os.environ.get("DB_PORT", "5432")),
        database=database,
    ).render_as_string(hide_password=False)
