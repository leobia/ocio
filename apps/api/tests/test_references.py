"""Test del lookup normativo e del glossario."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from ocio.database import database_url
from ocio.references import (
    Glossary,
    GlossaryRetriever,
    ReferenceLookupRetriever,
    expand_query,
    load_glossary,
    parse_legal_reference,
)
from ocio.retrieval import Ranking


class RecordingRetriever:
    def __init__(self) -> None:
        self.query = ""

    def retrieve(self, query: str, limit: int) -> Ranking:
        self.query = query
        return Ranking("test", (), {"limit": limit}, 0.0)


def test_parser_recognizes_complete_and_partial_references() -> None:
    glossary = load_glossary()

    complete = parse_legal_reference(
        "Vedi art. 77, comma 4, lett. h) del D.Lgs. 81/08", glossary
    )
    partial = parse_legal_reference("articolo 4 del DPR 462/2001", glossary)

    assert complete is not None
    assert (
        complete.document_code,
        complete.article,
        complete.paragraph,
        complete.letter,
    ) == ("dlgs_81_2008", "77", "4", "h")
    assert partial is not None
    assert (partial.document_code, partial.article) == ("dpr_462_2001", "4")
    assert partial.paragraph is partial.letter is None


def test_article_without_an_act_is_not_a_deterministic_reference() -> None:
    assert (
        parse_legal_reference("Cosa stabilisce l'articolo 4?", load_glossary()) is None
    )


def test_glossary_expansion_is_optional_and_traced_by_the_wrapper() -> None:
    glossary = load_glossary()
    inner = RecordingRetriever()
    retriever = GlossaryRetriever(inner, glossary, enabled=True)

    ranking = retriever.retrieve("Quando sono obbligatori i DPI?", 5)

    assert "dispositivi di protezione individuale" in inner.query
    assert ranking.configuration["query_expansion"]["enabled"] is True
    assert ranking.configuration["query_expansion"]["expansions"] == (
        ("DPI", "dispositivi di protezione individuale"),
    )
    disabled = expand_query("DPI", glossary, enabled=False)
    assert disabled.effective_query == "DPI"
    assert disabled.expansions == ()


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


@pytest.mark.integration
def test_lookup_maps_the_most_specific_reference_to_searchable_chunks(
    connection: Connection,
) -> None:
    suffix = uuid4().hex
    acquisition_id = _insert(
        connection,
        "INSERT INTO acquisizioni_fonti (fonte, url, contenuto, sha256, metadati) "
        "VALUES (:source, :url, 'fixture', :digest, '{}'::jsonb) RETURNING id",
        {
            "source": f"lookup-{suffix}",
            "url": f"https://example.test/{suffix}",
            "digest": suffix.ljust(64, "0"),
        },
    )
    code = f"atto-{suffix}"
    document_id = _insert(
        connection,
        "INSERT INTO documenti (codice, titolo, tipo_documento) "
        "VALUES (:code, 'Atto di prova', 'atto_normativo') RETURNING id",
        {"code": code},
    )

    def partition(kind: str, marker: str, parent: int | None) -> int:
        return _insert(
            connection,
            "INSERT INTO partizioni_documentali "
            "(documento_id, partizione_genitore_id, acquisizione_fonte_id, "
            " identificatore, tipo, marcatore, ordine, contenuto) "
            "VALUES (:document, :parent, :acquisition, :identifier, :kind, "
            " :marker, 1, :content) RETURNING id",
            {
                "document": document_id,
                "parent": parent,
                "acquisition": acquisition_id,
                "identifier": f"{kind}-{marker}",
                "kind": kind,
                "marker": marker,
                "content": f"contenuto {kind} {marker}",
            },
        )

    article_id = partition("articolo", "7", None)
    paragraph_id = partition("comma", "2", article_id)
    letter_id = partition("lettera", "b", paragraph_id)
    fingerprint = suffix.ljust(64, "f")
    set_id = _insert(
        connection,
        "INSERT INTO insiemi_chunk (strategia, revisione, configurazione, fingerprint) "
        "VALUES ('structural', 1, '{}'::jsonb, :fingerprint) RETURNING id",
        {"fingerprint": fingerprint},
    )

    for order, (identifier, partition_id) in enumerate(
        (("comma", paragraph_id), ("lettera", letter_id)), start=1
    ):
        chunk_id = _insert(
            connection,
            "INSERT INTO chunk (insieme_chunk_id, documento_id, identificatore, "
            " ruolo, ordine, contenuto, sha256) VALUES "
            "(:set_id, :document, :identifier, 'ricercabile', :position, "
            " :content, :digest) RETURNING id",
            {
                "set_id": set_id,
                "document": document_id,
                "identifier": identifier,
                "position": order,
                "content": f"contenuto {identifier}",
                "digest": uuid4().hex.ljust(64, "0"),
            },
        )
        connection.execute(
            text(
                "INSERT INTO chunk_partizioni (chunk_id, posizione, "
                "partizione_documentale_id, acquisizione_fonte_id, "
                "identificatore_partizione, sha256_contenuto) VALUES "
                "(:chunk, 0, :partition, :acquisition, :identifier, :digest)"
            ),
            {
                "chunk": chunk_id,
                "partition": partition_id,
                "acquisition": acquisition_id,
                "identifier": identifier,
                "digest": uuid4().hex.ljust(64, "0"),
            },
        )

    glossary = Glossary(1, {code: ("Atto Lookup",)}, {})
    retriever = ReferenceLookupRetriever(connection, fingerprint, glossary)

    article = retriever.retrieve("Atto Lookup, articolo 7", 10)
    letter = retriever.retrieve("art. 7, comma 2, lettera b dell'Atto Lookup", 10)

    assert [
        item.candidate.reference.chunk_identifier for item in article.candidates
    ] == [
        "comma",
        "lettera",
    ]
    assert [
        item.candidate.reference.chunk_identifier for item in letter.candidates
    ] == ["lettera"]
    assert letter.configuration["resolved"] is True
