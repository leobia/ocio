"""Evaluation corpus persistence integration tests."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection

from ocio.database import database_url
from ocio.evaluation import (
    corpus_records,
    default_schema_path,
    load_corpus_index,
    validate_lines,
)


@contextmanager
def database_connection() -> Iterator[Connection]:
    try:
        url = database_url()
    except RuntimeError:
        pytest.skip("PostgreSQL environment variables are not configured")
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                yield connection
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


def _insert_document(connection: Connection, code: str, *, enabled: bool) -> int:
    return int(
        connection.execute(
            text(
                "INSERT INTO documenti "
                "(codice, tipo_documento, titolo, abilitato_per_agente) "
                "VALUES (:code, 'test', :code, :enabled) RETURNING id"
            ),
            {"code": code, "enabled": enabled},
        ).scalar_one()
    )


def _case(document: str, partition: str, number: int) -> dict[str, Any]:
    evidence_text = {
        "art-1": "Contenuto utile.",
        "art-other": "Altro contenuto.",
        "art-disabled": "Contenuto disabilitato.",
    }.get(partition, "Contenuto utile.")
    return {
        "schema_version": 1,
        "id": f"case-{number}",
        "kind": "grounded",
        "query": f"Domanda {number}?",
        "difficulty": "easy",
        "answerable": True,
        "expected_evidence": [
            {
                "document_code": document,
                "partition_identifier": partition,
                "evidence_text": evidence_text,
            }
        ],
    }


@pytest.mark.integration
def test_export_and_reference_validation_use_the_canonical_enabled_corpus() -> None:
    schema = json.loads(default_schema_path().read_text(encoding="utf-8"))
    with database_connection() as connection:
        connection.execute(text("UPDATE documenti SET abilitato_per_agente = false"))
        enabled_id = _insert_document(connection, "eval-enabled", enabled=True)
        other_id = _insert_document(connection, "eval-other", enabled=True)
        disabled_id = _insert_document(connection, "eval-disabled", enabled=False)
        acquisition_id = connection.execute(
            text(
                "INSERT INTO acquisizioni_fonti "
                "(fonte, url, contenuto, sha256) VALUES "
                "('test', 'https://example.test/eval', decode('eval', 'escape'), :hash) "
                "RETURNING id"
            ),
            {"hash": "e" * 64},
        ).scalar_one()
        for document_id, identifier, content in (
            (enabled_id, "art-1", "Contenuto utile."),
            (enabled_id, "art-empty", "  "),
            (other_id, "art-other", "Altro contenuto."),
            (disabled_id, "art-disabled", "Contenuto disabilitato."),
        ):
            connection.execute(
                text(
                    "INSERT INTO partizioni_documentali "
                    "(documento_id, acquisizione_fonte_id, identificatore, "
                    " tipo, ordine, contenuto) VALUES "
                    "(:document_id, :acquisition_id, :identifier, "
                    " 'articolo', 1, :content)"
                ),
                {
                    "document_id": document_id,
                    "acquisition_id": acquisition_id,
                    "identifier": identifier,
                    "content": content,
                },
            )

        first_export = corpus_records(connection)
        second_export = corpus_records(connection)
        index = load_corpus_index(connection)
        cases = [
            _case("eval-enabled", "art-1", 1),
            _case("missing", "art-1", 2),
            _case("eval-enabled", "art-other", 3),
            _case("eval-disabled", "art-disabled", 4),
        ]
        report = validate_lines([json.dumps(case) for case in cases], schema, index)

    assert first_export == second_export
    assert [
        (row["document_code"], row["partition_identifier"]) for row in first_export
    ] == [
        ("eval-enabled", "art-1"),
        ("eval-other", "art-other"),
    ]
    messages = [issue.message for issue in report.issues]
    assert messages == [
        "documento inesistente 'missing'",
        "partizione 'art-other' inesistente nel documento 'eval-enabled'",
        "documento non abilitato per l’agente 'eval-disabled'",
    ]
