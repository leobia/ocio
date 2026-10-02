"""Explicit quality decisions and reversible, anonymized regression promotion."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import Engine, text

from ocio.dossier import replace_section_body, section_titles, validate_instructions
from ocio.dossier_prompt import PROMPT_VERSION
from ocio.dossier_review import ReviewStore, protect_sections, revision

ROOT = Path(__file__).resolve().parents[4]


def current_versions() -> dict[str, str]:
    return {'prompt': PROMPT_VERSION,
            'prompt_sha256': hashlib.sha256(Path(__file__).with_name('dossier_prompt.py').read_bytes()).hexdigest(),
            'tools': hashlib.sha256(Path(__file__).with_name('dossier_agent.py').read_bytes()).hexdigest(),
            'corpus': hashlib.sha256((ROOT / 'ocio_sources.yaml').read_bytes()).hexdigest()}


class QualitySignal(BaseModel):
    category: Literal['fatto_errato', 'omissione', 'domanda_superflua', 'citazione_inadeguata']
    section: str | None = Field(default=None, max_length=300)
    detail: str = Field(min_length=1, max_length=500, pattern=r'\S')
    author: str = Field(min_length=1, max_length=200, pattern=r'\S')
    expected_version: int = Field(ge=0)


class RegressionCase(BaseModel):
    company: str = Field(min_length=1, max_length=200)
    template: str = Field(min_length=1, max_length=20000)
    descriptions: dict[str, str]
    relevance_guidance: dict[str, str] = Field(default_factory=dict)
    notes: str = Field(min_length=1, max_length=10000)
    followup: str = Field(default='', max_length=10000)
    expected_relevance: dict[str, Literal['pertinente', 'non_pertinente', 'da_chiarire']]
    required_terms: list[str]
    forbidden_terms: list[str]
    reference: str = Field(min_length=1, max_length=10000)

    @model_validator(mode='after')
    def valid(self) -> RegressionCase:
        validate_instructions(self.template, self.descriptions)
        validate_instructions(self.template, self.relevance_guidance)
        if set(self.expected_relevance) != set(section_titles(self.template)):
            raise ValueError('Definisci la pertinenza attesa per ogni sezione.')
        serialized = self.model_dump_json()
        if re.search(r'https?://|[\w.+-]+@[\w.-]+\.[a-z]{2,}|\b\d{8,}\b|[0-9a-f]{8}-[0-9a-f-]{27,}', serialized, re.I):
            raise ValueError('Rimuovi contatti, identificatori e URL aziendali dal caso anonimizzato.')
        if not self.required_terms or any(not term.strip() for term in self.required_terms + self.forbidden_terms):
            raise ValueError('Definisci controlli non vuoti per il caso di regressione.')
        return self


class QualityDecision(BaseModel):
    cause: Literal['dato_del_caso', 'estrazione', 'ricerca_normativa', 'scelta_tool', 'istruzione', 'output_finale']
    action: Literal['scartato', 'solo_incarico', 'regressione', 'aperto']
    author: str = Field(min_length=1, max_length=200, pattern=r'\S')
    reason: str = Field(min_length=1, max_length=2000, pattern=r'\S')
    expected_version: int | None = Field(default=None, ge=0)
    body: str | None = Field(default=None, max_length=500_000)
    regression_case: RegressionCase | None = None
    anonymized_confirmed: bool = False


class QualityStore:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def inbox(self) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            # No company names, notes, documents or extracted passages in the inbox.
            return [dict(row) for row in c.execute(text(
                'SELECT id, incarico_id AS engagement_id, run_id, revisione_id AS revision_id, '
                'sezione AS section, categoria AS category, dettaglio AS detail, autore AS author, '
                'causa AS cause, stato AS status, creata_il AS created_at FROM candidati_qualita ORDER BY creata_il DESC, id DESC'
            )).mappings()]

    def signal(self, engagement_id: UUID, value: QualitySignal) -> UUID:
        with self.engine.begin() as c:
            state = ReviewStore.lock(c, engagement_id, value.expected_version)
            if value.section and value.section not in section_titles(state['fascicolo_markdown']):
                raise HTTPException(422, 'Sezione inesistente.')
            identifier = uuid4()
            c.execute(text(
                'INSERT INTO candidati_qualita (id, incarico_id, run_id, revisione_id, sezione, categoria, dettaglio, autore) '
                'VALUES (:id, :case, (SELECT id FROM run_fascicolo WHERE incarico_id = :case ORDER BY creato_il DESC LIMIT 1), '
                '(SELECT id FROM revisioni_fascicolo WHERE incarico_id = :case ORDER BY numero DESC LIMIT 1), :section, :category, :detail, :author)'
            ), {'id': identifier, 'case': engagement_id, 'section': value.section, 'category': value.category, 'detail': value.detail, 'author': value.author})
            return identifier

    def decide(self, identifier: UUID, value: QualityDecision) -> None:
        with self.engine.begin() as c:
            row = c.execute(text('SELECT * FROM candidati_qualita WHERE id = :id FOR UPDATE'), {'id': identifier}).mappings().one_or_none()
            if row is None:
                raise HTTPException(404, 'Candidato non trovato.')
            if row['stato'] != 'aperto' and value.action != 'aperto':
                raise HTTPException(409, 'Riapri il candidato prima di cambiare decisione.')
            regression = None
            if value.action == 'regressione':
                if not value.anonymized_confirmed or value.regression_case is None:
                    raise HTTPException(422, 'Serve un caso riscritto e una conferma esplicita dell’anonimizzazione.')
                regression = value.regression_case.model_dump()
                company: str = c.execute(text('SELECT azienda FROM incarichi WHERE id = :id'), {'id': row['incarico_id']}).scalar_one()
                if company.casefold() in json.dumps(regression, ensure_ascii=False).casefold():
                    raise HTTPException(422, 'Sostituisci il nome dell’impresa originale.')
                regression.update({'id': 'quality-' + str(identifier), 'reviewed_by': value.author, 'attachments': []})
            if value.action == 'solo_incarico':
                if not row['sezione'] or value.expected_version is None or not value.body or not value.body.strip():
                    raise HTTPException(422, 'Indica sezione, testo corretto e versione corrente dell’incarico.')
                state = ReviewStore.lock(c, row['incarico_id'], value.expected_version)
                if section_titles(value.body):
                    raise HTTPException(422, 'Correggi una sola sezione.')
                if row['sezione'] not in section_titles(state['fascicolo_markdown']):
                    raise HTTPException(409, 'La sezione non esiste più: rivedi l’incarico.')
                sources = ReviewStore.sources(c, row['incarico_id'])
                known_urls = {s['url'] for s in sources if s['url']}
                if set(re.findall(r'https?://[^\s)\]]+', value.body)) - known_urls:
                    raise HTTPException(422, 'Le nuove fonti normative passano dal registro e dalla pipeline del corpus.')
                markdown = replace_section_body(state['fascicolo_markdown'], row['sezione'], value.body)
                revision(c, row['incarico_id'], markdown)
                protect_sections(c, row['incarico_id'], [row['sezione']])
            versions: dict[str, Any] = current_versions()
            if row['run_id']:
                run = c.execute(text('SELECT modello, versione_prompt, revisione_modello_id FROM run_fascicolo WHERE id = :id'), {'id': row['run_id']}).mappings().one()
                versions['origin'] = dict(run)
            c.execute(text('INSERT INTO decisioni_qualita (id, candidato_id, autore, motivo, ambito, causa, versioni, caso_anonimo) VALUES (:id, :candidate, :author, :reason, :scope, :cause, CAST(:versions AS jsonb), CAST(:regression AS jsonb))'),
                      {'id': uuid4(), 'candidate': identifier, 'author': value.author, 'reason': value.reason, 'scope': value.action, 'cause': value.cause, 'versions': json.dumps(versions, default=str), 'regression': json.dumps(regression, ensure_ascii=False)})
            c.execute(text('UPDATE candidati_qualita SET stato = :status, causa = :cause, caso_anonimo = CAST(:regression AS jsonb) WHERE id = :id'),
                      {'id': identifier, 'status': value.action, 'cause': value.cause, 'regression': json.dumps(regression, ensure_ascii=False)})

    def history(self, identifier: UUID) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            return [dict(row) for row in c.execute(text('SELECT autore AS author, motivo AS reason, ambito AS scope, causa AS cause, versioni AS versions, creata_il AS created_at FROM decisioni_qualita WHERE candidato_id = :id ORDER BY creata_il, id'), {'id': identifier}).mappings()]

    def promoted(self) -> list[dict[str, Any]]:
        with self.engine.connect() as c:
            return list(c.execute(text("SELECT caso_anonimo FROM candidati_qualita WHERE stato = 'regressione' ORDER BY id")).scalars())


def quality_router(engine: Engine) -> APIRouter:
    router = APIRouter(prefix='/v1')
    store = QualityStore(engine)

    @router.get('/quality')
    def inbox() -> list[dict[str, Any]]:
        return store.inbox()

    @router.post('/engagements/{engagement_id}/quality')
    def signal(engagement_id: UUID, value: QualitySignal) -> dict[str, UUID]:
        return {'id': store.signal(engagement_id, value)}

    @router.post('/quality/{candidate_id}')
    def decide(candidate_id: UUID, value: QualityDecision) -> dict[str, bool]:
        store.decide(candidate_id, value)
        return {'ok': True}

    @router.get('/quality/{candidate_id}/history')
    def history(candidate_id: UUID) -> list[dict[str, Any]]:
        return store.history(candidate_id)

    return router
