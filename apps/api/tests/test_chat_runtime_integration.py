"""Opt-in end-to-end test against PostgreSQL and the real model providers."""

import os
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text

from ocio.api import PostgresStore, create_app
from ocio.chat_runtime import DEFAULT_CONFIG, RuntimeChatBackend, load_profile
from ocio.database import database_url


@pytest.mark.integration
def test_real_chat_answers_with_citations_and_complete_trace() -> None:
    required = (
        "OPENAI_API_KEY",
        "COHERE_API_KEY",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
    )
    if os.environ.get("OCIO_RUN_LIVE_CHAT_TEST") != "1" or any(
        not os.environ.get(name) for name in required
    ):
        pytest.skip("test chat live non abilitato o credenziali mancanti")

    engine = create_engine(database_url())
    client = TestClient(create_app(
        PostgresStore(engine),
        RuntimeChatBackend(engine, load_profile(DEFAULT_CONFIG, "alpha")),
    ))
    conversation_id: str | None = None
    try:
        created = client.post("/v1/conversations")
        conversation_id = created.json()["id"]
        response = client.post(
            f"/v1/conversations/{conversation_id}/messages",
            json={
                "content": (
                    "Quanti crediti sono attribuiti al rilascio della patente "
                    "digitale prevista dal D.M. 132/2024?"
                )
            },
        )

        assert response.status_code == 201
        assert response.json()["status"] == "ANSWER"
        assert response.json()["citations"]
        with engine.connect() as connection:
            trace = connection.execute(
                text("SELECT dati FROM trace_api WHERE id = :id"),
                {"id": UUID(response.json()["trace_id"])},
            ).scalar_one()
        assert set(trace) >= {"rewrite", "retrieval", "sufficiency", "generation"}
    finally:
        if conversation_id is not None:
            with engine.begin() as connection:
                parameters = {"id": UUID(conversation_id)}
                connection.execute(text(
                    "DELETE FROM trace_api WHERE messaggio_id IN "
                    "(SELECT id FROM messaggi_conversazione WHERE conversazione_id = :id)"
                ), parameters)
                connection.execute(text(
                    "DELETE FROM citazioni_api WHERE messaggio_id IN "
                    "(SELECT id FROM messaggi_conversazione WHERE conversazione_id = :id)"
                ), parameters)
                connection.execute(text(
                    "DELETE FROM messaggi_conversazione WHERE conversazione_id = :id"
                ), parameters)
                connection.execute(
                    text("DELETE FROM conversazioni WHERE id = :id"), parameters
                )
        engine.dispose()
