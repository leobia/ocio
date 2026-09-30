"""Versioned HTTP boundary for the OCIO modular monolith."""

from __future__ import annotations

import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any, Literal, Protocol
from urllib.parse import quote
from uuid import UUID, uuid4

from fastapi import FastAPI, File, Form, Request, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import Engine, create_engine, text

from ocio.database import database_url
from ocio.dossier import (
    exportable_dossier,
    migration,
    section_titles,
    validate_instructions,
)
from ocio.dossier_agent import DossierAgentService, PostgresAgentStore, StateConflict
from ocio.engagement_evidence import (
    SUPPORTED,
    EvidenceAnalyzer,
    EvidenceStore,
    MemoryEvidenceStore,
    OpenAIEvidenceAnalyzer,
    PostgresEvidenceStore,
)

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
    conditions: tuple[str, ...] = ()
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
    def list_conversations(self) -> Sequence[Mapping[str, Any]]: ...
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
    def list_templates(self) -> Sequence[Mapping[str, Any]]: ...
    def create_template(
        self, template_id: UUID, revision_id: UUID, values: Mapping[str, Any]
    ) -> Mapping[str, Any]: ...
    def revise_template(
        self, template_id: UUID, revision_id: UUID, values: Mapping[str, Any]
    ) -> Mapping[str, Any] | None: ...
    def list_engagements(self) -> Sequence[Mapping[str, Any]]: ...
    def create_engagement(
        self, engagement_id: UUID, values: Mapping[str, Any]
    ) -> Mapping[str, Any] | None: ...
    def engagement(self, engagement_id: UUID) -> Mapping[str, Any] | None: ...
    def update_dossier(
        self, engagement_id: UUID, markdown: str
    ) -> Mapping[str, Any] | None: ...
    def apply_migration(
        self, engagement_id: UUID, migration_id: UUID
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

    def list_conversations(self) -> Sequence[Mapping[str, Any]]:
        with self.engine.connect() as connection:
            rows = connection.execute(text(
                "SELECT c.id, c.creata_il, count(m.id) AS message_count, "
                "(array_agg(m.contenuto ORDER BY m.creato_il DESC, m.id DESC) "
                "FILTER (WHERE m.id IS NOT NULL))[1] AS last_message "
                "FROM conversazioni c LEFT JOIN messaggi_conversazione m "
                "ON m.conversazione_id = c.id GROUP BY c.id, c.creata_il "
                "ORDER BY c.creata_il DESC"
            )).mappings()
            return tuple({
                "id": str(row["id"]), "created_at": row["creata_il"],
                "message_count": row["message_count"],
                "last_message": row["last_message"],
            } for row in rows)

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
                "SELECT id, ruolo, contenuto, stato, creato_il, metadati "
                "FROM messaggi_conversazione WHERE conversazione_id = :id "
                "ORDER BY creato_il, id"
            ), {"id": conversation_id}).mappings()]
            citation_rows = connection.execute(text(
                "SELECT id, messaggio_id, dati FROM citazioni_api "
                "WHERE messaggio_id IN (SELECT id FROM messaggi_conversazione "
                "WHERE conversazione_id = :id) ORDER BY creata_il, id"
            ), {"id": conversation_id}).mappings()
            citations: dict[UUID, list[dict[str, Any]]] = {}
            for row in citation_rows:
                citations.setdefault(row["messaggio_id"], []).append({
                    "id": str(row["id"]), **row["dati"],
                })
            state = self._case_state(connection, conversation_id)
        return {
            "id": str(conversation["id"]),
            "created_at": conversation["creata_il"],
            "messages": [
                {
                    **_message_dict(item),
                    "citations": citations.get(item["id"], []),
                    "missing_information": item["metadati"].get(
                        "missing_information", []
                    ),
                    "conditions": item["metadati"].get("conditions", []),
                }
                for item in messages
            ],
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
                "(id, conversazione_id, ruolo, contenuto, stato, metadati) "
                "VALUES (:id, :conversation_id, 'assistant', :content, :status, "
                "CAST(:metadata AS jsonb)) "
                "RETURNING id, ruolo, contenuto, stato, creato_il"
            ), {
                "id": message_id, "conversation_id": conversation_id,
                "content": reply.content, "status": reply.status,
                "metadata": json.dumps({
                    "missing_information": reply.missing_information,
                    "conditions": reply.conditions,
                }),
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

    def list_templates(self) -> Sequence[Mapping[str, Any]]:
        with self.engine.connect() as connection:
            templates = connection.execute(text(
                "SELECT id, nome, predefinito, creato_il FROM modelli_fascicolo "
                "ORDER BY predefinito DESC, nome"
            )).mappings().all()
            revisions = connection.execute(text(
                "SELECT id, modello_id, numero, schema_markdown, indicazioni, pertinenza, creata_il "
                "FROM revisioni_modello_fascicolo ORDER BY modello_id, numero"
            )).mappings().all()
        by_template: dict[UUID, list[dict[str, Any]]] = {}
        for row in revisions:
            by_template.setdefault(row["modello_id"], []).append(_template_revision(dict(row)))
        return tuple({
            "id": str(row["id"]), "name": row["nome"],
            "is_default": row["predefinito"], "created_at": row["creato_il"],
            "revisions": by_template.get(row["id"], []),
        } for row in templates)

    def create_template(
        self, template_id: UUID, revision_id: UUID, values: Mapping[str, Any]
    ) -> Mapping[str, Any]:
        with self.engine.begin() as connection:
            template = connection.execute(text(
                "INSERT INTO modelli_fascicolo (id, nome) VALUES (:id, :name) "
                "RETURNING id, nome, predefinito, creato_il"
            ), {"id": template_id, **values}).mappings().one()
            revision = connection.execute(text(
                "INSERT INTO revisioni_modello_fascicolo "
                "(id, modello_id, numero, schema_markdown, indicazioni, pertinenza) "
                "VALUES (:id, :template_id, 1, :markdown, CAST(:instructions AS jsonb), "
                "CAST(:relevance_guidance AS jsonb)) "
                "RETURNING id, modello_id, numero, schema_markdown, indicazioni, pertinenza, creata_il"
            ), {
                "id": revision_id, "template_id": template_id,
                "markdown": values["markdown"],
                "instructions": json.dumps(values["instructions"]),
                "relevance_guidance": json.dumps(values["relevance_guidance"]),
            }).mappings().one()
        return {
            "id": str(template["id"]), "name": template["nome"],
            "is_default": template["predefinito"], "created_at": template["creato_il"],
            "revisions": [_template_revision(dict(revision))],
        }

    def revise_template(
        self, template_id: UUID, revision_id: UUID, values: Mapping[str, Any]
    ) -> Mapping[str, Any] | None:
        with self.engine.begin() as connection:
            template = connection.execute(text(
                "SELECT id FROM modelli_fascicolo WHERE id = :id FOR UPDATE"
            ), {"id": template_id}).scalar_one_or_none()
            if template is None:
                return None
            number = connection.execute(text(
                "SELECT COALESCE(max(numero), 0) + 1 FROM revisioni_modello_fascicolo "
                "WHERE modello_id = :id"
            ), {"id": template_id}).scalar_one()
            revision = connection.execute(text(
                "INSERT INTO revisioni_modello_fascicolo "
                "(id, modello_id, numero, schema_markdown, indicazioni, pertinenza) "
                "VALUES (:id, :template_id, :number, :markdown, CAST(:instructions AS jsonb), "
                "CAST(:relevance_guidance AS jsonb)) "
                "RETURNING id, modello_id, numero, schema_markdown, indicazioni, pertinenza, creata_il"
            ), {
                "id": revision_id, "template_id": template_id, "number": number,
                "markdown": values["markdown"],
                "instructions": json.dumps(values["instructions"]),
                "relevance_guidance": json.dumps(values["relevance_guidance"]),
            }).mappings().one()
            engagements = connection.execute(text(
                "SELECT i.id, i.revisione_modello_id, i.fascicolo_markdown "
                "FROM incarichi i JOIN revisioni_modello_fascicolo r "
                "ON r.id = i.revisione_modello_id WHERE r.modello_id = :id"
            ), {"id": template_id}).mappings().all()
            for item in engagements:
                proposed, diff = migration(item["fascicolo_markdown"], values["markdown"])
                connection.execute(text(
                    "UPDATE migrazioni_fascicolo SET stato = 'superata' "
                    "WHERE incarico_id = :engagement_id AND stato = 'proposta'"
                ), {"engagement_id": item["id"]})
                connection.execute(text(
                    "INSERT INTO migrazioni_fascicolo "
                    "(id, incarico_id, revisione_origine_id, revisione_destinazione_id, "
                    "fascicolo_origine, fascicolo_proposto, diff) VALUES "
                    "(:id, :engagement_id, :source_id, :target_id, :current, :proposed, :diff)"
                ), {
                    "id": uuid4(), "engagement_id": item["id"],
                    "source_id": item["revisione_modello_id"], "target_id": revision_id,
                    "current": item["fascicolo_markdown"], "proposed": proposed, "diff": diff,
                })
        return _template_revision(dict(revision))

    def list_engagements(self) -> Sequence[Mapping[str, Any]]:
        with self.engine.connect() as connection:
            rows = connection.execute(text(
                "SELECT i.id, i.azienda, i.sede, i.data_riferimento, i.creato_il, "
                "m.nome AS modello, r.numero AS revisione, "
                "EXISTS (SELECT 1 FROM migrazioni_fascicolo x "
                "WHERE x.incarico_id = i.id AND x.stato = 'proposta') AS migrazione_pendente "
                "FROM incarichi i JOIN revisioni_modello_fascicolo r "
                "ON r.id = i.revisione_modello_id JOIN modelli_fascicolo m "
                "ON m.id = r.modello_id ORDER BY i.creato_il DESC"
            )).mappings()
            return tuple(_engagement_summary(dict(row)) for row in rows)

    def create_engagement(
        self, engagement_id: UUID, values: Mapping[str, Any]
    ) -> Mapping[str, Any] | None:
        with self.engine.begin() as connection:
            revision = connection.execute(text(
                "SELECT schema_markdown FROM revisioni_modello_fascicolo WHERE id = :id"
            ), {"id": values["template_revision_id"]}).scalar_one_or_none()
            if revision is None:
                return None
            connection.execute(text(
                "INSERT INTO incarichi (id, azienda, sede, data_riferimento, "
                "revisione_modello_id, fascicolo_markdown) VALUES "
                "(:id, :company, :site, :reference_date, :template_revision_id, :markdown)"
            ), {"id": engagement_id, "markdown": revision, **values})
            connection.execute(text(
                "INSERT INTO revisioni_fascicolo (id, incarico_id, numero, "
                "revisione_modello_id, fascicolo_markdown, motivo) VALUES "
                "(:id, :engagement_id, 1, :revision_id, :markdown, 'creazione')"
            ), {
                "id": uuid4(), "engagement_id": engagement_id,
                "revision_id": values["template_revision_id"], "markdown": revision,
            })
            for title in dict.fromkeys(section_titles(revision)):
                connection.execute(text(
                    "INSERT INTO pertinenza_sezioni (incarico_id, sezione, stato, motivo, origine) "
                    "VALUES (:id, :section, 'da_valutare', 'Sezione del modello adottato.', 'sistema')"
                ), {"id": engagement_id, "section": title})
            return self._engagement(connection, engagement_id)

    def engagement(self, engagement_id: UUID) -> Mapping[str, Any] | None:
        with self.engine.connect() as connection:
            return self._engagement(connection, engagement_id)

    def update_dossier(
        self, engagement_id: UUID, markdown: str
    ) -> Mapping[str, Any] | None:
        with self.engine.begin() as connection:
            current = connection.execute(text(
                "SELECT revisione_modello_id FROM incarichi WHERE id = :id FOR UPDATE"
            ), {"id": engagement_id}).scalar_one_or_none()
            if current is None:
                return None
            connection.execute(text(
                "UPDATE incarichi SET fascicolo_markdown = :markdown, aggiornato_il = now(), "
                "versione_stato = versione_stato + 1 "
                "WHERE id = :id"
            ), {"id": engagement_id, "markdown": markdown})
            proposals = connection.execute(text(
                "SELECT x.id, r.schema_markdown FROM migrazioni_fascicolo x "
                "JOIN revisioni_modello_fascicolo r ON r.id = x.revisione_destinazione_id "
                "WHERE x.incarico_id = :id AND x.stato = 'proposta'"
            ), {"id": engagement_id}).mappings().all()
            for proposal in proposals:
                proposed, diff = migration(markdown, proposal["schema_markdown"])
                connection.execute(text(
                    "UPDATE migrazioni_fascicolo SET fascicolo_origine = :current, "
                    "fascicolo_proposto = :proposed, diff = :diff WHERE id = :id"
                ), {
                    "id": proposal["id"], "current": markdown,
                    "proposed": proposed, "diff": diff,
                })
            self._append_dossier_revision(
                connection, engagement_id, current, markdown, "modifica_manuale"
            )
            for title in dict.fromkeys(section_titles(markdown)):
                connection.execute(text(
                    "INSERT INTO pertinenza_sezioni (incarico_id, sezione, stato, motivo, origine) "
                    "VALUES (:id, :section, 'da_valutare', 'Sezione aggiunta dall’operatore.', 'sistema') "
                    "ON CONFLICT (incarico_id, sezione) DO NOTHING"
                ), {"id": engagement_id, "section": title})
            return self._engagement(connection, engagement_id)

    def apply_migration(
        self, engagement_id: UUID, migration_id: UUID
    ) -> Mapping[str, Any] | None:
        with self.engine.begin() as connection:
            item = connection.execute(text(
                "SELECT id, revisione_origine_id, revisione_destinazione_id, fascicolo_origine, "
                "fascicolo_proposto FROM migrazioni_fascicolo "
                "WHERE id = :migration_id AND incarico_id = :engagement_id "
                "AND stato = 'proposta'"
            ), {"migration_id": migration_id, "engagement_id": engagement_id}).mappings().one_or_none()
            if item is None:
                return None
            updated = connection.execute(text(
                "UPDATE incarichi SET revisione_modello_id = :target, "
                "fascicolo_markdown = :markdown, aggiornato_il = now(), "
                "versione_stato = versione_stato + 1 "
                "WHERE id = :id AND revisione_modello_id = :source "
                "AND fascicolo_markdown = :current RETURNING id"
            ), {
                "id": engagement_id, "source": item["revisione_origine_id"],
                "target": item["revisione_destinazione_id"],
                "current": item["fascicolo_origine"],
                "markdown": item["fascicolo_proposto"],
            }).scalar_one_or_none()
            if updated is None:
                raise ApiError(409, "stale_migration", "La proposta non parte dalla revisione corrente.")
            connection.execute(text(
                "UPDATE migrazioni_fascicolo SET stato = 'applicata', applicata_il = now() "
                "WHERE id = :id"
            ), {"id": migration_id})
            self._append_dossier_revision(
                connection, engagement_id, item["revisione_destinazione_id"],
                item["fascicolo_proposto"], "migrazione",
            )
            for title in dict.fromkeys(section_titles(item["fascicolo_proposto"])):
                connection.execute(text(
                    "INSERT INTO pertinenza_sezioni (incarico_id, sezione, stato, motivo, origine) "
                    "VALUES (:id, :section, 'da_valutare', 'Sezione introdotta dal modello.', 'sistema') "
                    "ON CONFLICT (incarico_id, sezione) DO NOTHING"
                ), {"id": engagement_id, "section": title})
            return self._engagement(connection, engagement_id)

    @staticmethod
    def _append_dossier_revision(
        connection: Any, engagement_id: UUID, template_revision_id: UUID,
        markdown: str, reason: str,
    ) -> None:
        connection.execute(text(
            "INSERT INTO revisioni_fascicolo (id, incarico_id, numero, "
            "revisione_modello_id, fascicolo_markdown, motivo) SELECT "
            ":id, :engagement_id, COALESCE(max(numero), 0) + 1, :revision_id, "
            ":markdown, :reason FROM revisioni_fascicolo WHERE incarico_id = :engagement_id"
        ), {
            "id": uuid4(), "engagement_id": engagement_id,
            "revision_id": template_revision_id, "markdown": markdown, "reason": reason,
        })

    @staticmethod
    def _engagement(connection: Any, engagement_id: UUID) -> Mapping[str, Any] | None:
        row = connection.execute(text(
            "SELECT i.id, i.azienda, i.sede, i.data_riferimento, i.fascicolo_markdown, "
            "i.creato_il, i.aggiornato_il, i.stato, i.versione_stato, "
            "m.id AS modello_id, m.nome AS modello, "
            "r.id AS revisione_id, r.numero AS revisione, r.indicazioni, r.pertinenza "
            "FROM incarichi i JOIN revisioni_modello_fascicolo r "
            "ON r.id = i.revisione_modello_id JOIN modelli_fascicolo m ON m.id = r.modello_id "
            "WHERE i.id = :id"
        ), {"id": engagement_id}).mappings().one_or_none()
        if row is None:
            return None
        history = connection.execute(text(
            "SELECT id, numero, revisione_modello_id, fascicolo_markdown, motivo, creata_il "
            "FROM revisioni_fascicolo WHERE incarico_id = :id ORDER BY numero DESC"
        ), {"id": engagement_id}).mappings().all()
        pending = connection.execute(text(
            "SELECT x.id, x.revisione_origine_id, x.revisione_destinazione_id, "
            "x.fascicolo_proposto, x.diff, x.creata_il, r.numero AS revisione_destinazione "
            "FROM migrazioni_fascicolo x JOIN revisioni_modello_fascicolo r "
            "ON r.id = x.revisione_destinazione_id WHERE x.incarico_id = :id "
            "AND x.stato = 'proposta' ORDER BY r.numero DESC LIMIT 1"
        ), {"id": engagement_id}).mappings().one_or_none()
        relevance = connection.execute(text(
            "SELECT sezione, stato, motivo, riferimenti, origine "
            "FROM pertinenza_sezioni WHERE incarico_id = :id"
        ), {"id": engagement_id}).mappings().all()
        relevance_history = connection.execute(text(
            "SELECT id, run_id, sezione, stato, motivo, riferimenti, origine, creata_il "
            "FROM revisioni_pertinenza WHERE incarico_id = :id ORDER BY creata_il DESC, id DESC"
        ), {"id": engagement_id}).mappings().all()
        proposed_facts = connection.execute(text(
            "SELECT id, run_id, sezione, testo, riferimenti, creato_il "
            "FROM fatti_proposti_incarico WHERE incarico_id = :id ORDER BY creato_il, id"
        ), {"id": engagement_id}).mappings().all()
        return {
            "id": str(row["id"]), "company": row["azienda"], "site": row["sede"],
            "reference_date": row["data_riferimento"], "dossier_markdown": row["fascicolo_markdown"],
            "created_at": row["creato_il"], "updated_at": row["aggiornato_il"],
            "status": row["stato"], "version": row["versione_stato"],
            "relevance": {item["sezione"]: {
                "status": item["stato"], "reason": item["motivo"],
                "references": item["riferimenti"], "origin": item["origine"],
            } for item in relevance},
            "relevance_history": [{"id": str(item["id"]),
                "run_id": str(item["run_id"]) if item["run_id"] else None,
                "section": item["sezione"], "status": item["stato"],
                "reason": item["motivo"], "references": item["riferimenti"],
                "origin": item["origine"], "created_at": item["creata_il"]}
                for item in relevance_history],
            "proposed_facts": [{"id": str(item["id"]), "run_id": str(item["run_id"]),
                "section": item["sezione"], "text": item["testo"],
                "references": item["riferimenti"], "created_at": item["creato_il"]}
                for item in proposed_facts],
            "exportable_markdown": exportable_dossier(
                row["fascicolo_markdown"],
                {item["sezione"] for item in relevance if item["stato"] == "non_pertinente"},
            ),
            "template": {"id": str(row["modello_id"]), "name": row["modello"]},
            "template_revision": {
                "id": str(row["revisione_id"]), "number": row["revisione"],
                "instructions": row["indicazioni"],
                "relevance_guidance": row["pertinenza"],
            },
            "history": [{
                "id": str(item["id"]), "number": item["numero"],
                "template_revision_id": str(item["revisione_modello_id"]),
                "dossier_markdown": item["fascicolo_markdown"],
                "reason": item["motivo"], "created_at": item["creata_il"],
            } for item in history],
            "pending_migration": None if pending is None else {
                "id": str(pending["id"]),
                "source_revision_id": str(pending["revisione_origine_id"]),
                "target_revision_id": str(pending["revisione_destinazione_id"]),
                "target_revision": pending["revisione_destinazione"],
                "proposed_markdown": pending["fascicolo_proposto"],
                "diff": pending["diff"], "created_at": pending["creata_il"],
            },
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


class TemplateInput(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    markdown: str = Field(min_length=1, max_length=100_000)
    instructions: dict[str, str] = Field(default_factory=dict)
    relevance_guidance: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def instructions_match_sections(self) -> TemplateInput:
        titles = section_titles(self.markdown)
        if len(titles) != len(set(titles)):
            raise ValueError("I titoli delle sezioni devono essere univoci.")
        validate_instructions(self.markdown, self.instructions)
        validate_instructions(self.markdown, self.relevance_guidance)
        return self


class TemplateRevisionInput(BaseModel):
    markdown: str = Field(min_length=1, max_length=100_000)
    instructions: dict[str, str] = Field(default_factory=dict)
    relevance_guidance: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def instructions_match_sections(self) -> TemplateRevisionInput:
        titles = section_titles(self.markdown)
        if len(titles) != len(set(titles)):
            raise ValueError("I titoli delle sezioni devono essere univoci.")
        validate_instructions(self.markdown, self.instructions)
        validate_instructions(self.markdown, self.relevance_guidance)
        return self


class EngagementInput(BaseModel):
    company: str = Field(min_length=1, max_length=300)
    site: str = Field(min_length=1, max_length=300)
    reference_date: date
    template_revision_id: UUID


class DossierInput(BaseModel):
    markdown: str = Field(min_length=1, max_length=500_000)


class ObservationSectionInput(BaseModel):
    section: str | None = None


class RelevanceInput(BaseModel):
    status: Literal["da_valutare", "pertinente", "non_pertinente", "da_chiarire"]
    reason: str = Field(min_length=1, max_length=2000)
    references: list[str] = Field(default_factory=list)


class CitationOutput(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: UUID
    passage: str
    document_title: str
    document_type: str
    document_urn: str | None = None
    document_valid_from: str | None = None
    document_valid_until: str | None = None
    sources: list[dict[str, Any]] = Field(default_factory=list)


class MessageOutput(BaseModel):
    id: UUID
    role: Literal["user", "assistant"]
    content: str
    status: Literal["ANSWER", "ABSTAIN"] | None
    created_at: datetime
    citations: list[CitationOutput] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    conditions: list[str] = Field(default_factory=list)


class ConversationSummary(BaseModel):
    id: UUID
    created_at: datetime
    message_count: int
    last_message: str | None


class ConversationOutput(BaseModel):
    id: UUID
    created_at: datetime
    messages: list[MessageOutput]
    case_state: dict[str, dict[str, Any]]


class AnswerResponse(BaseModel):
    status: Literal["ANSWER"]
    message: MessageOutput
    citations: list[CitationOutput]
    missing_information: list[str]
    conditions: list[str]
    trace_id: UUID
    request_id: UUID


class AbstentionResponse(BaseModel):
    status: Literal["ABSTAIN"]
    message: MessageOutput
    citations: list[CitationOutput]
    missing_information: list[str]
    conditions: list[str]
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
    409: {"model": ErrorEnvelope}, 422: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope},
    502: {"model": ErrorEnvelope}, 503: {"model": ErrorEnvelope},
}


def create_app(
    store: Store | None = None, backend: ChatBackend | None = None,
    evidence_store: EvidenceStore | None = None,
    evidence_analyzer: EvidenceAnalyzer | None = None,
    agent_service: DossierAgentService | None = None,
) -> FastAPI:
    app = FastAPI(
        title="OCIO API", version="1.0.0",
        responses={400: {"model": ErrorEnvelope}, 500: {"model": ErrorEnvelope}},
    )
    if store is None:
        engine = create_engine(database_url())
        selected_store: Store = PostgresStore(engine)
        if backend is None:
            from ocio.chat_runtime import backend_from_environment

            backend = backend_from_environment(engine)
    else:
        selected_store = store
    selected_backend = backend or UnconfiguredBackend()
    selected_evidence_store = evidence_store or (
        PostgresEvidenceStore(selected_store.engine)
        if isinstance(selected_store, PostgresStore) else MemoryEvidenceStore()
    )
    selected_evidence_analyzer = evidence_analyzer or OpenAIEvidenceAnalyzer()
    selected_agent = agent_service or (
        DossierAgentService(PostgresAgentStore(selected_store.engine),
                            selected_evidence_store, selected_backend)
        if isinstance(selected_store, PostgresStore) else None
    )

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

    @app.get("/v1/conversations", response_model=list[ConversationSummary])
    def list_conversations() -> Sequence[Mapping[str, Any]]:
        return selected_store.list_conversations()

    @app.get(
        "/v1/conversations/{conversation_id}", responses=ERROR_RESPONSES,
        response_model=ConversationOutput,
    )
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
            "conditions": reply.conditions,
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

    @app.get("/v1/dossier-templates")
    def list_dossier_templates() -> Sequence[Mapping[str, Any]]:
        return selected_store.list_templates()

    @app.post("/v1/dossier-templates", status_code=201, responses=ERROR_RESPONSES)
    def create_dossier_template(payload: TemplateInput) -> Mapping[str, Any]:
        return selected_store.create_template(uuid4(), uuid4(), payload.model_dump())

    @app.post(
        "/v1/dossier-templates/{template_id}/revisions", status_code=201,
        responses=ERROR_RESPONSES,
    )
    def create_dossier_template_revision(
        template_id: UUID, payload: TemplateRevisionInput
    ) -> Mapping[str, Any]:
        result = selected_store.revise_template(template_id, uuid4(), payload.model_dump())
        if result is None:
            raise ApiError(404, "template_not_found", "Modello non trovato.")
        return result

    @app.get("/v1/engagements")
    def list_engagements() -> Sequence[Mapping[str, Any]]:
        return selected_store.list_engagements()

    @app.post("/v1/engagements", status_code=201, responses=ERROR_RESPONSES)
    def create_engagement(payload: EngagementInput) -> Mapping[str, Any]:
        result = selected_store.create_engagement(uuid4(), payload.model_dump())
        if result is None:
            raise ApiError(422, "template_revision_not_found", "Revisione del modello non trovata.")
        return result

    @app.get("/v1/engagements/{engagement_id}", responses=ERROR_RESPONSES)
    def get_engagement(engagement_id: UUID) -> Mapping[str, Any]:
        result = selected_store.engagement(engagement_id)
        if result is None:
            raise ApiError(404, "engagement_not_found", "Incarico non trovato.")
        return result

    @app.get("/v1/engagements/{engagement_id}/agent", responses=ERROR_RESPONSES)
    def get_engagement_agent(engagement_id: UUID) -> Mapping[str, Any] | None:
        if selected_agent is None:
            raise ApiError(503, "agent_unavailable", "Agente non configurato.")
        if selected_store.engagement(engagement_id) is None:
            raise ApiError(404, "engagement_not_found", "Incarico non trovato.")
        return selected_agent.store.run(engagement_id)

    @app.post("/v1/engagements/{engagement_id}/agent/runs", responses=ERROR_RESPONSES)
    async def start_engagement_agent(engagement_id: UUID) -> Mapping[str, Any]:
        if selected_agent is None:
            raise ApiError(503, "agent_unavailable", "Agente non configurato.")
        if selected_store.engagement(engagement_id) is None:
            raise ApiError(404, "engagement_not_found", "Incarico non trovato.")
        try:
            return await selected_agent.execute(engagement_id)
        except StateConflict as error:
            raise ApiError(409, "agent_running", str(error)) from error

    @app.patch("/v1/engagements/{engagement_id}/relevance/{section:path}", responses=ERROR_RESPONSES)
    def update_engagement_relevance(
        engagement_id: UUID, section: str, payload: RelevanceInput
    ) -> Mapping[str, Any]:
        if selected_agent is None:
            raise ApiError(503, "agent_unavailable", "Agente non configurato.")
        try:
            selected_agent.store.relevance(engagement_id, section, payload.status,
                                           payload.reason, payload.references)
        except ValueError as error:
            raise ApiError(422, "invalid_relevance", str(error)) from error
        result = selected_store.engagement(engagement_id)
        assert result is not None
        return result

    @app.get("/v1/engagements/{engagement_id}/messages", responses=ERROR_RESPONSES)
    def engagement_messages(engagement_id: UUID) -> list[dict[str, Any]]:
        result = selected_evidence_store.messages(engagement_id)
        if result is None:
            raise ApiError(404, "engagement_not_found", "Incarico non trovato.")
        return result

    @app.post("/v1/engagements/{engagement_id}/messages", status_code=201, responses=ERROR_RESPONSES)
    async def add_engagement_message(
        engagement_id: UUID,
        content: str = Form(default=""),
        files: list[UploadFile] = File(default=[]),
        file_instructions: list[str] = Form(default=[]),
    ) -> dict[str, Any]:
        if not content.strip() and not files:
            raise ApiError(422, "empty_message", "Scrivi un messaggio o allega un file.")
        if len(files) > 5:
            raise ApiError(422, "too_many_files", "Allega al massimo cinque file per messaggio.")
        if len(content) > 10_000:
            raise ApiError(422, "message_too_long", "Il messaggio supera 10.000 caratteri.")
        if file_instructions and len(file_instructions) != len(files):
            raise ApiError(422, "invalid_file_instructions", "Indica un'istruzione per ogni file.")
        original: list[tuple[str, str, bytes, str]] = []
        for index, file in enumerate(files):
            data = await file.read(10_000_001)
            if len(data) > 10_000_000:
                raise ApiError(413, "file_too_large", "Ogni file può contenere al massimo 10 MB.")
            instruction = (file_instructions[index].strip() if file_instructions else "") or content.strip()
            if len(instruction) > 10_000:
                raise ApiError(422, "instruction_too_long", "L'istruzione supera 10.000 caratteri.")
            original.append((file.filename or "allegato", file.content_type or "application/octet-stream", data, instruction))
        message = selected_evidence_store.add_message(engagement_id, content.strip(), original)
        if message is None:
            raise ApiError(404, "engagement_not_found", "Incarico non trovato.")
        engagement = selected_store.engagement(engagement_id)
        assert engagement is not None
        sections = section_titles(engagement["dossier_markdown"])
        # Persist the message and every original before analysis can fail.
        for attachment in message["attachments"]:
            identifier = UUID(attachment["id"])
            source = selected_evidence_store.attachment(engagement_id, identifier)
            assert source is not None
            _, media_type, data = source
            try:
                if media_type not in SUPPORTED:
                    raise ValueError("Formato non supportato. Usa JPEG, PNG, WebP, PDF o testo semplice.")
                method, observations = selected_evidence_analyzer.analyze(
                    data, media_type, attachment["instruction"], sections
                )
                selected_evidence_store.record_analysis(
                    engagement_id, UUID(message["id"]), identifier,
                    attachment["instruction"], method, observations,
                )
            except Exception as error:
                LOGGER.warning("engagement evidence analysis failed", extra={
                    "engagement_id": str(engagement_id), "attachment_id": str(identifier),
                    "error_type": type(error).__name__,
                })
                reason = str(error) if isinstance(error, ValueError) else "Analisi non disponibile. L'originale è stato conservato."
                selected_evidence_store.record_error(engagement_id, identifier, reason)
        if not files and content.strip():
            selected_evidence_store.record_note(
                engagement_id, UUID(message["id"]), content.strip()
            )
        result = selected_evidence_store.messages(engagement_id)
        assert result is not None
        return next(item for item in result if item["id"] == message["id"])

    @app.get("/v1/engagements/{engagement_id}/attachments/{attachment_id}", responses=ERROR_RESPONSES)
    def get_engagement_attachment(engagement_id: UUID, attachment_id: UUID) -> Response:
        result = selected_evidence_store.attachment(engagement_id, attachment_id)
        if result is None:
            raise ApiError(404, "attachment_not_found", "Allegato non trovato.")
        name, media_type, data = result
        return Response(data, media_type=media_type, headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(name, safe='')}",
            "X-Content-Type-Options": "nosniff",
        })

    @app.patch("/v1/engagements/{engagement_id}/observations/{observation_id}", responses=ERROR_RESPONSES)
    def link_observation(
        engagement_id: UUID, observation_id: UUID, payload: ObservationSectionInput
    ) -> dict[str, str | None]:
        engagement = selected_store.engagement(engagement_id)
        if engagement is None:
            raise ApiError(404, "engagement_not_found", "Incarico non trovato.")
        if payload.section is not None and payload.section not in section_titles(engagement["dossier_markdown"]):
            raise ApiError(422, "section_not_found", "Sezione del fascicolo non trovata.")
        if not selected_evidence_store.link_section(engagement_id, observation_id, payload.section):
            raise ApiError(404, "observation_not_found", "Osservazione non trovata.")
        return {"section": payload.section}

    @app.patch("/v1/engagements/{engagement_id}/dossier", responses=ERROR_RESPONSES)
    def update_dossier(
        engagement_id: UUID, payload: DossierInput
    ) -> Mapping[str, Any]:
        result = selected_store.update_dossier(engagement_id, payload.markdown)
        if result is None:
            raise ApiError(404, "engagement_not_found", "Incarico non trovato.")
        return result

    @app.post(
        "/v1/engagements/{engagement_id}/migrations/{migration_id}/apply",
        responses=ERROR_RESPONSES,
    )
    def apply_dossier_migration(
        engagement_id: UUID, migration_id: UUID
    ) -> Mapping[str, Any]:
        result = selected_store.apply_migration(engagement_id, migration_id)
        if result is None:
            raise ApiError(404, "migration_not_found", "Proposta di migrazione non trovata.")
        return result

    return app


def _message_dict(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]), "role": row["ruolo"], "content": row["contenuto"],
        "status": row["stato"], "created_at": row["creato_il"],
    }


def _template_revision(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]), "number": row["numero"],
        "markdown": row["schema_markdown"], "instructions": row["indicazioni"],
        "relevance_guidance": row["pertinenza"],
        "created_at": row["creata_il"],
    }


def _engagement_summary(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]), "company": row["azienda"], "site": row["sede"],
        "reference_date": row["data_riferimento"], "created_at": row["creato_il"],
        "template_name": row["modello"], "template_revision": row["revisione"],
        "has_pending_migration": row["migrazione_pendente"],
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
