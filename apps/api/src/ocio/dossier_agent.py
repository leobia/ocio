"""OCIO-owned state and effects for the dossier agent."""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections.abc import Mapping, Sequence
from typing import Any, Protocol
from uuid import UUID, uuid4

from sqlalchemy import Engine, text

from ocio.dossier import replace_section_body, section_titles
from ocio.dossier_prompt import PROMPT_VERSION, writing_context

STATUSES = ("da_valutare", "pertinente", "non_pertinente", "da_chiarire")
RUN_STATUSES = ("in_corso", "in_attesa", "completato", "fallito")
MAX_TURNS = 24
MAX_SECONDS = 180
MAX_TOKENS = 60_000


def _question_key(value: str) -> str:
    return re.sub(r"\W+", " ", value.casefold()).strip()


class StateConflict(ValueError):
    pass


class AgentStore(Protocol):
    def snapshot(self, engagement_id: UUID) -> dict[str, Any] | None: ...
    def start(self, engagement_id: UUID, model: str) -> UUID: ...
    def event(self, run_id: UUID, kind: str, data: Mapping[str, Any]) -> None: ...
    def effect(self, run_id: UUID, operation_id: UUID, expected_version: int,
               kind: str, payload: Mapping[str, Any]) -> dict[str, Any]: ...
    def finish(self, run_id: UUID, status: str, reason: str) -> dict[str, Any]: ...
    def run(self, engagement_id: UUID) -> dict[str, Any] | None: ...
    def relevance(self, engagement_id: UUID, section: str, status: str,
                  reason: str, references: Sequence[str]) -> None: ...


class PostgresAgentStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def snapshot(self, engagement_id: UUID) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            row = connection.execute(text(
                "SELECT i.id, i.azienda, i.sede, i.data_riferimento, i.fascicolo_markdown, "
                "i.versione_stato, i.stato, r.id AS revisione_id, r.schema_markdown, "
                "r.indicazioni, r.pertinenza FROM incarichi i JOIN revisioni_modello_fascicolo r "
                "ON r.id = i.revisione_modello_id WHERE i.id = :id"
            ), {"id": engagement_id}).mappings().one_or_none()
            if row is None:
                return None
            decisions = connection.execute(text(
                "SELECT sezione, stato, motivo, riferimenti, origine FROM pertinenza_sezioni "
                "WHERE incarico_id = :id"
            ), {"id": engagement_id}).mappings().all()
            facts = connection.execute(text(
                "SELECT id, sezione, testo, riferimenti FROM fatti_proposti_incarico "
                "WHERE incarico_id = :id ORDER BY creato_il, id"
            ), {"id": engagement_id}).mappings().all()
            return {
                "id": str(row["id"]), "company": row["azienda"], "site": row["sede"],
                "reference_date": str(row["data_riferimento"]),
                "dossier_markdown": row["fascicolo_markdown"],
                "version": row["versione_stato"], "status": row["stato"],
                "template_revision_id": str(row["revisione_id"]),
                "schema": row["schema_markdown"], "descriptions": row["indicazioni"],
                "relevance_guidance": row["pertinenza"],
                "relevance": {item["sezione"]: {
                    "status": item["stato"], "reason": item["motivo"],
                    "references": item["riferimenti"], "origin": item["origine"],
                } for item in decisions},
                "proposed_facts": [{"id": str(item["id"]), "section": item["sezione"],
                                    "text": item["testo"], "references": item["riferimenti"]}
                                   for item in facts],
            }

    def start(self, engagement_id: UUID, model: str) -> UUID:
        run_id = uuid4()
        with self.engine.begin() as connection:
            row = connection.execute(text(
                "SELECT revisione_modello_id FROM incarichi WHERE id = :id FOR UPDATE"
            ), {"id": engagement_id}).scalar_one_or_none()
            if row is None:
                raise ValueError("Incarico non trovato.")
            connection.execute(text(
                "UPDATE run_fascicolo SET stato = 'fallito', motivo = 'Run interrotto prima della conclusione.', "
                "concluso_il = now() WHERE incarico_id = :id AND stato = 'in_corso' "
                "AND creato_il < now() - interval '5 minutes'"
            ), {"id": engagement_id})
            active = connection.execute(text(
                "SELECT 1 FROM run_fascicolo WHERE incarico_id = :id AND stato = 'in_corso'"
            ), {"id": engagement_id}).scalar_one_or_none()
            if active:
                raise StateConflict("Un run è già in corso per questo incarico.")
            connection.execute(text(
                "INSERT INTO run_fascicolo (id, incarico_id, stato, modello, versione_prompt, "
                "revisione_modello_id) VALUES (:run, :id, 'in_corso', :model, :prompt, :revision)"
            ), {"run": run_id, "id": engagement_id, "model": model,
                "prompt": PROMPT_VERSION, "revision": row})
            connection.execute(text(
                "UPDATE incarichi SET stato = 'in_corso' WHERE id = :id"
            ), {"id": engagement_id})
        return run_id

    def event(self, run_id: UUID, kind: str, data: Mapping[str, Any]) -> None:
        with self.engine.begin() as connection:
            connection.execute(text(
                "INSERT INTO eventi_run_fascicolo (run_id, tipo, dati) "
                "VALUES (:run, :kind, CAST(:data AS jsonb))"
            ), {"run": run_id, "kind": kind,
                "data": json.dumps(data, ensure_ascii=False, default=str)})

    def effect(self, run_id: UUID, operation_id: UUID, expected_version: int,
               kind: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        if kind not in ("plan", "fact", "relevance", "write", "question"):
            raise ValueError("Operazione sconosciuta.")
        with self.engine.begin() as connection:
            run = connection.execute(text(
                "SELECT incarico_id, stato FROM run_fascicolo WHERE id = :run"
            ), {"run": run_id}).mappings().one()
            engagement_id = run["incarico_id"]
            state = connection.execute(text(
                "SELECT versione_stato, fascicolo_markdown, revisione_modello_id "
                "FROM incarichi WHERE id = :id FOR UPDATE"
            ), {"id": engagement_id}).mappings().one()
            previous = connection.execute(text(
                "SELECT run_id, tipo, payload, risultato FROM operazioni_fascicolo WHERE id = :id"
            ), {"id": operation_id}).mappings().one_or_none()
            if previous is not None:
                if previous["run_id"] != run_id or previous["tipo"] != kind or previous["payload"] != dict(payload):
                    raise StateConflict("Identificatore di operazione già usato con dati diversi.")
                return dict(previous["risultato"])
            if run["stato"] != "in_corso" or state["versione_stato"] != expected_version:
                raise StateConflict("Lo stato è cambiato: ricarica l'incarico prima di riprovare.")
            if kind in ("fact", "relevance", "write"):
                title = str(payload["section"])
                if title not in section_titles(state["fascicolo_markdown"]):
                    raise ValueError("Sezione inesistente.")
                references = payload.get("references", [])
                if not isinstance(references, list) or any(not isinstance(ref, str) for ref in references):
                    raise ValueError("Riferimenti non validi.")
                known = {str(item[0]) for item in connection.execute(text(
                    "SELECT m.id FROM messaggi_incarico m WHERE m.incarico_id = :id "
                    "AND m.ruolo = 'user' UNION SELECT o.id FROM osservazioni_incarico o "
                    "JOIN messaggi_incarico m ON m.id = o.messaggio_id "
                    "WHERE m.incarico_id = :id AND o.esito = 'osservato'"
                ), {"id": engagement_id}).all()}
                known.update({"incarico:azienda", "incarico:sede", "incarico:data_riferimento"})
                searches: Sequence[Mapping[str, Any]] = connection.execute(text(
                    "SELECT dati FROM eventi_run_fascicolo WHERE run_id = :run "
                    "AND tipo = 'knowledge_search'"
                ), {"run": run_id}).scalars().all()
                for search in searches:
                    known.update(str(citation.get("id")) for citation in
                                 search.get("result", {}).get("citations", []) if citation.get("id"))
                if set(references) - known:
                    raise ValueError("Riferimento non presente nelle evidenze o nella ricerca normativa.")
            if kind == "plan":
                connection.execute(text("UPDATE run_fascicolo SET piano = :plan WHERE id = :run"),
                                   {"plan": payload["plan"], "run": run_id})
            elif kind == "fact":
                fact = str(payload["text"]).strip()
                if not fact or not references:
                    raise ValueError("Un fatto proposto richiede testo e riferimenti.")
                connection.execute(text(
                    "INSERT INTO fatti_proposti_incarico (id, incarico_id, run_id, sezione, testo, riferimenti) "
                    "VALUES (:fact_id, :id, :run, :section, :fact, CAST(:refs AS jsonb))"
                ), {"fact_id": uuid4(), "id": engagement_id, "run": run_id,
                    "section": title, "fact": fact, "refs": json.dumps(references)})
            elif kind == "relevance":
                status = str(payload["status"])
                if status not in STATUSES or not str(payload["reason"]).strip():
                    raise ValueError("Decisione di pertinenza non valida.")
                if status == "non_pertinente" and not references:
                    raise ValueError("Una esclusione richiede un dato che la sostenga.")
                existing: str | None = connection.execute(text(
                    "SELECT origine FROM pertinenza_sezioni WHERE incarico_id = :id AND sezione = :section"
                ), {"id": engagement_id, "section": title}).scalar_one_or_none()
                if existing == "operatore":
                    raise StateConflict("La decisione dell'RSPP ha precedenza.")
                connection.execute(text(
                    "INSERT INTO pertinenza_sezioni (incarico_id, sezione, stato, motivo, riferimenti, origine) "
                    "VALUES (:id, :section, :status, :reason, CAST(:refs AS jsonb), 'agente') "
                    "ON CONFLICT (incarico_id, sezione) DO UPDATE SET stato = EXCLUDED.stato, "
                    "motivo = EXCLUDED.motivo, riferimenti = EXCLUDED.riferimenti, "
                    "origine = 'agente', aggiornata_il = now()"
                ), {"id": engagement_id, "section": title, "status": status,
                    "reason": payload["reason"],
                    "refs": json.dumps(payload.get("references", []))})
                connection.execute(text(
                    "INSERT INTO revisioni_pertinenza (id, incarico_id, run_id, sezione, stato, "
                    "motivo, riferimenti, origine) VALUES (:revision, :id, :run, :section, :status, "
                    ":reason, CAST(:refs AS jsonb), 'agente')"
                ), {"revision": uuid4(), "id": engagement_id, "run": run_id,
                    "section": title, "status": status, "reason": payload["reason"],
                    "refs": json.dumps(payload.get("references", []))})
            elif kind == "write":
                decision = connection.execute(text(
                    "SELECT stato FROM pertinenza_sezioni WHERE incarico_id = :id AND sezione = :section"
                ), {"id": engagement_id, "section": title}).scalar_one_or_none()
                if decision != "pertinente":
                    raise StateConflict("La sezione deve essere pertinente prima della scrittura.")
                body = str(payload["body"]).strip()
                if not body or not isinstance(references, list) or not references:
                    raise ValueError("Testo e riferimenti verificabili sono obbligatori.")
                if any(reference not in body for reference in references):
                    raise ValueError("Ogni riferimento deve comparire nel testo della sezione.")
                updated = replace_section_body(state["fascicolo_markdown"], title, body)
                connection.execute(text(
                    "UPDATE incarichi SET fascicolo_markdown = :markdown, aggiornato_il = now() WHERE id = :id"
                ), {"id": engagement_id, "markdown": updated})
                connection.execute(text(
                    "INSERT INTO revisioni_fascicolo (id, incarico_id, numero, revisione_modello_id, "
                    "fascicolo_markdown, motivo) SELECT :revision, :id, COALESCE(max(numero), 0) + 1, "
                    ":template, :markdown, 'agente' FROM revisioni_fascicolo WHERE incarico_id = :id"
                ), {"revision": uuid4(), "id": engagement_id,
                    "template": state["revisione_modello_id"], "markdown": updated})
            elif kind == "question":
                question = str(payload["question"]).strip()
                if not question:
                    raise ValueError("Domanda vuota.")
                existing = connection.execute(text(
                    "SELECT domande FROM run_fascicolo WHERE id = :run FOR UPDATE"
                ), {"run": run_id}).scalar_one()
                questions: list[dict[str, Any]] = list(existing)
                if _question_key(question) not in {
                    _question_key(item["question"]) for item in questions
                }:
                    questions.append({"question": question, "impact": int(payload["impact"]),
                                      "section": payload.get("section")})
                connection.execute(text(
                    "UPDATE run_fascicolo SET domande = CAST(:questions AS jsonb) WHERE id = :run"
                ), {"run": run_id, "questions": json.dumps(questions, ensure_ascii=False)})
            version = expected_version + 1
            connection.execute(text(
                "UPDATE incarichi SET versione_stato = :version WHERE id = :id"
            ), {"version": version, "id": engagement_id})
            result = {"version": version, "status": "applied"}
            connection.execute(text(
                "INSERT INTO operazioni_fascicolo (id, incarico_id, run_id, tipo, payload, risultato) "
                "VALUES (:operation, :id, :run, :kind, CAST(:payload AS jsonb), CAST(:result AS jsonb))"
            ), {"operation": operation_id, "id": engagement_id, "run": run_id,
                "kind": kind, "payload": json.dumps(payload, ensure_ascii=False),
                "result": json.dumps(result)})
            connection.execute(text(
                "INSERT INTO eventi_run_fascicolo (run_id, tipo, dati) "
                "VALUES (:run, :kind, CAST(:data AS jsonb))"
            ), {"run": run_id, "kind": kind,
                "data": json.dumps({"operation_id": str(operation_id), "payload": payload,
                                    "result": result}, ensure_ascii=False)})
            return result

    def finish(self, run_id: UUID, status: str, reason: str) -> dict[str, Any]:
        if status not in RUN_STATUSES or status == "in_corso":
            raise ValueError("Stato finale non valido.")
        with self.engine.begin() as connection:
            run = connection.execute(text(
                "SELECT incarico_id, domande, stato FROM run_fascicolo WHERE id = :run FOR UPDATE"
            ), {"run": run_id}).mappings().one()
            if run["stato"] != "in_corso":
                return self._run_dict(run_id, connection)
            questions = sorted(run["domande"], key=lambda item: (-item["impact"], item["question"]))
            if status == "completato" and not questions:
                undecided: list[str] = list(connection.execute(text(
                    "SELECT sezione FROM pertinenza_sezioni WHERE incarico_id = :id "
                    "AND stato IN ('da_valutare', 'da_chiarire') ORDER BY sezione"
                ), {"id": run["incarico_id"]}).scalars().all())
                current_markdown: str = connection.execute(text(
                    "SELECT fascicolo_markdown FROM incarichi WHERE id = :id"
                ), {"id": run["incarico_id"]}).scalar_one()
                undecided = [title for title in undecided if title in section_titles(current_markdown)]
                if undecided:
                    questions = [{"question": "Quali attività o condizioni permettono di valutare "
                                  "la pertinenza di: " + ", ".join(undecided) + "?",
                                  "impact": 5, "section": None}]
                    connection.execute(text(
                        "UPDATE run_fascicolo SET domande = CAST(:questions AS jsonb) WHERE id = :run"
                    ), {"run": run_id, "questions": json.dumps(questions, ensure_ascii=False)})
            elif questions:
                connection.execute(text(
                    "UPDATE run_fascicolo SET domande = CAST(:questions AS jsonb) WHERE id = :run"
                ), {"run": run_id, "questions": json.dumps(questions, ensure_ascii=False)})
            if questions and status == "completato":
                status = "in_attesa"
            message = reason
            if questions and status == "in_attesa":
                message = "Per proseguire servono queste informazioni:\n" + "\n".join(
                    f"{index}. {item['question']}" for index, item in enumerate(questions, 1)
                )
            connection.execute(text(
                "UPDATE run_fascicolo SET stato = :status, motivo = :reason, "
                "concluso_il = now() WHERE id = :run"
            ), {"run": run_id, "status": status, "reason": reason})
            connection.execute(text(
                "UPDATE incarichi SET stato = :status WHERE id = :id"
            ), {"id": run["incarico_id"], "status": status})
            connection.execute(text(
                "INSERT INTO messaggi_incarico (id, incarico_id, ruolo, contenuto) "
                "VALUES (:message, :id, 'assistant', :content)"
            ), {"message": uuid4(), "id": run["incarico_id"], "content": message})
            return self._run_dict(run_id, connection)

    def run(self, engagement_id: UUID) -> dict[str, Any] | None:
        with self.engine.connect() as connection:
            run_id = connection.execute(text(
                "SELECT id FROM run_fascicolo WHERE incarico_id = :id "
                "ORDER BY creato_il DESC, id DESC LIMIT 1"
            ), {"id": engagement_id}).scalar_one_or_none()
            return self._run_dict(run_id, connection) if run_id else None

    @staticmethod
    def _run_dict(run_id: UUID, connection: Any) -> dict[str, Any]:
        row = connection.execute(text(
            "SELECT id, stato, modello, versione_prompt, revisione_modello_id, piano, "
            "domande, motivo, creato_il, concluso_il FROM run_fascicolo WHERE id = :run"
        ), {"run": run_id}).mappings().one()
        events = connection.execute(text(
            "SELECT tipo, dati, creato_il FROM eventi_run_fascicolo WHERE run_id = :run ORDER BY id"
        ), {"run": run_id}).mappings().all()
        return {"id": str(row["id"]), "status": row["stato"], "model": row["modello"],
                "prompt_version": row["versione_prompt"],
                "template_revision_id": str(row["revisione_modello_id"]),
                "plan": row["piano"], "questions": row["domande"], "reason": row["motivo"],
                "created_at": row["creato_il"], "finished_at": row["concluso_il"],
                "events": [{"type": item["tipo"], "data": item["dati"],
                            "created_at": item["creato_il"]} for item in events]}

    def relevance(self, engagement_id: UUID, section: str, status: str,
                  reason: str, references: Sequence[str]) -> None:
        if status not in STATUSES or not reason.strip():
            raise ValueError("Decisione di pertinenza non valida.")
        with self.engine.begin() as connection:
            row = connection.execute(text(
                "SELECT fascicolo_markdown FROM incarichi WHERE id = :id FOR UPDATE"
            ), {"id": engagement_id}).scalar_one_or_none()
            if row is None or section not in section_titles(row):
                raise ValueError("Sezione inesistente.")
            connection.execute(text(
                "INSERT INTO pertinenza_sezioni (incarico_id, sezione, stato, motivo, riferimenti, origine) "
                "VALUES (:id, :section, :status, :reason, CAST(:refs AS jsonb), 'operatore') "
                "ON CONFLICT (incarico_id, sezione) DO UPDATE SET stato = EXCLUDED.stato, "
                "motivo = EXCLUDED.motivo, riferimenti = EXCLUDED.riferimenti, "
                "origine = 'operatore', aggiornata_il = now()"
            ), {"id": engagement_id, "section": section, "status": status,
                "reason": reason, "refs": json.dumps(list(references))})
            connection.execute(text(
                "INSERT INTO revisioni_pertinenza (id, incarico_id, sezione, stato, motivo, "
                "riferimenti, origine) VALUES (:revision, :id, :section, :status, :reason, "
                "CAST(:refs AS jsonb), 'operatore')"
            ), {"revision": uuid4(), "id": engagement_id, "section": section,
                "status": status, "reason": reason, "refs": json.dumps(list(references))})
            connection.execute(text(
                "UPDATE incarichi SET versione_stato = versione_stato + 1 WHERE id = :id"
            ), {"id": engagement_id})


class DossierAgentService:
    def __init__(self, store: AgentStore, evidence: Any, knowledge: Any = None,
                 runner: Any = None) -> None:
        self.store = store
        self.evidence = evidence
        self.knowledge = knowledge
        self.runner = runner

    async def execute(self, engagement_id: UUID) -> dict[str, Any]:
        snapshot = self.store.snapshot(engagement_id)
        if snapshot is None:
            raise ValueError("Incarico non trovato.")
        previous = self.store.run(engagement_id)
        model = os.environ.get("OCIO_DOSSIER_MODEL", "gpt-4.1")
        run_id = self.store.start(engagement_id, model)
        try:
            messages = self.evidence.messages(engagement_id) or []
            context = writing_context(snapshot["schema"], snapshot["descriptions"])
            payload = {"engagement": {key: snapshot[key] for key in (
                "id", "company", "site", "reference_date", "dossier_markdown", "version",
                "status", "relevance", "relevance_guidance", "template_revision_id",
                "proposed_facts")},
                "template": json.loads(context.template), "messages": messages,
                "engagement_source_references": {
                    "company": "incarico:azienda", "site": "incarico:sede",
                    "reference_date": "incarico:data_riferimento"},
                "previous_run": None if previous is None else {
                    "plan": previous["plan"], "questions": previous["questions"],
                    "status": previous["status"], "reason": previous["reason"]}}
            self.store.event(run_id, "input", {"prompt_version": context.version,
                                               "template_revision_id": snapshot["template_revision_id"],
                                               "message_ids": [item["id"] for item in messages],
                                               "model": model, "max_turns": MAX_TURNS,
                                               "max_seconds": MAX_SECONDS,
                                               "max_tokens": MAX_TOKENS})
            output = await asyncio.wait_for(
                self._run_sdk(run_id, model, context.instructions, payload), MAX_SECONDS
            )
            self.store.event(run_id, "output", {"text": output})
            current = self.store.run(engagement_id)
            questions = current["questions"] if current else []
            return self.store.finish(run_id, "in_attesa" if questions else "completato", output)
        except Exception as error:
            self.store.event(run_id, "error", {"type": type(error).__name__, "message": str(error)})
            return self.store.finish(run_id, "fallito", f"Compilazione interrotta: {type(error).__name__}.")

    async def _run_sdk(self, run_id: UUID, model: str, instructions: str,
                       payload: dict[str, Any]) -> str:
        if self.runner is not None:
            return str(await self.runner(run_id, instructions, payload, self))
        from agents import (
            Agent,
            ModelSettings,
            RunConfig,
            RunHooks,
            Runner,
            function_tool,
        )

        store = self.store

        class BudgetHooks(RunHooks):  # type: ignore[type-arg]
            total_tokens = 0

            async def on_llm_end(self, context: Any, agent: Any, response: Any) -> None:
                self.total_tokens += response.usage.total_tokens
                store.event(run_id, "model_usage", {"input_tokens": response.usage.input_tokens,
                                                     "output_tokens": response.usage.output_tokens,
                                                     "total_tokens": self.total_tokens})
                if self.total_tokens >= MAX_TOKENS:
                    raise RuntimeError("Budget di token raggiunto.")

        def apply(kind: str, operation_id: str, expected_version: int,
                  data: dict[str, Any]) -> str:
            result = self.store.effect(run_id, UUID(operation_id), expected_version, kind, data)
            return json.dumps(result, ensure_ascii=False)

        @function_tool
        def plan_work(operation_id: str, expected_version: int, plan: str) -> str:
            """Persist the plan for all dossier sections. Return the next state version."""
            return apply("plan", operation_id, expected_version, {"plan": plan})

        @function_tool
        def analyze_evidence(section: str) -> str:
            """Read current notes and observations relevant to a section, including source IDs."""
            messages = self.evidence.messages(UUID(payload["engagement"]["id"])) or []
            result = [{"message_id": item["id"], "content": item["content"],
                "observations": [observation for observation in item["observations"]
                                 if observation["section"] in (None, section)]}
                for item in messages if item.get("role") == "user"]
            self.store.event(run_id, "analyze_evidence", {"section": section, "result": result})
            return json.dumps(result, ensure_ascii=False, default=str)

        @function_tool
        def propose_fact(operation_id: str, expected_version: int, section: str,
                         fact: str, references: list[str]) -> str:
            """Persist a case fact proposal with source IDs before using it in the draft."""
            return apply("fact", operation_id, expected_version, {
                "section": section, "text": fact, "references": references})

        @function_tool
        def check_section(section: str) -> str:
            """Inspect current section text, relevance and proposed facts for a completeness check."""
            current = self.store.snapshot(UUID(payload["engagement"]["id"]))
            assert current is not None
            from ocio.dossier import _split

            blocks = dict(_split(current["dossier_markdown"])[1])
            if section not in blocks:
                return "Sezione inesistente."
            result = {"section": section, "body": blocks[section],
                      "relevance": current["relevance"].get(section),
                      "proposed_facts": [item for item in current["proposed_facts"]
                                         if item["section"] == section]}
            self.store.event(run_id, "check_section", result)
            return json.dumps(result, ensure_ascii=False, default=str)

        @function_tool
        def knowledge_search(query: str) -> str:
            """Search the configured normative knowledge base for official sources and citations."""
            if self.knowledge is None:
                return "Ricerca normativa non configurata; non formulare affermazioni normative specifiche."
            try:
                reply = self.knowledge.answer(query, [], {})
            except Exception as error:
                self.store.event(run_id, "knowledge_error", {"error": str(error)})
                return "Ricerca normativa non disponibile; non formulare affermazioni normative specifiche."
            result = {"status": reply.status, "content": reply.content,
                      "citations": reply.citations}
            self.store.event(run_id, "knowledge_search", {"query": query, "result": result,
                                                           "retrieval_trace": reply.trace})
            return json.dumps(result, ensure_ascii=False, default=str)

        @function_tool
        def set_relevance(operation_id: str, expected_version: int, section: str,
                          status: str, reason: str, references: list[str]) -> str:
            """Record section relevance and evidence IDs; status is pertinent, not pertinent, or unclear."""
            return apply("relevance", operation_id, expected_version, {
                "section": section, "status": status, "reason": reason,
                "references": references})

        @function_tool
        def write_section(operation_id: str, expected_version: int, section: str,
                          body: str, references: list[str]) -> str:
            """Replace one relevant section with grounded Markdown; cite evidence IDs or official sources."""
            return apply("write", operation_id, expected_version, {
                "section": section, "body": body, "references": references})

        @function_tool
        def ask_question(operation_id: str, expected_version: int, section: str,
                         question: str, impact: int) -> str:
            """Queue a missing fact or relevance question, impact 1 to 5; never ask it immediately."""
            return apply("question", operation_id, expected_version, {
                "section": section, "question": question,
                "impact": max(1, min(5, impact))})

        agent = Agent(
            name="Redattore fascicolo OCIO", model=model,
            model_settings=ModelSettings(max_tokens=3000, parallel_tool_calls=False,
                                         store=False, include_usage=True),
            instructions=instructions,
            tools=[plan_work, analyze_evidence, propose_fact, knowledge_search,
                   set_relevance, write_section, check_section, ask_question],
        )
        result = await Runner.run(
            agent, json.dumps(payload, ensure_ascii=False, default=str),
            max_turns=MAX_TURNS,
            hooks=BudgetHooks(),
            run_config=RunConfig(tracing_disabled=True, workflow_name="ocio-dossier"),
        )
        return str(result.final_output or "Compilazione conclusa.")
