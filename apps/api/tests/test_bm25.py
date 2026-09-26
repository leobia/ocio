"""Test del retrieval BM25 con pg_textsearch."""

from __future__ import annotations

import math
from collections.abc import Iterator
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from ocio.bm25 import (
    Bm25Error,
    Bm25Retriever,
    bm25_index_name,
    ensure_bm25_index,
)
from ocio.database import database_url
from ocio.postgres_fts import PostgresFtsRetriever


@pytest.fixture
def connection() -> Iterator[Connection]:
    try:
        url = database_url()
    except RuntimeError:
        pytest.skip("PostgreSQL environment variables are not configured")

    engine = create_engine(url)
    with engine.connect() as current:
        transaction = current.begin()
        try:
            yield current
        finally:
            transaction.rollback()
    engine.dispose()


def _insert(connection: Connection, sql: str, values: dict[str, Any]) -> int:
    return int(connection.execute(text(sql), values).scalar_one())


def _insert_set(connection: Connection, fingerprint: str) -> int:
    return _insert(
        connection,
        "INSERT INTO insiemi_chunk (strategia, revisione, configurazione, fingerprint) "
        "VALUES ('structural', 1, '{}'::jsonb, :fingerprint) RETURNING id",
        {"fingerprint": fingerprint},
    )


def _insert_chunk(
    connection: Connection,
    *,
    set_id: int,
    document_id: int,
    acquisition_id: int,
    identifier: str,
    role: str,
    content: str,
    parent_id: int | None = None,
    partitions: tuple[str, ...] = ("articolo-1",),
) -> int:
    chunk_id = _insert(
        connection,
        "INSERT INTO chunk "
        "(insieme_chunk_id, documento_id, chunk_genitore_id, identificatore, "
        " ruolo, ordine, contenuto, sha256) "
        "VALUES (:set_id, :document_id, :parent_id, :identifier, :role, 1, "
        "        :content, :digest) RETURNING id",
        {
            "set_id": set_id,
            "document_id": document_id,
            "parent_id": parent_id,
            "identifier": identifier,
            "role": role,
            "content": content,
            "digest": uuid4().hex.ljust(64, "0"),
        },
    )
    for position, partition in enumerate(partitions):
        connection.execute(
            text(
                "INSERT INTO chunk_partizioni "
                "(chunk_id, posizione, acquisizione_fonte_id, "
                " identificatore_partizione, sha256_contenuto) "
                "VALUES (:chunk_id, :position, :acquisition_id, :identifier, :digest)"
            ),
            {
                "chunk_id": chunk_id,
                "position": position,
                "acquisition_id": acquisition_id,
                "identifier": partition,
                "digest": uuid4().hex.ljust(64, "0"),
            },
        )
    return chunk_id


def _seed(connection: Connection) -> tuple[str, int, int, int]:
    suffix = uuid4().hex
    acquisition_id = _insert(
        connection,
        "INSERT INTO acquisizioni_fonti "
        "(fonte, url, contenuto, sha256, metadati) "
        "VALUES (:source, :url, :content, :digest, '{}'::jsonb) RETURNING id",
        {
            "source": f"bm25-{suffix}",
            "url": f"https://example.test/{suffix}",
            "content": "fixture bm25",
            "digest": suffix.ljust(64, "0"),
        },
    )
    enabled_document = _insert(
        connection,
        "INSERT INTO documenti (codice, titolo, tipo_documento, abilitato_per_agente) "
        "VALUES (:code, 'Sicurezza', 'atto_normativo', true) RETURNING id",
        {"code": f"a-doc-{suffix}"},
    )
    disabled_document = _insert(
        connection,
        "INSERT INTO documenti (codice, titolo, tipo_documento, abilitato_per_agente) "
        "VALUES (:code, 'Documento escluso', 'atto_normativo', false) RETURNING id",
        {"code": f"z-doc-{suffix}"},
    )
    fingerprint = ("a" + suffix).ljust(64, "0")
    set_id = _insert_set(connection, fingerprint)
    parent_id = _insert_chunk(
        connection,
        set_id=set_id,
        document_id=enabled_document,
        acquisition_id=acquisition_id,
        identifier="parent/articolo-1",
        role="parent",
        content="termineparentesclusivo prevenzione",
    )
    _insert_chunk(
        connection,
        set_id=set_id,
        document_id=enabled_document,
        acquisition_id=acquisition_id,
        identifier="chunk-b",
        role="ricercabile",
        content=(
            "Il datore di lavoro è responsabile della valutazione dei rischi "
            "per la sicurezza."
        ),
        parent_id=parent_id,
        partitions=("articolo-1/comma-2", "articolo-1/comma-1"),
    )
    _insert_chunk(
        connection,
        set_id=set_id,
        document_id=enabled_document,
        acquisition_id=acquisition_id,
        identifier="chunk-a",
        role="ricercabile",
        content="Il datore di lavoro cura la valutazione dei rischi per la sicurezza.",
    )
    _insert_chunk(
        connection,
        set_id=set_id,
        document_id=disabled_document,
        acquisition_id=acquisition_id,
        identifier="chunk-disabilitato",
        role="ricercabile",
        content="Il datore di lavoro cura la valutazione dei rischi per la sicurezza.",
    )
    ensure_bm25_index(connection, set_id)
    return fingerprint, set_id, enabled_document, acquisition_id


