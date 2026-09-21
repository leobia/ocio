"""Database integration contract tests."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from ocio.database import database_url


@pytest.mark.integration
def test_required_extensions_are_enabled() -> None:
    try:
        url = database_url()
    except RuntimeError:
        pytest.skip("PostgreSQL environment variables are not configured")

    engine = create_engine(url)
    with engine.connect() as connection:
        extensions = set(
            connection.execute(
                text(
                    "SELECT extname FROM pg_extension "
                    "WHERE extname IN ('vector', 'pg_textsearch')"
                )
            ).scalars()
        )

    assert extensions == {"pg_textsearch", "vector"}
