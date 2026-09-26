"""Canonical current-document database contract tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import LargeBinary, create_engine, inspect, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.engine.reflection import Inspector
from sqlalchemy.exc import IntegrityError

from ocio.database import database_url


def database_engine() -> Engine:
    """Return an engine for the configured integration database."""
    try:
        url = database_url()
    except RuntimeError:
        pytest.skip("PostgreSQL environment variables are not configured")
    return create_engine(url)


def database_inspector() -> Inspector:
    """Inspect the configured integration schema."""
    engine = database_engine()
    try:
        return inspect(engine)
    finally:
        engine.dispose()


@contextmanager
def database_connection() -> Iterator[Connection]:
    """Provide a connection whose test data is always rolled back."""
    engine = database_engine()
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                yield connection
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


@pytest.mark.integration
def test_schema_tracks_current_documents_and_source_acquisitions() -> None:
    inspector = database_inspector()
    acquisition_columns = {
        column["name"]: column["type"]
        for column in inspector.get_columns("acquisizioni_fonti")
    }
    columns = {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in ("documenti", "acquisizioni_fonti", "partizioni_documentali")
    }

    assert columns == {
        "documenti": {
            "id",
            "codice",
            "tipo_documento",
            "titolo",
            "urn",
            "vigente_dal",
            "vigente_al",
            "snapshot_al",
            "pubblicato_il",
            "abilitato_per_agente",
        },
        "acquisizioni_fonti": {
            "id",
            "fonte",
            "url",
            "contenuto",
            "sha256",
            "acquisita_il",
            "metadati",
        },
        "partizioni_documentali": {
            "id",
            "documento_id",
            "partizione_genitore_id",
            "acquisizione_fonte_id",
            "identificatore",
            "tipo",
            "rubrica",
            "ordine",
            "contenuto",
            "localizzatore",
            "vigente_dal",
            "vigente_al",
        },
    }
    assert isinstance(acquisition_columns["contenuto"], LargeBinary)
    assert isinstance(acquisition_columns["metadati"], JSONB)

    foreign_keys = {
        table: {
            (tuple(key["constrained_columns"]), key["referred_table"])
            for key in inspector.get_foreign_keys(table)
        }
        for table in ("partizioni_documentali",)
    }
    assert foreign_keys["partizioni_documentali"] == {
        (("documento_id",), "documenti"),
        (("acquisizione_fonte_id",), "acquisizioni_fonti"),
        (("partizione_genitore_id", "documento_id"), "partizioni_documentali"),
    }


@pytest.mark.integration
def test_document_code_is_unique_and_agent_flag_defaults_to_enabled() -> None:
    with database_connection() as connection:
        connection.execute(
            text(
                "INSERT INTO documenti (codice, tipo_documento, titolo) "
                "VALUES ('test-document-code', 'faq', 'FAQ')"
            )
        )
        enabled = connection.execute(
            text("SELECT abilitato_per_agente FROM documenti WHERE codice = :code"),
            {"code": "test-document-code"},
        ).scalar_one()
        assert enabled is True

        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(
                text(
                    "INSERT INTO documenti (codice, tipo_documento, titolo) "
                    "VALUES ('test-document-code', 'faq', 'Duplicato')"
                )
            )


@pytest.mark.integration
def test_source_content_is_unique_per_provider_and_hash() -> None:
    sha256 = "a" * 64
    with database_connection() as connection:
        connection.execute(
            text(
                "INSERT INTO acquisizioni_fonti "
                "(fonte, url, contenuto, sha256) VALUES "
                "('Normattiva', 'https://example.test/1', decode('<atto />', 'escape'), :sha256)"
            ),
            {"sha256": sha256},
        )
        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(
                text(
                    "INSERT INTO acquisizioni_fonti "
                    "(fonte, url, contenuto, sha256) VALUES "
                    "('Normattiva', 'https://example.test/2', decode('<atto />', 'escape'), :sha256)"
                ),
                {"sha256": sha256},
            )


@pytest.mark.integration
def test_partition_parent_must_belong_to_the_same_document() -> None:
    with database_connection() as connection:
        first_document = connection.execute(
            text(
                "INSERT INTO documenti (codice, tipo_documento, titolo) "
                "VALUES ('test-parent-a', 'atto_normativo', 'Atto A') RETURNING id"
            )
        ).scalar_one()
        second_document = connection.execute(
            text(
                "INSERT INTO documenti (codice, tipo_documento, titolo) "
                "VALUES ('test-parent-b', 'atto_normativo', 'Atto B') RETURNING id"
            )
        ).scalar_one()
        acquisition_id = connection.execute(
            text(
                "INSERT INTO acquisizioni_fonti "
                "(fonte, url, contenuto, sha256) VALUES "
                "('Normattiva', 'https://example.test/parent', decode('<atto />', 'escape'), :sha256) "
                "RETURNING id"
            ),
            {"sha256": "b" * 64},
        ).scalar_one()
        parent_id = connection.execute(
            text(
                "INSERT INTO partizioni_documentali "
                "(documento_id, acquisizione_fonte_id, identificatore, tipo, ordine, contenuto) "
                "VALUES (:document_id, :acquisition_id, 'art-1', 'articolo', 1, '') RETURNING id"
            ),
            {"document_id": first_document, "acquisition_id": acquisition_id},
        ).scalar_one()

        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(
                text(
                    "INSERT INTO partizioni_documentali "
                    "(documento_id, partizione_genitore_id, acquisizione_fonte_id, "
                    " identificatore, tipo, ordine, contenuto) "
                    "VALUES (:document_id, :parent_id, :acquisition_id, 'art-1/comma-1', "
                    " 'comma', 1, '')"
                ),
                {
                    "document_id": second_document,
                    "parent_id": parent_id,
                    "acquisition_id": acquisition_id,
                },
            )
