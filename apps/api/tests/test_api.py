"""HTTP contract tests using an in-memory store and fake model backend."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from ocio.api import PostgresStore, Reply, create_app
from ocio.database import database_url


class MemoryStore:
    def __init__(self) -> None:
        self.conversations: dict[UUID, dict[str, Any]] = {}
        self.citations: dict[UUID, dict[str, Any]] = {}
        self.feedbacks: dict[UUID, dict[str, Any]] = {}
        self.traces: dict[UUID, dict[str, Any]] = {}

    def ready(self) -> bool:
        return True

    def list_conversations(self) -> list[dict[str, Any]]:
        return [
            {
                "id": str(identifier),
                "created_at": value["created_at"],
                "message_count": len(value["messages"]),
                "last_message": (
                    value["messages"][-1]["content"] if value["messages"] else None
                ),
            }
            for identifier, value in reversed(self.conversations.items())
        ]

    def create_conversation(self, conversation_id: UUID) -> dict[str, Any]:
        value = {"id": str(conversation_id), "created_at": datetime.now(UTC), "messages": [], "case_state": {}}
        self.conversations[conversation_id] = value
        return value

    def conversation(self, conversation_id: UUID) -> dict[str, Any] | None:
        return self.conversations.get(conversation_id)

    def append_user_message(self, conversation_id: UUID, message_id: UUID, content: str) -> None:
        conversation = self.conversations.get(conversation_id)
        if conversation is None:
            from ocio.api import ApiError
            raise ApiError(404, "conversation_not_found", "Conversazione non trovata.")
        conversation["messages"].append(self._message(message_id, "user", content, None))

    def append_reply(self, conversation_id: UUID, message_id: UUID, reply: Reply, request_id: UUID) -> tuple[dict[str, Any], tuple[dict[str, Any], ...], UUID]:
        message = self._message(message_id, "assistant", reply.content, reply.status)
        self.conversations[conversation_id]["messages"].append(message)
        public = []
        for value in reply.citations:
            identifier = uuid4()
            citation = {"id": str(identifier), **value}
            self.citations[identifier] = citation
            public.append(citation)
        message["citations"] = public
        message["missing_information"] = list(reply.missing_information)
        message["conditions"] = list(reply.conditions)
        trace_id = uuid4()
        self.traces[trace_id] = {"request_id": str(request_id), **(reply.trace or {})}
        return message, tuple(public), trace_id

    def record_failure(self, message_id: UUID, request_id: UUID, error: Exception) -> None:
        self.traces[uuid4()] = {"request_id": str(request_id), "type": type(error).__name__}

    def patch_facts(self, conversation_id: UUID, facts: list[dict[str, Any]]) -> dict[str, Any]:
        state = self.conversations[conversation_id]["case_state"]
        for fact in facts:
            state[fact["name"]] = fact
        return state

    def citation(self, citation_id: UUID) -> dict[str, Any] | None:
        return self.citations.get(citation_id)

    def feedback(self, message_id: UUID, values: dict[str, Any]) -> dict[str, Any] | None:
        known = any(
            message["id"] == str(message_id) and message["role"] == "assistant"
            for conversation in self.conversations.values()
            for message in conversation["messages"]
        )
        if not known:
            return None
        current = self.feedbacks.get(message_id, {})
        current.update({key: value for key, value in values.items() if value is not None})
        result = {"message_id": str(message_id), "reason": None, "details": None, **current, "updated_at": datetime.now(UTC)}
        self.feedbacks[message_id] = result
        return result

    @staticmethod
    def _message(identifier: UUID, role: str, content: str, status: str | None) -> dict[str, Any]:
        return {"id": str(identifier), "role": role, "content": content, "status": status, "created_at": datetime.now(UTC)}


class FakeBackend:
    def __init__(self) -> None:
        self.case_state: dict[str, Any] = {}

    def answer(self, question: str, history: list[dict[str, Any]], case_state: dict[str, Any]) -> Reply:
        self.case_state = case_state
        return Reply(
            "ANSWER", "È applicabile.", ({
                "passage": "Testo ufficiale.", "document_title": "Decreto",
                "document_type": "atto_normativo", "document_urn": "urn:test",
                "document_valid_from": "2025-01-01", "document_valid_until": None,
                "sources": [{"provider": "Normattiva", "url": "https://example.test"}],
            },), trace={"query": question},
        )


def test_complete_conversation_citation_feedback_and_request_correlation() -> None:
    store = MemoryStore()
    backend = FakeBackend()
    client = TestClient(create_app(store, backend))
    request_id = str(uuid4())

    created = client.post("/v1/conversations", headers={"X-Request-ID": request_id})
    conversation_id = created.json()["id"]
    patched = client.patch(f"/v1/conversations/{conversation_id}/case-state", json={
        "facts": [{"name": "employee_count", "value": 12, "status": "confirmed"}]
    })
    response = client.post(
        f"/v1/conversations/{conversation_id}/messages",
        json={"content": "Quali obblighi si applicano?"},
        headers={"X-Request-ID": request_id},
    )

    assert created.status_code == 201
    assert patched.status_code == 200
    assert response.status_code == 201
    assert response.headers["X-Request-ID"] == request_id
    assert response.json()["request_id"] == request_id
    assert response.json()["status"] == "ANSWER"
    assert client.get("/v1/conversations").json()[0]["message_count"] == 2
    assert backend.case_state["employee_count"]["value"] == 12
    citation_id = response.json()["citations"][0]["id"]
    assert client.get(f"/v1/citations/{citation_id}").json()["passage"] == "Testo ufficiale."
    reopened = client.get(f"/v1/conversations/{conversation_id}").json()
    assert reopened["messages"][-1]["citations"][0]["id"] == citation_id

    message_id = response.json()["message"]["id"]
    assert client.post(f"/v1/messages/{message_id}/feedback", json={"rating": 4}).status_code == 200
    detailed = client.post(f"/v1/messages/{message_id}/feedback", json={"reason": "citation"})
    assert detailed.json()["reason"] == "citation"


def test_errors_have_stable_envelope_and_request_id() -> None:
    client = TestClient(create_app(MemoryStore(), FakeBackend()))

    response = client.get(f"/v1/conversations/{uuid4()}")
    invalid = client.post("/v1/conversations", headers={"X-Request-ID": "secret-key"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "conversation_not_found"
    UUID(response.json()["request_id"])
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "invalid_request_id"


def test_openapi_documents_answer_abstention_and_error_envelopes() -> None:
    schema = create_app(MemoryStore(), FakeBackend()).openapi()
    operation = schema["paths"]["/v1/conversations/{conversation_id}/messages"]["post"]

    assert "anyOf" in operation["responses"]["201"]["content"]["application/json"]["schema"]
    assert operation["responses"]["422"]["content"]["application/json"]["schema"]["$ref"].endswith("ErrorEnvelope")


@pytest.mark.integration
def test_conversation_flow_is_persisted_in_postgres() -> None:
    try:
        engine = create_engine(database_url())
        with engine.connect() as connection:
            connection.execute(text("SELECT 1 FROM conversazioni"))
    except Exception:
        pytest.skip("PostgreSQL migrato non disponibile")
    client = TestClient(create_app(PostgresStore(engine), FakeBackend()))
    conversation_id: str | None = None
    try:
        created = client.post("/v1/conversations")
        conversation_id = created.json()["id"]
        response = client.post(
            f"/v1/conversations/{conversation_id}/messages",
            json={"content": "Quali obblighi si applicano?"},
        )
        citation_id = response.json()["citations"][0]["id"]

        assert response.status_code == 201
        assert len(client.get(f"/v1/conversations/{conversation_id}").json()["messages"]) == 2
        assert client.get(f"/v1/citations/{citation_id}").status_code == 200
        with engine.connect() as connection:
            request_id = response.json()["request_id"]
            assert connection.execute(
                text("SELECT count(*) FROM trace_api WHERE request_id = :id"),
                {"id": UUID(request_id)},
            ).scalar_one() == 1
    finally:
        if conversation_id is not None:
            with engine.begin() as connection:
                parameters = {"id": UUID(conversation_id)}
                connection.execute(text(
                    "DELETE FROM feedback_messaggi WHERE messaggio_id IN "
                    "(SELECT id FROM messaggi_conversazione WHERE conversazione_id = :id)"
                ), parameters)
                connection.execute(text(
                    "DELETE FROM trace_api WHERE messaggio_id IN "
                    "(SELECT id FROM messaggi_conversazione WHERE conversazione_id = :id)"
                ), parameters)
                connection.execute(text(
                    "DELETE FROM citazioni_api WHERE messaggio_id IN "
                    "(SELECT id FROM messaggi_conversazione WHERE conversazione_id = :id)"
                ), parameters)
                connection.execute(text("DELETE FROM fatti_conversazione WHERE conversazione_id = :id"), parameters)
                connection.execute(text("DELETE FROM messaggi_conversazione WHERE conversazione_id = :id"), parameters)
                connection.execute(text("DELETE FROM conversazioni WHERE id = :id"), parameters)
        engine.dispose()
