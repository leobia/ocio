"""Database configuration tests."""

from __future__ import annotations

import pytest
from sqlalchemy.engine import make_url

from ocio.database import database_url


def test_database_url_uses_postgres_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("POSTGRES_DB", "ocio")
    monkeypatch.setenv("POSTGRES_USER", "user@example.com")
    monkeypatch.setenv("POSTGRES_PASSWORD", "p@ss word")
    monkeypatch.setenv("DB_HOST", "database")
    monkeypatch.setenv("DB_PORT", "5433")

    url = make_url(database_url())
    assert (url.username, url.password, url.host, url.port, url.database) == (
        "user@example.com",
        "p@ss word",
        "database",
        5433,
        "ocio",
    )


def test_database_url_requires_postgres_environment_variables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("POSTGRES_DB", raising=False)
    monkeypatch.delenv("POSTGRES_USER", raising=False)
    monkeypatch.delenv("POSTGRES_PASSWORD", raising=False)

    with pytest.raises(RuntimeError, match="POSTGRES_DB"):
        database_url()
