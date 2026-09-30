"""Evidence API uses only invented case material and a fake analyzer."""

from collections.abc import Sequence
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from ocio.api import create_app
from ocio.database import database_url
from ocio.engagement_evidence import (
    MemoryEvidenceStore,
    OpenAIEvidenceAnalyzer,
    PostgresEvidenceStore,
)


class EngagementStub:
    def __init__(self, engagement_id: UUID) -> None:
        self.engagement_id = engagement_id

    def engagement(self, engagement_id: UUID) -> dict[str, str] | None:
        if engagement_id != self.engagement_id:
            return None
        return {"dossier_markdown": "# Caso fittizio\n\n## Attrezzature\n\n## Formazione\n"}


class FakeAnalyzer:
    def analyze(
        self, content: bytes, media_type: str, instruction: str,
        sections: Sequence[str],
    ) -> tuple[str, list[dict[str, str]]]:
        assert instruction == "Leggi il codice inventato sulla targhetta"
        assert sections == ("Attrezzature", "Formazione")
        return "analisi-fittizia-v1", [{
            "information": "Codice targhetta", "status": "non_leggibile",
            "text": "Il codice non è leggibile nella foto fittizia.",
            "position": "targhetta", "section": "Attrezzature",
        }]


def test_engagement_evidence_survives_reopen_and_is_isolated() -> None:
    engagement_id, other_id = uuid4(), uuid4()
    evidence = MemoryEvidenceStore()
    evidence.engagements.update((engagement_id, other_id))
    client = TestClient(create_app(
        store=EngagementStub(engagement_id), evidence_store=evidence,
        evidence_analyzer=FakeAnalyzer(),
    ))
    url = f"/v1/engagements/{engagement_id}"
    sent = client.post(f"{url}/messages", data={
        "content": "Leggi il codice inventato sulla targhetta",
        "file_instructions": [
            "Leggi il codice inventato sulla targhetta",
            "Leggi il documento inventato",
        ],
    }, files=[
        ("files", ("macchina-fittizia.png", b"fake-image", "image/png")),
        ("files", ("dati.csv", b"solo,test", "text/csv")),
    ])
    assert sent.status_code == 201
    message = sent.json()
    assert [item["status"] for item in message["attachments"]] == ["analizzato", "errore"]
    assert message["attachments"][1]["instruction"] == "Leggi il documento inventato"
    assert "Formato non supportato" in message["attachments"][1]["error"]
    assert message["observations"][0]["status"] == "non_leggibile"
    assert message["observations"][0]["instruction"] == message["content"]
    assert message["observations"][0]["version"] == "engagement-evidence-v1"
    assert client.get(f"{url}/messages").json() == [message]

    attachment_id = message["attachments"][0]["id"]
    original = client.get(f"{url}/attachments/{attachment_id}")
    assert original.content == b"fake-image"
    assert original.headers["x-content-type-options"] == "nosniff"
    assert client.get(f"/v1/engagements/{other_id}/attachments/{attachment_id}").status_code == 404
    assert client.get(f"/v1/engagements/{other_id}/messages").json() == []

    observation_id = message["observations"][0]["id"]
    assert client.patch(f"{url}/observations/{observation_id}", json={"section": "Formazione"}).status_code == 200
    assert client.get(f"{url}/messages").json()[0]["observations"][0]["section"] == "Formazione"
    assert client.patch(f"{url}/observations/{observation_id}", json={"section": "Inesistente"}).status_code == 422
    assert client.patch(f"/v1/engagements/{other_id}/observations/{observation_id}", json={"section": None}).status_code == 404


def test_note_and_failed_analysis_keep_original_without_modifying_dossier() -> None:
    engagement_id = uuid4()
    evidence = MemoryEvidenceStore()
    evidence.engagements.add(engagement_id)
    client = TestClient(create_app(store=EngagementStub(engagement_id), evidence_store=evidence))
    url = f"/v1/engagements/{engagement_id}"
    note = client.post(f"{url}/messages", data={"content": "Appunto fittizio del sopralluogo"})
    assert note.status_code == 201
    assert note.json()["observations"][0]["method"] == "appunto-originale"
    unsupported = client.post(f"{url}/messages", data={"content": "Controlla"}, files={
        "files": ("dati.xyz", b"example", "application/octet-stream")
    })
    assert unsupported.status_code == 201
    assert unsupported.json()["attachments"][0]["status"] == "errore"
    assert len(client.get(f"{url}/messages").json()) == 2
    assert client.get(f"{url}/attachments/{unsupported.json()['attachments'][0]['id']}").content == b"example"


