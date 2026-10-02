"""Human review of drafts; approval exports are immutable application records."""
from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import Connection, Engine, text

from ocio.dossier import (
    _split,
    exportable_dossier,
    replace_section_body,
    section_titles,
)


def section_body(markdown: str, title: str) -> str:
    block = dict(_split(markdown)[1]).get(title)
    if block is None:
        raise ValueError("Sezione inesistente.")
    return block.split('\n', 1)[1].strip() if '\n' in block else ''


def protect_sections(connection: Connection, engagement_id: UUID, titles: list[str]) -> None:
    current: list[str] = connection.execute(text("SELECT sezioni_protette FROM incarichi WHERE id = :id"),
                                 {"id": engagement_id}).scalar_one()
    connection.execute(text("UPDATE incarichi SET sezioni_protette = CAST(:titles AS jsonb) WHERE id = :id"),
                       {"id": engagement_id, "titles": json.dumps(sorted(set(current) | set(titles)))})


def revision(connection: Connection, engagement_id: UUID, markdown: str) -> UUID:
    identifier = uuid4()
    connection.execute(text(
        "UPDATE incarichi SET fascicolo_markdown = :markdown, versione_stato = versione_stato + 1, "
        "aggiornato_il = now() WHERE id = :id"
    ), {"id": engagement_id, "markdown": markdown})
    connection.execute(text(
        "INSERT INTO revisioni_fascicolo (id, incarico_id, numero, revisione_modello_id, fascicolo_markdown, motivo) "
        "SELECT :revision, i.id, (SELECT COALESCE(max(numero), 0) + 1 FROM revisioni_fascicolo WHERE incarico_id = i.id), "
        "i.revisione_modello_id, :markdown, 'modifica_manuale' FROM incarichi i WHERE i.id = :id"
    ), {"revision": identifier, "id": engagement_id, "markdown": markdown})
    return identifier


class ReviewInput(BaseModel):
    expected_version: int = Field(ge=0)
    author: str = Field(min_length=1, max_length=200, pattern=r"\S")
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")


class DecisionInput(ReviewInput):
    action: Literal['accettata', 'corretta', 'rifiutata']
    body: str | None = Field(default=None, max_length=500_000)


class ReviewStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def state(self, engagement_id: UUID) -> dict[str, Any]:
        with self.engine.connect() as c:
            return {
                "proposals": [dict(row) for row in c.execute(text(
                    "SELECT id, run_id, sezione AS section, precedente AS previous, proposto AS proposed, "
                    "riferimenti AS references, stato AS status FROM proposte_sezione WHERE incarico_id = :id ORDER BY creata_il DESC"
                ), {"id": engagement_id}).mappings()],
                "approvals": [dict(row) for row in c.execute(text(
                    "SELECT id, autore AS author, creata_il AS created_at, revisione_id AS revision_id "
                    "FROM approvazioni_fascicolo WHERE incarico_id = :id ORDER BY creata_il DESC"
                ), {"id": engagement_id}).mappings()],
                "sources": self.sources(c, engagement_id),
            }

    @staticmethod
    def lock(c: Connection, engagement_id: UUID, version: int) -> Mapping[str, Any]:
        row = c.execute(text("SELECT * FROM incarichi WHERE id = :id FOR UPDATE"), {"id": engagement_id}).mappings().one_or_none()
        if row is None:
            raise HTTPException(404, "Incarico non trovato.")
        if row['versione_stato'] != version:
            raise HTTPException(409, "Il fascicolo è cambiato. Ricarica prima di confermare.")
        if c.execute(text("SELECT 1 FROM run_fascicolo WHERE incarico_id = :id AND stato = 'in_corso'"), {"id": engagement_id}).first():
            raise HTTPException(409, "Attendi la conclusione della compilazione.")
        return dict(row)

    @staticmethod
    def sources(c: Connection, engagement_id: UUID) -> list[dict[str, Any]]:
        result = [{"id": str(row['id']), "text": row['contenuto'], "url": None} for row in c.execute(text(
            "SELECT id, contenuto FROM messaggi_incarico WHERE incarico_id = :id AND ruolo = 'user'"
        ), {"id": engagement_id}).mappings()]
        for row in c.execute(text(
            "SELECT o.id, o.testo, o.allegato_id FROM osservazioni_incarico o JOIN messaggi_incarico m "
            "ON m.id = o.messaggio_id WHERE m.incarico_id = :id"
        ), {"id": engagement_id}).mappings():
            result.append({"id": str(row['id']), "text": row['testo'], "url":
                           f"/api/v1/engagements/{engagement_id}/attachments/{row['allegato_id']}" if row['allegato_id'] else None})
        search_results: list[dict[str, Any]] = list(c.execute(text(
            "SELECT e.dati FROM eventi_run_fascicolo e JOIN run_fascicolo r ON r.id = e.run_id "
            "WHERE r.incarico_id = :id AND e.tipo = 'knowledge_search' ORDER BY e.id"
        ), {"id": engagement_id}).scalars())
        for data in search_results:
            for citation in data.get('result', {}).get('citations', []):
                result.append({"id": str(citation['id']), "text": citation.get('passage', ''),
                               "url": next((s.get('url') or s.get('source_url') for s in citation.get('sources', []) if s.get('url') or s.get('source_url')), None)})
        return list({item['id']: item for item in result}.values())

    def decide(self, engagement_id: UUID, proposal_id: UUID, value: DecisionInput) -> None:
        with self.engine.begin() as c:
            row = self.lock(c, engagement_id, value.expected_version)
            proposal = c.execute(text("SELECT * FROM proposte_sezione WHERE id = :proposal AND incarico_id = :id FOR UPDATE"),
                                 {"proposal": proposal_id, "id": engagement_id}).mappings().one_or_none()
            if proposal is None:
                raise HTTPException(404, "Proposta non trovata.")
            if proposal['stato'] not in ('proposta', 'bozza'):
                raise HTTPException(409, "Proposta già revisionata.")
            current = section_body(row['fascicolo_markdown'], proposal['sezione'])
            expected = proposal['proposto'] if proposal['stato'] == 'bozza' else proposal['precedente']
            if current != expected:
                raise HTTPException(409, "Il testo della sezione è cambiato: rivedi una nuova proposta.")
            body = proposal['proposto']
            if value.action == 'corretta':
                if not value.body or not value.body.strip() or section_titles(value.body):
                    raise HTTPException(422, "Inserisci il testo corretto della singola sezione.")
                body = value.body.strip()
            elif value.action == 'rifiutata':
                body = proposal['precedente']
            markdown = replace_section_body(row['fascicolo_markdown'], proposal['sezione'], body)
            revision_id = revision(c, engagement_id, markdown)
            protect_sections(c, engagement_id, [proposal['sezione']])
            c.execute(text("UPDATE proposte_sezione SET stato = :status WHERE id = :id"), {"id": proposal_id, "status": value.action})
            c.execute(text(
                "INSERT INTO decisioni_revisione (id, incarico_id, proposta_id, run_id, revisione_id, azione, autore, motivo) "
                "VALUES (:id, :case, :proposal, :run, :revision, :action, :author, :reason)"
            ), {"id": uuid4(), "case": engagement_id, "proposal": proposal_id, "run": proposal['run_id'],
                "revision": revision_id, "action": value.action, "author": value.author, "reason": value.reason})

    def restore(self, engagement_id: UUID, revision_id: UUID, value: ReviewInput) -> None:
        with self.engine.begin() as c:
            self.lock(c, engagement_id, value.expected_version)
            old = c.execute(text("SELECT * FROM revisioni_fascicolo WHERE id = :revision AND incarico_id = :id"),
                            {"revision": revision_id, "id": engagement_id}).mappings().one_or_none()
            if old is None:
                raise HTTPException(404, "Revisione non trovata.")
            c.execute(text("UPDATE incarichi SET revisione_modello_id = :template WHERE id = :id"),
                      {"id": engagement_id, "template": old['revisione_modello_id']})
            new_id = revision(c, engagement_id, old['fascicolo_markdown'])
            protect_sections(c, engagement_id, list(section_titles(old['fascicolo_markdown'])))
            # Relevance must be re-evaluated; decisions from a newer draft do not apply to restored text.
            c.execute(text("DELETE FROM pertinenza_sezioni WHERE incarico_id = :id"), {"id": engagement_id})
            for title in section_titles(old['fascicolo_markdown']):
                c.execute(text("INSERT INTO pertinenza_sezioni (incarico_id, sezione, stato, motivo, origine) VALUES (:id, :section, 'da_chiarire', 'Revisione ripristinata: verificare pertinenza.', 'sistema')"), {"id": engagement_id, "section": title})
            c.execute(text("UPDATE proposte_sezione SET stato = 'superata' WHERE incarico_id = :id AND stato IN ('proposta', 'bozza')"), {"id": engagement_id})
            c.execute(text("UPDATE migrazioni_fascicolo SET stato = 'superata' WHERE incarico_id = :id AND stato = 'proposta'"), {"id": engagement_id})
            c.execute(text("INSERT INTO decisioni_revisione (id, incarico_id, revisione_id, azione, autore, motivo) VALUES (:id, :case, :revision, 'ripristino', :author, :reason)"),
                      {"id": uuid4(), "case": engagement_id, "revision": new_id, "author": value.author, "reason": value.reason})

    def approve(self, engagement_id: UUID, value: ReviewInput) -> UUID:
        with self.engine.begin() as c:
            row = self.lock(c, engagement_id, value.expected_version)
            if c.execute(text("SELECT 1 FROM proposte_sezione WHERE incarico_id = :id AND stato = 'proposta'"), {"id": engagement_id}).first():
                raise HTTPException(409, "Rivedi le proposte sul testo protetto prima di approvare.")
            decisions = [dict(item) for item in c.execute(text("SELECT sezione, stato, motivo, riferimenti FROM pertinenza_sezioni WHERE incarico_id = :id"), {"id": engagement_id}).mappings()]
            runs = [dict(item) for item in c.execute(text("SELECT id, modello, versione_prompt, revisione_modello_id, domande FROM run_fascicolo WHERE incarico_id = :id ORDER BY creato_il"), {"id": engagement_id}).mappings()]
            excluded = {item['sezione'] for item in decisions if item['stato'] == 'non_pertinente'}
            markdown = exportable_dossier(row['fascicolo_markdown'], excluded)
            markdown += '\n\n## Elementi da verificare\n\n'
            unresolved = [f"- {item['sezione']}: {item['stato']} — {item['motivo']}" for item in decisions if item['stato'] in ('da_valutare', 'da_chiarire')]
            if runs:
                unresolved += [f"- {q['question']}" for q in runs[-1]['domande'] if q.get('section') not in excluded]
            markdown += '\n'.join(unresolved) or 'Nessun chiarimento strutturato aperto; restano le riserve indicate nel testo.'
            sources = self.sources(c, engagement_id)
            cited = [s for s in sources if s['id'] in markdown]
            if cited:
                markdown += '\n\n## Riferimenti verificabili\n\n' + '\n'.join(
                    f"- {s['id']}: {s['url'] or f'/api/v1/engagements/{engagement_id}/messages'}" for s in cited)
            identifier = uuid4()
            revision_id: UUID = c.execute(text("SELECT id FROM revisioni_fascicolo WHERE incarico_id = :id ORDER BY numero DESC LIMIT 1"), {"id": engagement_id}).scalar_one()
            now = datetime.now(UTC).isoformat()
            metadata = {"author": value.author, "reason": value.reason, "approved_at": now,
                        "template_revision_id": str(row['revisione_modello_id']), "runs": runs, "relevance": decisions, "sources": cited}
            markdown += f"\n\nApprovato da {value.author} il {now}. Revisione {revision_id}. Modello fascicolo {row['revisione_modello_id']}.\n"
            c.execute(text("INSERT INTO approvazioni_fascicolo (id, incarico_id, revisione_id, autore, markdown, contesto) VALUES (:id, :case, :revision, :author, :markdown, CAST(:context AS jsonb))"),
                      {"id": identifier, "case": engagement_id, "revision": revision_id, "author": value.author, "markdown": markdown, "context": json.dumps(metadata, default=str, ensure_ascii=False)})
            protect_sections(c, engagement_id, list(section_titles(row['fascicolo_markdown'])))
            for proposal in c.execute(text("SELECT id, run_id FROM proposte_sezione WHERE incarico_id = :id AND stato = 'bozza'"), {"id": engagement_id}).mappings():
                c.execute(text("INSERT INTO decisioni_revisione (id, incarico_id, proposta_id, run_id, revisione_id, azione, autore, motivo) VALUES (:id, :case, :proposal, :run, :revision, 'accettata', :author, :reason)"),
                          {"id": uuid4(), "case": engagement_id, "proposal": proposal['id'], "run": proposal['run_id'], "revision": revision_id, "author": value.author, "reason": value.reason})
            c.execute(text("UPDATE proposte_sezione SET stato = 'accettata' WHERE incarico_id = :id AND stato = 'bozza'"), {"id": engagement_id})
            c.execute(text("UPDATE incarichi SET versione_stato = versione_stato + 1 WHERE id = :id"), {"id": engagement_id})
            return identifier