def test_index_name_is_deterministic() -> None:
    assert bm25_index_name(42) == "ix_chunk_contenuto_bm25_insieme_42"


def test_non_positive_limit_is_rejected() -> None:
    retriever = Bm25Retriever(cast(Connection, None), "fingerprint")

    with pytest.raises(Bm25Error, match="limite deve essere positivo"):
        retriever.retrieve("sicurezza", 0)


@pytest.mark.integration
def test_italian_retrieval_maps_provenance_parent_and_configuration(
    connection: Connection,
) -> None:
    fingerprint, _, _, _ = _seed(connection)

    ranking = Bm25Retriever(connection, fingerprint).retrieve(
        "responsabile della valutazione dei rischi", 1
    )

    assert ranking.stage == "pg-textsearch-bm25"
    assert len(ranking.candidates) == 1
    candidate = ranking.candidates[0]
    assert candidate.rank == 1
    assert math.isfinite(candidate.score)
    assert candidate.candidate.reference.chunk_identifier == "chunk-b"
    assert candidate.candidate.parent is not None
    assert candidate.candidate.parent.chunk_identifier == "parent/articolo-1"
    assert [
        source.partition_identifier for source in candidate.candidate.source_partitions
    ] == ["articolo-1/comma-2", "articolo-1/comma-1"]
    assert ranking.configuration["chunk_set_fingerprint"] == fingerprint
    assert ranking.configuration["engine"] == "pg_textsearch"
    assert ranking.configuration["text_config"] == "italian"
    assert ranking.configuration["k1"] == 1.2
    assert ranking.configuration["b"] == 0.75
    assert ranking.configuration["extension_version"]
    assert math.isfinite(ranking.latency_ms) and ranking.latency_ms >= 0


@pytest.mark.integration
def test_candidate_domain_matches_fts_and_excludes_parent_and_disabled_document(
    connection: Connection,
) -> None:
    fingerprint, _, enabled_document, _ = _seed(connection)

    bm25 = Bm25Retriever(connection, fingerprint).retrieve("rischi", 100)
    fts = PostgresFtsRetriever(connection, fingerprint).retrieve("rischi", 100)

    bm25_references = {item.candidate.reference for item in bm25.candidates}
    fts_references = {item.candidate.reference for item in fts.candidates}
    assert bm25_references == fts_references
    assert len(bm25_references) == 2
    assert Bm25Retriever(connection, fingerprint).retrieve(
        "termineparentesclusivo", 10
    ).candidates == ()

    connection.execute(
        text("UPDATE documenti SET abilitato_per_agente = false WHERE id = :id"),
        {"id": enabled_document},
    )
    assert Bm25Retriever(connection, fingerprint).retrieve(
        "rischi", 100
    ).candidates == ()


@pytest.mark.integration
def test_statistics_are_isolated_from_other_chunk_sets(connection: Connection) -> None:
    fingerprint, _, document_id, acquisition_id = _seed(connection)
    retriever = Bm25Retriever(connection, fingerprint)
    score_before = retriever.retrieve("responsabile rischi", 10).candidates[0].score

    other_fingerprint = ("b" + uuid4().hex).ljust(64, "0")
    other_set_id = _insert_set(connection, other_fingerprint)
    _insert_chunk(
        connection,
        set_id=other_set_id,
        document_id=document_id,
        acquisition_id=acquisition_id,
        identifier="chunk-altro-insieme",
        role="ricercabile",
        content=("responsabile rischi " * 100).strip(),
    )
    ensure_bm25_index(connection, other_set_id)

    score_after = retriever.retrieve("responsabile rischi", 10).candidates[0].score
    assert score_after == score_before


@pytest.mark.integration
def test_top_k_has_contiguous_ranks_and_deterministic_ties(
    connection: Connection,
) -> None:
    fingerprint, set_id, _, _ = _seed(connection)
    connection.execute(
        text(
            "UPDATE chunk SET contenuto = ("
            "  SELECT contenuto FROM chunk "
            "  WHERE insieme_chunk_id = :set_id AND identificatore = 'chunk-a'"
            ") WHERE insieme_chunk_id = :set_id AND identificatore = 'chunk-b'"
        ),
        {"set_id": set_id},
    )
    retriever = Bm25Retriever(connection, fingerprint)

    full = retriever.retrieve("rischi", 10)
    limited = retriever.retrieve("rischi", 1)

    assert [item.rank for item in full.candidates] == [1, 2]
    assert len(limited.candidates) == 1
    assert full.candidates[0].score == full.candidates[1].score
    assert [
        item.candidate.reference.chunk_identifier for item in full.candidates
    ] == ["chunk-a", "chunk-b"]


@pytest.mark.integration
def test_empty_query_returns_an_empty_ranking(connection: Connection) -> None:
    fingerprint, _, _, _ = _seed(connection)

    ranking = Bm25Retriever(connection, fingerprint).retrieve("e il di", 10)

    assert ranking.candidates == ()


@pytest.mark.integration
def test_missing_chunk_set_and_index_are_rejected(connection: Connection) -> None:
    with pytest.raises(Bm25Error, match="Insieme di chunk inesistente"):
        Bm25Retriever(connection, "missing").retrieve("rischi", 10)

    fingerprint = ("c" + uuid4().hex).ljust(64, "0")
    _insert_set(connection, fingerprint)
    with pytest.raises(Bm25Error, match="Indice BM25 inesistente"):
        Bm25Retriever(connection, fingerprint).retrieve("rischi", 10)