def test_document_analysis_requires_a_source_position(monkeypatch: pytest.MonkeyPatch) -> None:
    requests: list[dict[str, object]] = []

    def create(**kwargs: object) -> SimpleNamespace:
        requests.append(kwargs)
        return SimpleNamespace(output_text='{"observations":[{"information":"Codice X",'
            '"status":"osservato","text":"Codice X indicato",'
            '"position":null,"section":"Attrezzature"}]}')

    monkeypatch.setattr(
        "ocio.engagement_evidence.OpenAI",
        lambda: SimpleNamespace(responses=SimpleNamespace(create=create)),
    )
    with pytest.raises(ValueError, match="posizione"):
        OpenAIEvidenceAnalyzer().analyze(
            b"Codice X inventato", "text/plain", "Quale codice?", ["Attrezzature"]
        )
    assert requests[0]["store"] is False
    assert "conformità" in str(requests[0]["instructions"])


@pytest.mark.integration
def test_postgres_evidence_keeps_original_and_enforces_engagement_scope() -> None:
    try:
        engine = create_engine(database_url())
        with engine.connect() as connection:
            connection.execute(text("SELECT 1 FROM osservazioni_incarico"))
    except Exception:
        pytest.skip("PostgreSQL migrato non disponibile")
    template_id, revision_id, engagement_id, other_id = (uuid4() for _ in range(4))
    try:
        with engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO modelli_fascicolo (id, nome) VALUES (:id, 'Modello fittizio')"
            ), {"id": template_id})
            connection.execute(text(
                "INSERT INTO revisioni_modello_fascicolo "
                "(id, modello_id, numero, schema_markdown) "
                "VALUES (:id, :template_id, 1, '## Attrezzature')"
            ), {"id": revision_id, "template_id": template_id})
            for identifier in (engagement_id, other_id):
                connection.execute(text(
                    "INSERT INTO incarichi (id, azienda, sede, data_riferimento, "
                    "revisione_modello_id, fascicolo_markdown) VALUES "
                    "(:id, 'Caso fittizio', 'Sede fittizia', '2026-01-01', "
                    ":revision_id, '## Attrezzature')"
                ), {"id": identifier, "revision_id": revision_id})
        store = PostgresEvidenceStore(engine)
        message = store.add_message(engagement_id, "Istruzione fittizia", [
            ("foto-fittizia.png", "image/png", b"contenuto-fittizio", "Leggi codice")
        ])
        assert message is not None
        attachment_id = UUID(message["attachments"][0]["id"])
        assert store.attachment(other_id, attachment_id) is None
        assert store.attachment(engagement_id, attachment_id) == (
            "foto-fittizia.png", "image/png", b"contenuto-fittizio"
        )
        store.record_analysis(
            engagement_id, UUID(message["id"]), attachment_id, message["content"],
            "analisi-fittizia", [{
                "information": "Codice", "status": "non_leggibile",
                "text": "Codice non leggibile", "position": "targhetta",
                "section": "Attrezzature",
            }],
        )
        reopened = store.messages(engagement_id)
        assert reopened is not None
        assert reopened[0]["attachments"][0]["status"] == "analizzato"
        observation = reopened[0]["observations"][0]
        assert observation["version"] == "engagement-evidence-v1"
        assert not store.link_section(other_id, UUID(observation["id"]), None)
    finally:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM incarichi WHERE id IN (:one, :two)"), {
                "one": engagement_id, "two": other_id,
            })
            connection.execute(text("DELETE FROM revisioni_modello_fascicolo WHERE id = :id"), {"id": revision_id})
            connection.execute(text("DELETE FROM modelli_fascicolo WHERE id = :id"), {"id": template_id})
        engine.dispose()
