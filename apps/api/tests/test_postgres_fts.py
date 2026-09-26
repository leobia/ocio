"""Test del retrieval full-text PostgreSQL."""

from __future__ import annotations

import math
from collections.abc import Iterator
from pathlib import Path
from typing import Any, cast
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from ocio.database import database_url
from ocio.postgres_fts import PostgresFtsError, PostgresFtsRetriever
from ocio.retrieval import RetrievalRun, read_trace, write_trace


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


def _seed(connection: Connection) -> tuple[str, str, int, int]:
    suffix = uuid4().hex
    acquisition_id = _insert(
        connection,
        "INSERT INTO acquisizioni_fonti "
        "(fonte, url, contenuto, sha256, metadati) "
        "VALUES (:source, :url, :content, :digest, '{}'::jsonb) RETURNING id",
        {
            "source": f"fts-{suffix}",
            "url": f"https://example.test/{suffix}",
            "content": "fixture fts",
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
    other_fingerprint = ("b" + suffix).ljust(64, "0")
    set_id = _insert(
        connection,
        "INSERT INTO insiemi_chunk (strategia, revisione, configurazione, fingerprint) "
        "VALUES ('structural', 1, '{}'::jsonb, :fingerprint) RETURNING id",
        {"fingerprint": fingerprint},
    )
    other_set_id = _insert(
        connection,
        "INSERT INTO insiemi_chunk (strategia, revisione, configurazione, fingerprint) "
        "VALUES ('structural', 1, '{}'::jsonb, :fingerprint) RETURNING id",
        {"fingerprint": other_fingerprint},
    )

    parent_id = _insert_chunk(
        connection,
        set_id,
        enabled_document,
        acquisition_id,
        "parent/articolo-1",
        "parent",
        "termineparentesclusivo prevenzione",
    )
    first_id = _insert_chunk(
        connection,
        set_id,
        enabled_document,
        acquisition_id,
        "chunk-b",
        "ricercabile",
        "Il datore di lavoro è responsabile della valutazione dei rischi per la sicurezza.",
        parent_id,
        ("articolo-1/comma-2", "articolo-1/comma-1"),
    )
    _insert_chunk(
        connection,
        set_id,
        enabled_document,
        acquisition_id,
        "chunk-a",
        "ricercabile",
        "Il datore di lavoro cura la valutazione dei rischi per la sicurezza.",
    )
    disabled_chunk = _insert_chunk(
        connection,
        set_id,
        disabled_document,
        acquisition_id,
        "chunk-disabilitato",
        "ricercabile",
        "Il datore di lavoro cura la valutazione dei rischi per la sicurezza.",
    )
    _insert_chunk(
        connection,
        other_set_id,
        enabled_document,
        acquisition_id,
        "chunk-altro-insieme",
        "ricercabile",
        "termineisolato insieme differente",
    )
    return fingerprint, other_fingerprint, first_id, disabled_chunk


def _insert_chunk(
    connection: Connection,
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


def test_non_positive_limit_is_rejected() -> None:
    retriever = PostgresFtsRetriever(cast(Connection, None), "fingerprint")

    with pytest.raises(PostgresFtsError, match="limite deve essere positivo"):
        retriever.retrieve("sicurezza", 0)


@pytest.mark.integration
def test_italian_retrieval_maps_provenance_parent_and_trace(
    connection: Connection, tmp_path: Path
) -> None:
    fingerprint, _, _, _ = _seed(connection)
    retriever = PostgresFtsRetriever(connection, fingerprint)

    ranking = retriever.retrieve("responsabile della valutazione dei rischi", 1)

    assert ranking.stage == "postgres-fts"
    assert len(ranking.candidates) == 1
    assert ranking.candidates[0].rank == 1
    assert math.isfinite(ranking.candidates[0].score)
    assert ranking.candidates[0].candidate.reference.chunk_identifier == "chunk-b"
    parent = ranking.candidates[0].candidate.parent
    assert parent is not None
    assert parent.chunk_identifier == "parent/articolo-1"
    assert ranking.candidates[0].candidate.source_partitions[0].partition_identifier == (
        "articolo-1/comma-2"
    )
    assert ranking.candidates[0].candidate.source_partitions[1].partition_identifier == (
        "articolo-1/comma-1"
    )
    assert ranking.configuration == {
        "chunk_set_fingerprint": fingerprint,
        "dictionary": "italian",
        "query_function": "websearch_to_tsquery",
        "ranking_function": "ts_rank_cd",
    }
    assert math.isfinite(ranking.latency_ms) and ranking.latency_ms >= 0

    run = RetrievalRun("run", "case", "rischi", fingerprint, (ranking,))
    trace = tmp_path / "trace.jsonl"
    write_trace([run], trace)
    assert read_trace(trace) == (run,)


@pytest.mark.integration
def test_retrieval_isolates_set_role_and_disabled_documents(
    connection: Connection,
) -> None:
    fingerprint, other_fingerprint, _, _ = _seed(connection)

    assert PostgresFtsRetriever(connection, fingerprint).retrieve(
        "termineisolato", 10
    ).candidates == ()
    assert PostgresFtsRetriever(connection, other_fingerprint).retrieve(
        "termineisolato", 10
    ).candidates
    assert PostgresFtsRetriever(connection, fingerprint).retrieve(
        "termineparentesclusivo", 10
    ).candidates == ()

    ranking = PostgresFtsRetriever(connection, fingerprint).retrieve("rischi", 10)
    assert len(ranking.candidates) == 2
    connection.execute(text("UPDATE documenti SET abilitato_per_agente = false"))
    assert PostgresFtsRetriever(connection, fingerprint).retrieve(
        "rischi", 10
    ).candidates == ()


@pytest.mark.integration
def test_top_k_has_contiguous_ranks_and_deterministic_ties(
    connection: Connection,
) -> None:
    fingerprint, _, _, _ = _seed(connection)
    retriever = PostgresFtsRetriever(connection, fingerprint)

    full = retriever.retrieve("rischi", 10)
    limited = retriever.retrieve("rischi", 1)

    assert [item.rank for item in full.candidates] == [1, 2]
    assert len(limited.candidates) == 1
    assert [item.candidate.reference.chunk_identifier for item in full.candidates] == [
        "chunk-a",
        "chunk-b",
    ]
    assert full.candidates[0].score == full.candidates[1].score


@pytest.mark.integration
def test_empty_tsquery_returns_an_empty_ranking(connection: Connection) -> None:
    fingerprint, _, _, _ = _seed(connection)

    ranking = PostgresFtsRetriever(connection, fingerprint).retrieve("e il di", 10)

    assert ranking.candidates == ()


@pytest.mark.integration
def test_missing_chunk_set_is_rejected(connection: Connection) -> None:
    with pytest.raises(PostgresFtsError, match="Insieme di chunk inesistente"):
        PostgresFtsRetriever(connection, "missing").retrieve("rischi", 10)
