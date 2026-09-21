"""Canonical corpus database contract tests."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import pytest
from sqlalchemy import create_engine, inspect, text
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
    """Return an inspector for the configured integration database."""
    return inspect(database_engine())


@contextmanager
def database_connection() -> Iterator[Connection]:
    """Provide a connection whose test data is always rolled back."""
    with database_engine().connect() as connection:
        transaction = connection.begin()
        try:
            yield connection
        finally:
            transaction.rollback()


@pytest.mark.integration
def test_canonical_corpus_schema_tracks_domain_concepts() -> None:
    inspector = database_inspector()

    columns = {
        table: {column["name"] for column in inspector.get_columns(table)}
        for table in (
            "atti_normativi",
            "redazioni",
            "acquisizioni_fonti",
            "partizioni_normative",
        )
    }

    assert columns == {
        "atti_normativi": {"id", "urn", "titolo"},
        "redazioni": {
            "id",
            "atto_normativo_id",
            "acquisizione_fonte_id",
            "vigente_dal",
            "vigente_al",
        },
        "acquisizioni_fonti": {
            "id",
            "fonte",
            "url",
            "contenuto",
            "sha256",
            "acquisita_il",
        },
        "partizioni_normative": {
            "id",
            "redazione_id",
            "partizione_genitore_id",
            "identificatore",
            "tipo",
            "ordine",
            "contenuto",
        },
    }

    foreign_keys = {
        table: {
            (tuple(key["constrained_columns"]), key["referred_table"])
            for key in inspector.get_foreign_keys(table)
        }
        for table in ("redazioni", "partizioni_normative")
    }

    assert foreign_keys == {
        "redazioni": {
            (("atto_normativo_id",), "atti_normativi"),
            (("acquisizione_fonte_id",), "acquisizioni_fonti"),
        },
        "partizioni_normative": {
            (("redazione_id",), "redazioni"),
            (
                ("partizione_genitore_id", "redazione_id"),
                "partizioni_normative",
            ),
        },
    }


@pytest.mark.integration
def test_a_normative_act_urn_identifies_only_one_normative_act() -> None:
    with database_connection() as connection:
        connection.execute(
            text(
                "INSERT INTO atti_normativi (urn, titolo) "
                "VALUES ('urn:nir:stato:decreto.legislativo:2008-04-09;81', "
                "'Testo unico sulla sicurezza')"
            )
        )

        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO atti_normativi (urn, titolo) "
                    "VALUES ("
                    "'urn:nir:stato:decreto.legislativo:2008-04-09;81', "
                    "'Titolo duplicato')"
                )
            )


@pytest.mark.integration
def test_source_content_is_acquired_only_once_per_source_hash() -> None:
    sha256 = "a" * 64
    with database_connection() as connection:
        connection.execute(
            text(
                "INSERT INTO acquisizioni_fonti "
                "(fonte, url, contenuto, sha256) VALUES "
                "('Normattiva', 'https://example.test/1', '<atto />', :sha256)"
            ),
            {"sha256": sha256},
        )

        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO acquisizioni_fonti "
                    "(fonte, url, contenuto, sha256) VALUES "
                    "('Normattiva', 'https://example.test/2', '<atto />', :sha256)"
                ),
                {"sha256": sha256},
            )


@pytest.mark.integration
def test_redactions_coexist_only_when_validity_intervals_do_not_overlap() -> None:
    with database_connection() as connection:
        act_id = connection.execute(
            text(
                "INSERT INTO atti_normativi (urn, titolo) "
                "VALUES ('urn:test:redazioni', 'Atto con redazioni') RETURNING id"
            )
        ).scalar_one()
        acquisition_id = connection.execute(
            text(
                "INSERT INTO acquisizioni_fonti "
                "(fonte, url, contenuto, sha256) VALUES "
                "('Normattiva', 'https://example.test/redazioni', '<atto />', :sha256) "
                "RETURNING id"
            ),
            {"sha256": "b" * 64},
        ).scalar_one()
        parameters = {"act_id": act_id, "acquisition_id": acquisition_id}

        connection.execute(
            text(
                "INSERT INTO redazioni "
                "(atto_normativo_id, acquisizione_fonte_id, vigente_dal, vigente_al) "
                "VALUES (:act_id, :acquisition_id, '2020-01-01', '2022-01-01'), "
                "(:act_id, :acquisition_id, '2022-01-01', NULL)"
            ),
            parameters,
        )

        with pytest.raises(IntegrityError), connection.begin_nested():
            connection.execute(
                text(
                    "INSERT INTO redazioni "
                    "(atto_normativo_id, acquisizione_fonte_id, "
                    "vigente_dal, vigente_al) "
                    "VALUES (:act_id, :acquisition_id, '2021-01-01', '2023-01-01')"
                ),
                parameters,
            )

        count = connection.execute(
            text(
                "SELECT count(*) FROM redazioni "
                "WHERE atto_normativo_id = :act_id"
            ),
            parameters,
        ).scalar_one()

        assert count == 2


@pytest.mark.integration
def test_redaction_must_have_a_positive_validity_interval() -> None:
    with database_connection() as connection:
        act_id = connection.execute(
            text(
                "INSERT INTO atti_normativi (urn, titolo) "
                "VALUES ('urn:test:intervallo', 'Atto') RETURNING id"
            )
        ).scalar_one()
        acquisition_id = connection.execute(
            text(
                "INSERT INTO acquisizioni_fonti "
                "(fonte, url, contenuto, sha256) VALUES "
                "('Normattiva', 'https://example.test/intervallo', '<atto />', :sha256) "
                "RETURNING id"
            ),
            {"sha256": "c" * 64},
        ).scalar_one()

        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO redazioni "
                    "(atto_normativo_id, acquisizione_fonte_id, "
                    "vigente_dal, vigente_al) "
                    "VALUES (:act_id, :acquisition_id, '2024-01-01', '2024-01-01')"
                ),
                {"act_id": act_id, "acquisition_id": acquisition_id},
            )


@pytest.mark.integration
def test_partition_identifier_is_unique_within_a_redaction() -> None:
    with database_connection() as connection:
        redaction_id = connection.execute(
            text(
                "WITH act AS ("
                "  INSERT INTO atti_normativi (urn, titolo) "
                "  VALUES ('urn:test:partizioni', 'Atto') RETURNING id"
                "), acquisition AS ("
                "  INSERT INTO acquisizioni_fonti "
                "  (fonte, url, contenuto, sha256) VALUES "
                "  ('Normattiva', 'https://example.test/partizioni', "
                "   '<atto />', :sha256) RETURNING id"
                ") INSERT INTO redazioni "
                "(atto_normativo_id, acquisizione_fonte_id, vigente_dal) "
                "SELECT act.id, acquisition.id, '2024-01-01' "
                "FROM act, acquisition RETURNING id"
            ),
            {"sha256": "d" * 64},
        ).scalar_one()
        parameters = {"redaction_id": redaction_id}
        connection.execute(
            text(
                "INSERT INTO partizioni_normative "
                "(redazione_id, identificatore, tipo, ordine, contenuto) VALUES "
                "(:redaction_id, 'art-1', 'articolo', 1, 'Articolo 1')"
            ),
            parameters,
        )

        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO partizioni_normative "
                    "(redazione_id, identificatore, tipo, ordine, contenuto) VALUES "
                    "(:redaction_id, 'art-1', 'articolo', 2, 'Duplicato')"
                ),
                parameters,
            )


@pytest.mark.integration
def test_partition_parent_belongs_to_the_same_redaction() -> None:
    with database_connection() as connection:
        redaction_ids = connection.execute(
            text(
                "WITH acts AS ("
                "  INSERT INTO atti_normativi (urn, titolo) VALUES "
                "  ('urn:test:gerarchia:1', 'Atto 1'), "
                "  ('urn:test:gerarchia:2', 'Atto 2') RETURNING id, urn"
                "), acquisition AS ("
                "  INSERT INTO acquisizioni_fonti "
                "  (fonte, url, contenuto, sha256) VALUES "
                "  ('Normattiva', 'https://example.test/gerarchia', "
                "   '<atti />', :sha256) RETURNING id"
                ") INSERT INTO redazioni "
                "(atto_normativo_id, acquisizione_fonte_id, vigente_dal) "
                "SELECT acts.id, acquisition.id, '2024-01-01' "
                "FROM acts, acquisition ORDER BY acts.urn RETURNING id"
            ),
            {"sha256": "e" * 64},
        ).scalars().all()
        parent_id = connection.execute(
            text(
                "INSERT INTO partizioni_normative "
                "(redazione_id, identificatore, tipo, ordine, contenuto) VALUES "
                "(:redaction_id, 'art-1', 'articolo', 1, 'Articolo 1') "
                "RETURNING id"
            ),
            {"redaction_id": redaction_ids[0]},
        ).scalar_one()

        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    "INSERT INTO partizioni_normative "
                    "(redazione_id, partizione_genitore_id, identificatore, "
                    "tipo, ordine, contenuto) VALUES "
                    "(:redaction_id, :parent_id, 'comma-1', "
                    "'comma', 1, 'Comma 1')"
                ),
                {"redaction_id": redaction_ids[1], "parent_id": parent_id},
            )
