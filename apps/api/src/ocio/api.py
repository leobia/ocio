"""Versioned HTTP boundary for the OCIO modular monolith."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any, Literal, Protocol
from uuid import UUID, uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Engine, create_engine, text

from ocio.database import database_url

LOGGER = logging.getLogger("ocio.api")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class Reply:
    """Provider-independent result consumed by the HTTP application service."""

    status: Literal["ANSWER", "ABSTAIN"]
    content: str
    citations: tuple[Mapping[str, Any], ...] = ()
    missing_information: tuple[str, ...] = ()
    trace: Mapping[str, Any] | None = None


class ChatBackend(Protocol):
    def answer(
        self,
        question: str,
        history: Sequence[Mapping[str, Any]],
        case_state: Mapping[str, Mapping[str, Any]],
    ) -> Reply: ...


class UnconfiguredBackend:
    def answer(
        self,
        question: str,
        history: Sequence[Mapping[str, Any]],
        case_state: Mapping[str, Mapping[str, Any]],
    ) -> Reply:
        raise ApiError(503, "chat_unavailable", "Il servizio chat non è configurato.")


class Store(Protocol):
    def ready(self) -> bool: ...
    def create_conversation(self, conversation_id: UUID) -> Mapping[str, Any]: ...
    def conversation(self, conversation_id: UUID) -> Mapping[str, Any] | None: ...
    def append_user_message(
        self, conversation_id: UUID, message_id: UUID, content: str
    ) -> None: ...
    def append_reply(
        self, conversation_id: UUID, message_id: UUID, reply: Reply,
        request_id: UUID,
    ) -> tuple[Mapping[str, Any], tuple[Mapping[str, Any], ...], UUID]: ...
    def record_failure(self, message_id: UUID, request_id: UUID, error: Exception) -> None: ...
    def patch_facts(
        self, conversation_id: UUID, facts: Sequence[Mapping[str, Any]]
    ) -> Mapping[str, Mapping[str, Any]]: ...
    def citation(self, citation_id: UUID) -> Mapping[str, Any] | None: ...
    def feedback(
        self, message_id: UUID, values: Mapping[str, Any]
    ) -> Mapping[str, Any] | None: ...


class PostgresStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def ready(self) -> bool:
        try:
            with self.engine.connect() as connection:
                return connection.execute(text("SELECT 1")).scalar_one() == 1
        except Exception:
            return False

    def create_conversation(self, conversation_id: UUID) -> Mapping[str, Any]:
        with self.engine.begin() as connection:
            row = connection.execute(text(
                "INSERT INTO conversazioni (id) VALUES (:id) "
                "RETURNING id, creata_il"
            ), {"id": conversation_id}).mappings().one()
        return {"id": str(row["id"]), "created_at": row["creata_il"]}

    def conversation(self, conversation_id: UUID) -> Mapping[str, Any] | None:
        with self.engine.connect() as connection:
            conversation = connection.execute(text(
                "SELECT id, creata_il FROM conversazioni WHERE id = :id"
            ), {"id": conversation_id}).mappings().one_or_none()
            if conversation is None:
                return None
            messages = [dict(row) for row in connection.execute(text(
                "SELECT id, ruolo, contenuto, stato, creato_il "
                "FROM messaggi_conversazione WHERE conversazione_id = :id "
                "ORDER BY creato_il, id"
            ), {"id": conversation_id}).mappings()]
            state = self._case_state(connection, conversation_id)
        return {
            "id": str(conversation["id"]),
            "created_at": conversation["creata_il"],
            "messages": [_message_dict(item) for item in messages],
            "case_state": state,
        }

    def append_user_message(
        self, conversation_id: UUID, message_id: UUID, content: str
    ) -> None:
        with self.engine.begin() as connection:
            exists = connection.execute(text(
                "SELECT 1 FROM conversazioni WHERE id = :id"
            ), {"id": conversation_id}).scalar_one_or_none()
            if exists is None:
                raise ApiError(404, "conversation_not_found", "Conversazione non trovata.")
            connection.execute(text(
                "INSERT INTO messaggi_conversazione "
                "(id, conversazione_id, ruolo, contenuto) "
                "VALUES (:id, :conversation_id, 'user', :content)"
            ), {"id": message_id, "conversation_id": conversation_id, "content": content})

    def append_reply(
        self, conversation_id: UUID, message_id: UUID, reply: Reply,
        request_id: UUID,
    ) -> tuple[Mapping[str, Any], tuple[Mapping[str, Any], ...], UUID]:
        trace_id = uuid4()
        public_citations: list[Mapping[str, Any]] = []
        with self.engine.begin() as connection:
            message = connection.execute(text(
                "INSERT INTO messaggi_conversazione "
                "(id, conversazione_id, ruolo, contenuto, stato) "
                "VALUES (:id, :conversation_id, 'assistant', :content, :status) "
                "RETURNING id, ruolo, contenuto, stato, creato_il"
            ), {
                "id": message_id, "conversation_id": conversation_id,
                "content": reply.content, "status": reply.status,
            }).mappings().one()
            for value in reply.citations:
                citation_id = uuid4()
                data = _json_value(value)
                if isinstance(data, dict):
                    data.pop("citation_id", None)
                connection.execute(text(
                    "INSERT INTO citazioni_api (id, messaggio_id, dati) "
                    "VALUES (:id, :message_id, CAST(:data AS jsonb))"
                ), {"id": citation_id, "message_id": message_id, "data": json.dumps(data)})
                public_citations.append({"id": str(citation_id), **data})
            connection.execute(text(
                "INSERT INTO trace_api (id, messaggio_id, request_id, dati) "
                "VALUES (:id, :message_id, :request_id, CAST(:data AS jsonb))"
            ), {
                "id": trace_id, "message_id": message_id, "request_id": request_id,
                "data": json.dumps(_json_value(reply.trace or {})),
            })
        return _message_dict(dict(message)), tuple(public_citations), trace_id

    def record_failure(self, message_id: UUID, request_id: UUID, error: Exception) -> None:
        with self.engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO trace_api (id, messaggio_id, request_id, dati) "
                "VALUES (:id, :message_id, :request_id, CAST(:data AS jsonb))"
            ), {
                "id": uuid4(), "message_id": message_id, "request_id": request_id,
                "data": json.dumps({"status": "ERROR", "type": type(error).__name__}),
            })

    def patch_facts(
        self, conversation_id: UUID, facts: Sequence[Mapping[str, Any]]
    ) -> Mapping[str, Mapping[str, Any]]:
        with self.engine.begin() as connection:
            if connection.execute(text(
                "SELECT 1 FROM conversazioni WHERE id = :id"
            ), {"id": conversation_id}).scalar_one_or_none() is None:
                raise ApiError(404, "conversation_not_found", "Conversazione non trovata.")
            for fact in facts:
                source_message_id = fact.get("source_message_id")
                if source_message_id is not None and connection.execute(text(
                    "SELECT 1 FROM messaggi_conversazione "
                    "WHERE id = :message_id AND conversazione_id = :conversation_id"
                ), {
                    "message_id": source_message_id,
                    "conversation_id": conversation_id,
                }).scalar_one_or_none() is None:
                    raise ApiError(
                        422, "invalid_fact_source",
                        "Il messaggio sorgente non appartiene alla conversazione.",
                    )
                connection.execute(text(
                    "INSERT INTO fatti_conversazione "
                    "(id, conversazione_id, nome, valore, stato, messaggio_sorgente_id) "
                    "VALUES (:id, :conversation_id, :name, CAST(:value AS jsonb), "
                    ":status, :source_message_id)"
                ), {
                    "id": uuid4(), "conversation_id": conversation_id,
                    "name": fact["name"], "value": json.dumps(fact["value"]),
                    "status": fact["status"], "source_message_id": source_message_id,
                })
            return self._case_state(connection, conversation_id)

    def citation(self, citation_id: UUID) -> Mapping[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(text(
                "SELECT id, messaggio_id, dati FROM citazioni_api WHERE id = :id"
            ), {"id": citation_id}).mappings().one_or_none()
        return None if row is None else {
            "id": str(row["id"]), "message_id": str(row["messaggio_id"]), **row["dati"]
        }

    def feedback(
        self, message_id: UUID, values: Mapping[str, Any]
    ) -> Mapping[str, Any] | None:
        with self.engine.begin() as connection:
            exists = connection.execute(text(
                "SELECT 1 FROM messaggi_conversazione "
                "WHERE id = :id AND ruolo = 'assistant'"
            ), {"id": message_id}).scalar_one_or_none()
            if exists is None:
                return None
            current = connection.execute(text(
                "SELECT rating FROM feedback_messaggi WHERE messaggio_id = :id"
            ), {"id": message_id}).scalar_one_or_none()
            rating = values.get("rating") or current
            if rating is None:
                raise ApiError(
                    422, "rating_required", "Il primo feedback richiede un rating."
                )
            row = connection.execute(text(
                "INSERT INTO feedback_messaggi (messaggio_id, rating, reason, details) "
                "VALUES (:id, :rating, :reason, :details) "
                "ON CONFLICT (messaggio_id) DO UPDATE SET "
                "rating = EXCLUDED.rating, "
                "reason = COALESCE(EXCLUDED.reason, feedback_messaggi.reason), "
                "details = COALESCE(EXCLUDED.details, feedback_messaggi.details), "
                "aggiornato_il = now() "
                "RETURNING messaggio_id, rating, reason, details, aggiornato_il"
            ), {"id": message_id, **values, "rating": rating}).mappings().one()
        return {
            "message_id": str(row["messaggio_id"]), "rating": row["rating"],
            "reason": row["reason"], "details": row["details"],
            "updated_at": row["aggiornato_il"],
        }

    def _case_state(self, connection: Any, conversation_id: UUID) -> dict[str, Any]:
        rows = connection.execute(text(
            "SELECT DISTINCT ON (nome) nome, valore, stato, "
            "messaggio_sorgente_id, creato_il FROM fatti_conversazione "
            "WHERE conversazione_id = :id ORDER BY nome, creato_il DESC, id DESC"
        ), {"id": conversation_id}).mappings()
        return {
            str(row["nome"]): {
                "value": row["valore"], "status": row["stato"],
                "source_message_id": (
                    str(row["messaggio_sorgente_id"])
                    if row["messaggio_sorgente_id"] else None
                ),
                "updated_at": row["creato_il"],
            }
            for row in rows
        }


class MessageInput(BaseModel):
    content: str = Field(min_length=1, max_length=10_000)


class FactPatch(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    value: str | int | bool | date | list[str] | None
    status: Literal["confirmed", "inferred", "unknown"] = "confirmed"
    source_message_id: UUID | None = None

    @model_validator(mode="after")
    def validate_value(self) -> FactPatch:
        if (self.status == "unknown") != (self.value is None):
            raise ValueError("unknown richiede value null; gli altri stati un valore")
        return self


class CaseStatePatch(BaseModel):
    facts: list[FactPatch] = Field(min_length=1)


class FeedbackInput(BaseModel):
    rating: int | None = Field(default=None, ge=1, le=5)
    reason: str | None = Field(default=None, max_length=200)
    details: str | None = Field(default=None, max_length=2_000)

    @model_validator(mode="after")
    def at_least_one_value(self) -> FeedbackInput:
        if self.rating is None and self.reason is None and self.details is None:
            raise ValueError("specificare almeno un campo di feedback")
        return self


class MessageOutput(BaseModel):
    id: UUID
    role: Literal["user", "assistant"]
    content: str
    status: Literal["ANSWER", "ABSTAIN"] | None
    created_at: datetime


class CitationOutput(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: UUID
    passage: str
    document_title: str
    document_type: str
    document_urn: str | None = None
    document_valid_from: str | None = None
    document_valid_until: str | None = None
    sources: list[dict[str, Any]] = []


class AnswerResponse(BaseModel):
    status: Literal["ANSWER"]
    message: MessageOutput
    citations: list[CitationOutput]
    missing_information: list[str]
    trace_id: UUID
    request_id: UUID


class AbstentionResponse(BaseModel):
    status: Literal["ABSTAIN"]
    message: MessageOutput
    citations: list[CitationOutput]
    missing_information: list[str]
    trace_id: UUID
    request_id: UUID


class ErrorItem(BaseModel):
    code: str
    message: str


class ErrorEnvelope(BaseModel):
    error: ErrorItem
    request_id: UUID


ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorEnvelope}, 404: {"model": ErrorEnvelope},
    422: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope},
    502: {"model": ErrorEnvelope}, 503: {"model": ErrorEnvelope},
}


def create_app(
    store: Store | None = None, backend: ChatBackend | None = None
) -> FastAPI:
    app = FastAPI(
        title="OCIO API", version="1.0.0",
        responses={400: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}},
    )
    selected_store = store or PostgresStore(create_engine(database_url()))
    selected_backend = backend or UnconfiguredBackend()

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next: Any) -> Any:
        supplied = request.headers.get("X-Request-ID")
        try:
            request_id = UUID(supplied) if supplied else uuid4()
        except ValueError:
            request_id = uuid4()
            response = _error(400, "invalid_request_id", "X-Request-ID deve essere un UUID.", request_id)
        else:
            request.state.request_id = request_id
            response = await call_next(request)
        response.headers["X-Request-ID"] = str(request_id)
        LOGGER.info("request completed", extra={
            "request_id": str(request_id), "method": request.method,
            "path": request.url.path, "status_code": response.status_code,
        })
        return response

    @app.exception_handler(ApiError)
    async def api_error(request: Request, error: ApiError) -> JSONResponse:
        return _error(error.status, error.code, error.message, request.state.request_id)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError) -> JSONResponse:
        return _error(422, "validation_error", "Richiesta non valida.", request.state.request_id)

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, error: Exception) -> JSONResponse:
        LOGGER.error(
            "unexpected request failure",
            extra={
                "request_id": str(request.state.request_id),
                "error_type": type(error).__name__,
            },
        )
        return _error(
            500, "internal_error", "Errore interno del servizio.",
            request.state.request_id,
        )

    @app.get("/health/live")
    def live() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health/ready", responses={503: {"model": ErrorEnvelope}})
    def ready(request: Request) -> dict[str, str]:
        if not selected_store.ready():
            raise ApiError(503, "not_ready", "Il database non è disponibile.")
        return {"status": "ok"}

    @app.post("/v1/conversations", status_code=201)
    def create_conversation() -> Mapping[str, Any]:
        result = dict(selected_store.create_conversation(uuid4()))
        result.setdefault("messages", [])
        result.setdefault("case_state", {})
        return result

    @app.get("/v1/conversations/{conversation_id}", responses=ERROR_RESPONSES)
    def get_conversation(conversation_id: UUID) -> Mapping[str, Any]:
        result = selected_store.conversation(conversation_id)
        if result is None:
            raise ApiError(404, "conversation_not_found", "Conversazione non trovata.")
        return result

    @app.post(
        "/v1/conversations/{conversation_id}/messages", status_code=201,
        responses=ERROR_RESPONSES, response_model=AnswerResponse | AbstentionResponse,
    )
    def add_message(
        conversation_id: UUID, payload: MessageInput, request: Request
    ) -> Mapping[str, Any]:
        user_message_id = uuid4()
        selected_store.append_user_message(conversation_id, user_message_id, payload.content)
        snapshot = selected_store.conversation(conversation_id)
        assert snapshot is not None
        try:
            reply = selected_backend.answer(
                payload.content, snapshot["messages"], snapshot["case_state"]
            )
        except ApiError as error:
            selected_store.record_failure(user_message_id, request.state.request_id, error)
            raise
        except Exception as error:
            selected_store.record_failure(user_message_id, request.state.request_id, error)
            raise ApiError(502, "provider_failure", "Il servizio di risposta non è disponibile.") from error
        message, citations, trace_id = selected_store.append_reply(
            conversation_id, uuid4(), reply, request.state.request_id
        )
        return {
            "status": reply.status, "message": message,
            "citations": citations, "missing_information": reply.missing_information,
            "trace_id": str(trace_id), "request_id": str(request.state.request_id),
        }

    @app.patch(
        "/v1/conversations/{conversation_id}/case-state", responses=ERROR_RESPONSES
    )
    def patch_case_state(
        conversation_id: UUID, payload: CaseStatePatch
    ) -> Mapping[str, Any]:
        facts = [fact.model_dump(mode="json") for fact in payload.facts]
        return {"case_state": selected_store.patch_facts(conversation_id, facts)}

    @app.get(
        "/v1/citations/{citation_id}", responses=ERROR_RESPONSES,
        response_model=CitationOutput,
    )
    def get_citation(citation_id: UUID) -> Mapping[str, Any]:
        result = selected_store.citation(citation_id)
        if result is None:
            raise ApiError(404, "citation_not_found", "Citazione non trovata.")
        return result

    @app.post("/v1/messages/{message_id}/feedback", responses=ERROR_RESPONSES)
    def submit_feedback(
        message_id: UUID, payload: FeedbackInput
    ) -> Mapping[str, Any]:
        result = selected_store.feedback(message_id, payload.model_dump())
        if result is None:
            raise ApiError(404, "message_not_found", "Messaggio assistente non trovato.")
        return result

    return app


def _message_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]), "role": row["ruolo"], "content": row["contenuto"],
        "status": row["stato"], "created_at": row["creato_il"],
    }


def _json_value(value: Any) -> Any:
    if hasattr(value, "__dataclass_fields__"):
        return _json_value(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, (datetime, date, UUID)):
        return str(value)
    return value


def _error(status: int, code: str, message: str, request_id: UUID) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {"code": code, "message": message},
            "request_id": str(request_id),
        },
    )
