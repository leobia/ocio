"""The shipped template is published as a revision, never as a dossier rewrite."""

import json
import runpy
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

from ocio.database import database_url
from ocio.dossier import section_titles, validate_instructions

VERSIONS = Path(__file__).parents[1] / "alembic" / "versions"
update = runpy.run_path(str(VERSIONS / "20260929_02_expand_default_dossier.py"))


def test_default_instructions_are_bound_to_real_sections() -> None:
    validate_instructions(update["MARKDOWN"], update["INSTRUCTIONS"])
    assert set(section_titles(update["MARKDOWN"])) == set(update["INSTRUCTIONS"])
    assert all(update["WRITING_GUIDANCE"] in value for value in update["INSTRUCTIONS"].values())


@pytest.mark.integration
def test_default_revision_preserves_cases_custom_templates_and_history() -> None:
    try:
        url = database_url()
    except RuntimeError:
        pytest.skip("PostgreSQL environment variables are not configured")
    engine = create_engine(url)
    schema = f"test_default_{uuid4().hex}"
    original = "# Fascicolo\n\n## 1. Anagrafica e organizzazione\n\nNota del consulente.\n"
    template_id = update["TEMPLATE_ID"]
    first_revision = "00000000-0000-4000-8000-000000000242"
    later_revision, custom_template, custom_revision = uuid4(), uuid4(), uuid4()
    case_id, custom_case, history_id, pending_id = uuid4(), uuid4(), uuid4(), uuid4()
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                # Roll back this isolated schema and all test data at the end.
                connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                context = MigrationContext.configure(connection)
                with Operations.context(context):
                    runpy.run_path(str(VERSIONS / "20260929_01_create_engagements.py"))["upgrade"]()
                    connection.execute(text(
                        "INSERT INTO revisioni_modello_fascicolo "
                        "(id, modello_id, numero, schema_markdown, indicazioni) "
                        "VALUES (:id, :template, 2, :markdown, CAST(:instructions AS jsonb))"
                    ), {"id": later_revision, "template": template_id, "markdown": original,
                        "instructions": json.dumps({"1. Anagrafica e organizzazione": "Indicazione personalizzata"})})
                    connection.execute(text(
                        "INSERT INTO modelli_fascicolo (id, nome) VALUES (:id, 'Modello utente')"
                    ), {"id": custom_template})
                    connection.execute(text(
                        "INSERT INTO revisioni_modello_fascicolo "
                        "(id, modello_id, numero, schema_markdown) VALUES (:id, :template, 1, '## Personale')"
                    ), {"id": custom_revision, "template": custom_template})
                    for identifier, revision_id in [(case_id, first_revision), (custom_case, custom_revision)]:
                        connection.execute(text(
                            "INSERT INTO incarichi "
                            "(id, azienda, sede, data_riferimento, revisione_modello_id, fascicolo_markdown) "
                            "VALUES (:id, 'Azienda fittizia', 'Sede', '2026-09-29', :revision, :markdown)"
                        ), {"id": identifier, "revision": revision_id, "markdown": original})
                    connection.execute(text(
                        "INSERT INTO revisioni_fascicolo "
                        "(id, incarico_id, numero, revisione_modello_id, fascicolo_markdown, motivo) "
                        "VALUES (:id, :case, 1, :revision, :markdown, 'creazione')"
                    ), {"id": history_id, "case": case_id, "revision": first_revision, "markdown": original})
                    connection.execute(text(
                        "INSERT INTO migrazioni_fascicolo "
                        "(id, incarico_id, revisione_origine_id, revisione_destinazione_id, "
                        "fascicolo_origine, fascicolo_proposto, diff) "
                        "VALUES (:id, :case, :source, :target, :markdown, :markdown, '')"
                    ), {"id": pending_id, "case": case_id, "source": first_revision,
                        "target": later_revision, "markdown": original})

                    update["upgrade"]()

                    latest = connection.execute(text(
                        "SELECT numero, schema_markdown FROM revisioni_modello_fascicolo WHERE id = :id"
                    ), {"id": update["REVISION_ID"]}).mappings().one()
                    assert latest["numero"] == 3  # A user-created revision 2 is not overwritten.
                    assert latest["schema_markdown"] == update["MARKDOWN"]
                    assert connection.execute(text(
                        "SELECT schema_markdown FROM revisioni_modello_fascicolo WHERE id = :id"
                    ), {"id": later_revision}).scalar_one() == original
                    assert connection.execute(text(
                        "SELECT count(*) FROM revisioni_modello_fascicolo WHERE modello_id = :id"
                    ), {"id": custom_template}).scalar_one() == 1
                    assert connection.execute(text(
                        "SELECT fascicolo_markdown FROM incarichi WHERE id = :id"
                    ), {"id": case_id}).scalar_one() == original
                    assert str(connection.execute(text(
                        "SELECT revisione_modello_id FROM incarichi WHERE id = :id"
                    ), {"id": case_id}).scalar_one()) == first_revision
                    assert connection.execute(text(
                        "SELECT fascicolo_markdown FROM revisioni_fascicolo WHERE id = :id"
                    ), {"id": history_id}).scalar_one() == original
                    proposal = connection.execute(text(
                        "SELECT fascicolo_proposto, diff FROM migrazioni_fascicolo "
                        "WHERE incarico_id = :id AND stato = 'proposta'"
                    ), {"id": case_id}).mappings().one()
                    assert "Nota del consulente." in proposal["fascicolo_proposto"]
                    assert "## Attività, processi e mansioni" in proposal["fascicolo_proposto"]
                    assert proposal["diff"]
                    assert connection.execute(text(
                        "SELECT stato FROM migrazioni_fascicolo WHERE id = :id"
                    ), {"id": pending_id}).scalar_one() == "superata"
                    assert connection.execute(text(
                        "SELECT count(*) FROM migrazioni_fascicolo WHERE incarico_id = :id"
                    ), {"id": custom_case}).scalar_one() == 0
                    with pytest.raises(RuntimeError, match="conservata"):
                        update["downgrade"]()
            finally:
                transaction.rollback()
    finally:
        engine.dispose()


