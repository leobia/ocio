"""Chunk persistence integration tests."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from ocio.chunking import ChunkingConfig, generate_chunk_set
from ocio.database import database_url


@pytest.mark.integration
def test_chunk_sets_are_reused_isolated_and_sourceable() -> None:
    try:
        url = database_url()
    except RuntimeError:
        pytest.skip("PostgreSQL environment variables are not configured")

    config = ChunkingConfig(max_tokens=512)
    fixed = generate_chunk_set("fixed", config)
    fixed_again = generate_chunk_set("fixed", config)
    structural = generate_chunk_set("structural", config)

    assert fixed.reused is False or fixed_again.reused is True
    assert fixed_again.set_id == fixed.set_id
    assert fixed_again.reused is True
    assert structural.set_id != fixed.set_id

    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            fixed_count = connection.execute(
                text("SELECT count(*) FROM chunk WHERE insieme_chunk_id = :set_id"),
                {"set_id": fixed.set_id},
            ).scalar_one()
            broken_sources = connection.execute(
                text(
                    "SELECT count(*) FROM chunk_partizioni AS source "
                    "JOIN chunk ON chunk.id = source.chunk_id "
                    "WHERE chunk.insieme_chunk_id IN (:fixed, :structural) "
                    "AND (source.partizione_documentale_id IS NULL "
                    "OR source.acquisizione_fonte_id IS NULL)"
                ),
                {"fixed": fixed.set_id, "structural": structural.set_id},
            ).scalar_one()
            cross_set_parents = connection.execute(
                text(
                    "SELECT count(*) FROM chunk AS child "
                    "JOIN chunk AS parent ON parent.id = child.chunk_genitore_id "
                    "WHERE child.insieme_chunk_id <> parent.insieme_chunk_id "
                    "OR child.documento_id <> parent.documento_id"
                )
            ).scalar_one()
    finally:
        engine.dispose()

    assert fixed_count == fixed.chunks
    assert broken_sources == 0
    assert cross_set_parents == 0
