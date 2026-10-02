"""Agent state is owned by OCIO and survives separate SDK runs."""

import asyncio
import runpy
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from ocio.api import PostgresStore, create_app
from ocio.database import database_url
from ocio.dossier import exportable_dossier, replace_section_body, section_titles
from ocio.dossier_agent import DossierAgentService, PostgresAgentStore, StateConflict
from ocio.engagement_evidence import PostgresEvidenceStore

VERSIONS = Path(__file__).parents[1] / "alembic" / "versions"
DEFAULT_REVISION = "00000000-0000-4000-8000-000000000242"


def test_section_write_and_export_keep_other_sections() -> None:
    original = "# Bozza\n\n## Uffici\n\nDa completare.\n\n## Macchine\n\nDa verificare.\n"
    updated = replace_section_body(original, "Uffici", "Attività documentata.")
    assert "## Uffici\n\nAttività documentata." in updated
    assert "## Macchine\n\nDa verificare." in updated
    assert "## Macchine" not in exportable_dossier(updated, {"Macchine"})
    assert "## Macchine" in updated
    with pytest.raises(ValueError):
        replace_section_body(original, "Inesistente", "Testo")


def test_sdk_run_disables_hosted_trace_and_limits_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    from agents import Runner

    async def inspect_run(agent: object, input: str, **kwargs: object) -> SimpleNamespace:
        assert input.startswith("{")
        assert kwargs["max_turns"] == 24
        assert kwargs["run_config"].tracing_disabled is True
        assert agent.model_settings.store is False
        assert agent.model_settings.parallel_tool_calls is False
        assert {tool.name for tool in agent.tools} == {
            "plan_work", "analyze_evidence", "propose_fact", "knowledge_search",
            "set_relevance", "write_section", "check_section", "ask_question",
        }
        return SimpleNamespace(final_output="Concluso")

    monkeypatch.setattr(Runner, "run", inspect_run)
    service = DossierAgentService(SimpleNamespace(), SimpleNamespace())
    result = asyncio.run(service._run_sdk(uuid4(), "gpt-4.1", "Istruzioni", {
        "engagement": {"id": str(uuid4())},
    }))
    assert result == "Concluso"