@pytest.mark.integration
@pytest.mark.parametrize("customized", [False, True])
def test_description_revision_preserves_customizations_and_case_text(customized: bool) -> None:
    try:
        url = database_url()
    except RuntimeError:
        pytest.skip("PostgreSQL environment variables are not configured")
    engine = create_engine(url)
    separation = runpy.run_path(str(VERSIONS / "20260929_03_separate_section_descriptions.py"))
    schema = f"test_descriptions_{uuid4().hex}"
    case_id = uuid4()
    original = "# Fascicolo\n\n## Ambienti di lavoro\n\nTesto  manuale.\n\n\n"
    try:
        with engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text(f'CREATE SCHEMA "{schema}"'))
                connection.execute(text(f'SET LOCAL search_path TO "{schema}"'))
                with Operations.context(MigrationContext.configure(connection)):
                    runpy.run_path(str(VERSIONS / "20260929_01_create_engagements.py"))["upgrade"]()
                    update["upgrade"]()
                    adopted_revision = update["REVISION_ID"]
                    expected_schema = update["MARKDOWN"]
                    descriptions = dict(update["INSTRUCTIONS"])
                    if customized:
                        adopted_revision = uuid4()
                        expected_schema += "\n## Sezione personalizzata\n\nContenuto iniziale.\n"
                        descriptions["Ambienti di lavoro"] = update["WRITING_GUIDANCE"] + "Descrivi solo il magazzino."
                        descriptions["Sezione personalizzata"] = "Approfondimento deciso dal consulente."
                        connection.execute(text(
                            "INSERT INTO revisioni_modello_fascicolo "
                            "(id, modello_id, numero, schema_markdown, indicazioni) "
                            "VALUES (:id, :template, 3, :schema, CAST(:descriptions AS jsonb))"
                        ), {"id": adopted_revision, "template": update["TEMPLATE_ID"],
                            "schema": expected_schema, "descriptions": json.dumps(descriptions)})
                    connection.execute(text(
                        "INSERT INTO incarichi "
                        "(id, azienda, sede, data_riferimento, revisione_modello_id, fascicolo_markdown) "
                        "VALUES (:id, 'Azienda fittizia', 'Sede', '2026-09-29', :revision, :markdown)"
                    ), {"id": case_id, "revision": adopted_revision, "markdown": original})
                    separation["upgrade"]()
                    published = connection.execute(text(
                        "SELECT numero, schema_markdown, indicazioni FROM revisioni_modello_fascicolo "
                        "WHERE id = :id"
                    ), {"id": separation["REVISION_ID"]}).mappings().one()
                    assert published["numero"] == (4 if customized else 3)
                    assert published["schema_markdown"] == expected_schema
                    if customized:
                        assert published["indicazioni"]["Ambienti di lavoro"] == "Descrivi solo il magazzino."
                        assert published["indicazioni"]["Sezione personalizzata"] == "Approfondimento deciso dal consulente."
                    else:
                        assert published["indicazioni"] == separation["DESCRIPTIONS"]
                    assert all(not value.startswith(update["WRITING_GUIDANCE"])
                               for value in published["indicazioni"].values())
                    assert connection.execute(text(
                        "SELECT indicazioni FROM revisioni_modello_fascicolo WHERE id = :id"
                    ), {"id": adopted_revision}).scalar_one() == descriptions
                    assert connection.execute(text(
                        "SELECT fascicolo_markdown FROM incarichi WHERE id = :id"
                    ), {"id": case_id}).scalar_one() == original
                    proposal = connection.execute(text(
                        "SELECT fascicolo_proposto, diff FROM migrazioni_fascicolo "
                        "WHERE incarico_id = :id AND stato = 'proposta'"
                    ), {"id": case_id}).one()
                    assert proposal.fascicolo_proposto == original
                    assert proposal.diff == ""
            finally:
                transaction.rollback()
    finally:
        engine.dispose()