def review_router(engine: Engine) -> APIRouter:
    router = APIRouter(prefix='/v1/engagements/{engagement_id}')
    store = ReviewStore(engine)

    @router.get('/review')
    def state(engagement_id: UUID) -> dict[str, Any]:
        return store.state(engagement_id)

    @router.post('/review/{proposal_id}')
    def decide(engagement_id: UUID, proposal_id: UUID, value: DecisionInput) -> dict[str, bool]:
        store.decide(engagement_id, proposal_id, value)
        return {"ok": True}

    @router.post('/restore/{revision_id}')
    def restore(engagement_id: UUID, revision_id: UUID, value: ReviewInput) -> dict[str, bool]:
        store.restore(engagement_id, revision_id, value)
        return {"ok": True}

    @router.post('/approvals')
    def approve(engagement_id: UUID, value: ReviewInput) -> dict[str, UUID]:
        return {"id": store.approve(engagement_id, value)}

    @router.get('/approvals/{approval_id}/export')
    def export(engagement_id: UUID, approval_id: UUID) -> Response:
        with engine.connect() as c:
            markdown = c.execute(text("SELECT markdown FROM approvazioni_fascicolo WHERE id = :approval AND incarico_id = :id"), {"approval": approval_id, "id": engagement_id}).scalar_one_or_none()
        if markdown is None:
            raise HTTPException(404, 'Approvazione non trovata.')
        return Response(markdown, media_type='text/markdown', headers={'Content-Disposition': f'attachment; filename="fascicolo-{approval_id}.md"'})

    return router