@pytest.mark.integration
def test_agent_waits_and_resumes_without_duplicating_effects() -> None:
    try:
        database_url()
    except RuntimeError:
        pytest.skip("PostgreSQL environment variables are not configured")
    root = create_engine(database_url())
    schema = f"test_agent_{uuid4().hex}"
    with root.begin() as connection:
        connection.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(database_url(), connect_args={"options": f"-csearch_path={schema}"})
    try:
        with engine.begin() as connection:
            with Operations.context(MigrationContext.configure(connection)):
                for name in ("20260929_01_create_engagements.py",
                             "20260930_01_engagement_evidence.py"):
                    runpy.run_path(str(VERSIONS / name))["upgrade"]()
                existing_id = uuid4()
                connection.execute(text(
                    "INSERT INTO incarichi (id, azienda, sede, data_riferimento, "
                    "revisione_modello_id, fascicolo_markdown) "
                    "VALUES (:id, 'Preesistente', 'Sede', '2026-09-30', :revision, "
                    "'# Fascicolo\n\n## Sezione preesistente\n\nAppunti.')"
                ), {"id": existing_id, "revision": DEFAULT_REVISION})
                runpy.run_path(str(VERSIONS / "20260930_02_dossier_agent.py"))["upgrade"]()
                runpy.run_path(str(VERSIONS / "20261002_01_dossier_review.py"))["upgrade"]()
                runpy.run_path(str(VERSIONS / "20261002_02_company_research.py"))["upgrade"]()
                assert connection.execute(text(
                    "SELECT stato FROM pertinenza_sezioni WHERE incarico_id = :id "
                    "AND sezione = 'Sezione preesistente'"
                ), {"id": existing_id}).scalar_one() == "da_valutare"
        store = PostgresAgentStore(engine)
        evidence = PostgresEvidenceStore(engine)
        turns = 0

        async def scripted_runner(run_id: UUID, instructions: str, payload: dict, service: DossierAgentService) -> str:
            nonlocal turns
            turns += 1
            assert "Ancora ogni affermazione" in instructions
            assert payload["template"]["schema"].startswith("# Fascicolo")
            assert payload["engagement"]["template_revision_id"] == DEFAULT_REVISION
            version = payload["engagement"]["version"]
            message_id = payload["messages"][-1]["id"]
            operation_id = uuid4()
            planned = service.store.effect(run_id, operation_id, version, "plan", {"plan": "Completare anagrafica, poi verificare macchine."})
            assert service.store.effect(run_id, operation_id, version, "plan", {"plan": "Completare anagrafica, poi verificare macchine."}) == planned
            version = planned["version"]
            def effect(kind: str, value: dict) -> dict:
                nonlocal version
                result = service.store.effect(run_id, uuid4(), version, kind, value)
                version = result["version"]
                return result
            if turns == 1:
                with pytest.raises(ValueError, match="Riferimento"):
                    service.store.effect(run_id, uuid4(), version, "relevance", {
                        "section": "1. Anagrafica e organizzazione", "status": "pertinente",
                        "reason": "Fonte inesistente", "references": [str(uuid4())]})
                effect("fact", {"section": "1. Anagrafica e organizzazione",
                                "text": "L'azienda opera in sede.", "references": [message_id]})
                effect("fact", {"section": "1. Anagrafica e organizzazione",
                                "text": "L'azienda opera in sede.", "references": [message_id]})
                effect("relevance", {"section": "1. Anagrafica e organizzazione",
                                     "status": "pertinente", "reason": "Appunto aziendale",
                                     "references": [message_id]})
                effect("write", {"section": "1. Anagrafica e organizzazione",
                                 "body": f"L'azienda opera in sede. [evidenza: {message_id}]",
                                 "references": [message_id]})
                effect("question", {"section": "1. Anagrafica e organizzazione",
                                    "question": "Qual è il numero degli addetti?", "impact": 2})
                effect("question", {"section": "8. Macchine, attrezzature e impianti",
                                    "question": "Sono presenti macchine?", "impact": 4})
                effect("question", {"section": "8. Macchine, attrezzature e impianti",
                                    "question": "Sono presenti macchine?", "impact": 4})
                with pytest.raises(StateConflict):
                    service.store.effect(run_id, uuid4(), version - 1, "plan", {"plan": "Stale"})
            else:
                assert payload["previous_run"]["questions"][0]["question"] == "Sono presenti macchine?"
                effect("relevance", {"section": "8. Macchine, attrezzature e impianti",
                                     "status": "non_pertinente", "reason": "Confermato dall'operatore",
                                     "references": [message_id]})
                for title in section_titles(payload["template"]["schema"]):
                    if title not in ("1. Anagrafica e organizzazione",
                                     "8. Macchine, attrezzature e impianti"):
                        effect("relevance", {"section": title, "status": "non_pertinente",
                                             "reason": "Dichiarazione esplicita dell'operatore",
                                             "references": [message_id]})
            return "Lavoro utile completato."

        service = DossierAgentService(store, evidence, runner=scripted_runner)
        class Analyzer:
            def analyze(self, content: bytes, media_type: str, instruction: str,
                        sections: list[str]) -> tuple[str, list[dict[str, str]]]:
                assert content == b"Sede amministrativa documentata"
                assert media_type == "text/plain"
                assert "1. Anagrafica e organizzazione" in sections
                return "testo-test", [{"information": "Sede", "status": "osservato",
                                        "text": "Sede amministrativa documentata",
                                        "position": "riga 1",
                                        "section": "1. Anagrafica e organizzazione"}]
        client = TestClient(create_app(PostgresStore(engine), evidence_store=evidence,
                                       evidence_analyzer=Analyzer(), agent_service=service))
        created = client.post("/v1/engagements", json={
            "company": "Azienda prova", "site": "Sede", "reference_date": "2026-09-30",
            "template_revision_id": DEFAULT_REVISION,
        })
        assert created.status_code == 201, created.text
        case_id = created.json()["id"]
        first_message = client.post(f"/v1/engagements/{case_id}/messages",
                                    data={"content": "L'azienda opera in sede."},
                                    files={"files": ("sede.txt", b"Sede amministrativa documentata", "text/plain")})
        assert first_message.status_code == 201, first_message.text
        assert first_message.json()["observations"][0]["status"] == "osservato"
        first = client.post(f"/v1/engagements/{case_id}/agent/runs")
        assert first.status_code == 200, first.text
        assert first.json()["status"] == "in_attesa"
        assert [item["question"] for item in first.json()["questions"]] == [
            "Sono presenti macchine?", "Qual è il numero degli addetti?",
        ]
        case = client.get(f"/v1/engagements/{case_id}").json()
        assert case["status"] == "in_attesa"
        assert len(case["history"]) == 2
        assert len(store.snapshot(UUID(case_id))["proposed_facts"]) == 1
        assert first_message.json()["id"] in case["dossier_markdown"]
        second_message = client.post(f"/v1/engagements/{case_id}/messages", data={
            "content": "Non sono presenti macchine in questa sede. Le altre sezioni ancora da valutare non sono pertinenti per questo incarico.",
        })
        assert second_message.status_code == 201
        second = client.post(f"/v1/engagements/{case_id}/agent/runs")
        assert second.status_code == 200, second.text
        assert second.json()["status"] == "completato"
        case = client.get(f"/v1/engagements/{case_id}").json()
        assert case["relevance"]["8. Macchine, attrezzature e impianti"]["status"] == "non_pertinente"
        assert "## 8. Macchine" not in case["exportable_markdown"]
        assert "## 8. Macchine" in case["dossier_markdown"]
        assert len(case["relevance_history"]) == len(section_titles(case["dossier_markdown"]))
        messages = client.get(f"/v1/engagements/{case_id}/messages").json()
        assert [item["role"] for item in messages] == ["user", "assistant", "user", "assistant"]
        correction = client.patch(
            f"/v1/engagements/{case_id}/relevance/8.%20Macchine%2C%20attrezzature%20e%20impianti",
            json={"status": "pertinente", "reason": "Correzione dell'RSPP", "references": []},
        )
        assert correction.status_code == 200, correction.text
        assert correction.json()["relevance"]["8. Macchine, attrezzature e impianti"]["origin"] == "operatore"
        manual_run = store.start(UUID(case_id), "gpt-4.1")
        with pytest.raises(StateConflict, match="RSPP"):
            store.effect(manual_run, uuid4(), store.snapshot(UUID(case_id))["version"],
                         "relevance", {"section": "8. Macchine, attrezzature e impianti",
                                       "status": "non_pertinente", "reason": "Da sovrascrivere",
                                       "references": [second_message.json()["id"]]})
        store.finish(manual_run, "fallito", "Controllo concluso.")
        async def failing_runner(*args: object) -> str:
            raise TimeoutError("Budget esaurito")
        service.runner = failing_runner
        failed = client.post(f"/v1/engagements/{case_id}/agent/runs")
        assert failed.status_code == 200
        assert failed.json()["status"] == "fallito"
        assert client.get(f"/v1/engagements/{case_id}").json()["dossier_markdown"] == case["dossier_markdown"]
    finally:
        engine.dispose()
        with root.begin() as connection:
            connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        root.dispose()
