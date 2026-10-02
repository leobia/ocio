"""Versioned dossier evaluations, independent of SDK internals and editorial review."""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import yaml
from sqlalchemy import Engine, create_engine

from ocio.api import PostgresStore
from ocio.database import database_url
from ocio.dossier_agent import MAX_TOKENS, DossierAgentService, PostgresAgentStore
from ocio.dossier_prompt import PROMPT_VERSION
from ocio.engagement_evidence import OpenAIEvidenceAnalyzer, PostgresEvidenceStore
from ocio.quality import QualityStore, current_versions

ROOT = Path(__file__).resolve().parents[4]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_cases(path: Path) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text())
    if not isinstance(data, dict) or data.get('synthetic') is not True or not data.get('cases'):
        raise ValueError('La suite deve dichiarare dati fittizi e contenere casi.')
    ids = [case['id'] for case in data['cases']]
    if len(ids) != len(set(ids)):
        raise ValueError('Identificatori duplicati nel dataset.')
    for case in data['cases']:
        for name in ('company', 'template', 'descriptions', 'notes', 'reference', 'expected_relevance', 'required_terms', 'forbidden_terms'):
            if name not in case:
                raise ValueError(f"{case['id']}: manca {name}")
    return dict(data)


def evaluate_result(case: dict[str, Any], result: dict[str, Any]) -> list[str]:
    errors = [f"Analisi allegato fallita: {error}" for error in result.get('evidence_errors', [])]
    markdown = result['markdown']
    lower = markdown.casefold()
    for term in case['required_terms']:
        if term.casefold() not in lower:
            errors.append(f'Dettaglio atteso mancante: {term}')
    for term in case['forbidden_terms']:
        if term.casefold() in lower:
            errors.append(f'Affermazione non supportata: {term}')
    for section, expected in case['expected_relevance'].items():
        decision = result['relevance'].get(section, {})
        if decision.get('status') != expected or not decision.get('reason'):
            errors.append(f'{section}: pertinenza attesa {expected}, con motivazione')
        if expected == 'non_pertinente' and not decision.get('references'):
            errors.append(f'{section}: esclusione priva di provenienza')
    known = set(result['source_ids'])
    writes = []
    for run in result['runs']:
        if run['status'] == 'fallito':
            errors.append(f"Run fallito: {run['reason']}")
        questions = [re.sub(r'\W+', ' ', q['question'].casefold()).strip() for q in run['questions']]
        if len(questions) != len(set(questions)):
            errors.append('Domande duplicate nello stesso gruppo')
        if [q['impact'] for q in run['questions']] != sorted([q['impact'] for q in run['questions']], reverse=True):
            errors.append('Domande non ordinate per impatto')
        for event in run['events']:
            if event['type'] == 'knowledge_search':
                known.update(str(c['id']) for c in event['data'].get('result', {}).get('citations', []))
            if event['type'] == 'write':
                payload = event['data']['payload']
                refs = payload.get('references', [])
                if not refs or set(refs) - known or any(ref not in payload['body'] for ref in refs):
                    errors.append(f"{payload['section']}: testo senza riferimenti verificabili")
                writes.append((payload['section'], payload['body']))
            if event['type'] == 'model_usage' and event['data'].get('total_tokens', 0) > MAX_TOKENS + 3000:
                errors.append('Budget di token superato oltre la singola risposta in corso')
    if not writes:
        errors.append('Nessuna sezione completata')
    if len(result['runs']) > 1 and not any(e['type'] == 'write' for e in result['runs'][0]['events']):
        errors.append('Il primo run non completa il lavoro indipendente')
    versions = result.get('versions', {})
    for key in ('model', 'prompt', 'tools', 'corpus', 'template'):
        if not versions.get(key):
            errors.append(f'Versione assente: {key}')
    return errors


def run_dossier_evaluation(dataset: Path, output: Path, baseline: Path | None = None,
                           engine: Engine | None = None, runner: Any = None,
                           analyzer: Any = None, knowledge: Any = None) -> dict[str, Any]:
    data = load_cases(dataset)
    owned_engine = engine is None
    engine = engine or create_engine(database_url())
    promoted = QualityStore(engine).promoted()
    data['cases'].extend(promoted)
    fingerprint = dataset_fingerprint(dataset, data, promoted)
    previous = json.loads(baseline.read_text()) if baseline else None
    if previous and previous['dataset_sha256'] != fingerprint:
        raise ValueError('Baseline e risultato usano dataset diversi.')
    store = PostgresStore(engine)
    evidence = PostgresEvidenceStore(engine)
    agent_store = PostgresAgentStore(engine)
    analyzer = analyzer or OpenAIEvidenceAnalyzer()
    if knowledge is None and runner is None:
        from ocio.chat_runtime import backend_from_environment
        knowledge = backend_from_environment(engine)
    service = DossierAgentService(agent_store, evidence, knowledge, runner)
    results = []
    try:
        for case in data['cases']:
            template_id, template_revision, case_id = uuid4(), uuid4(), uuid4()
            store.create_template(template_id, template_revision, {
                'name': 'Eval ' + case['id'], 'markdown': case['template'],
                'instructions': case['descriptions'], 'relevance_guidance': case.get('relevance_guidance', {}),
            })
            store.create_engagement(case_id, {'company': case['company'], 'site': 'Sede interamente fittizia',
                                              'reference_date': '2026-10-02', 'template_revision_id': template_revision})
            runs = []
            evidence_errors = []
            source_ids = ['incarico:azienda', 'incarico:sede', 'incarico:data_riferimento']
            for index, note in enumerate([case['notes'], case.get('followup', '')]):
                if not note:
                    continue
                files = []
                for name in case.get('attachments', []) if index == 0 else case.get('followup_attachments', []):
                    path = (dataset.parent / name).resolve()
                    if not path.is_relative_to(dataset.parent.resolve()):
                        raise ValueError('Allegato esterno al dataset.')
                    media_type = 'image/png' if path.suffix == '.png' else 'text/plain'
                    files.append((path.name, media_type, path.read_bytes(), 'Descrivi solo quanto leggibile.'))
                message = evidence.add_message(case_id, note, files)
                assert message is not None
                evidence.record_note(case_id, UUID(message['id']), note)
                for attachment in message['attachments']:
                    source = evidence.attachment(case_id, UUID(attachment['id']))
                    assert source is not None
                    try:
                        method, observations = analyzer.analyze(source[2], source[1], 'Descrivi solo quanto leggibile.', list(case['descriptions']))
                        evidence.record_analysis(case_id, UUID(message['id']), UUID(attachment['id']), 'Materiale fittizio', method, observations)
                    except Exception as error:
                        reason = f"{attachment['name']}: {type(error).__name__}"
                        evidence_errors.append(reason)
                        evidence.record_error(case_id, UUID(attachment['id']), reason)
                runs.append(asyncio.run(service.execute(case_id)))
            snapshot = agent_store.snapshot(case_id)
            assert snapshot is not None
            for message in evidence.messages(case_id) or []:
                if message['role'] == 'user':
                    source_ids.append(message['id'])
                    source_ids.extend(o['id'] for o in message['observations'])
            result = {'id': case['id'], 'engagement_id': str(case_id), 'markdown': snapshot['dossier_markdown'],
                      'relevance': snapshot['relevance'], 'evidence_errors': evidence_errors, 'runs': runs, 'source_ids': source_ids,
                      'versions': {**current_versions(), 'model': runs[-1]['model'], 'prompt': PROMPT_VERSION,
                                   'corpus': digest(ROOT / 'ocio_sources.yaml'),
                                   'template': hashlib.sha256(json.dumps({k: case.get(k) for k in ('template', 'descriptions', 'relevance_guidance')}, sort_keys=True).encode()).hexdigest()},
                      'editorial_review': {'reviewed_by': case.get('reviewed_by'), 'reference': case['reference'],
                                           'rubric': data.get('rubric', []), 'scores': None}}
            result['errors'] = evaluate_result(case, result)
            results.append(result)
    finally:
        if owned_engine:
            engine.dispose()
    report = {'dataset_version': data['version'], 'dataset_sha256': fingerprint, 'cases': results,
              'passed': all(not r['errors'] for r in results),
              'human_validation_pending': any(not c.get('reviewed_by') for c in data['cases'])}
    if previous:
        before = {c['id']: c['errors'] for c in previous['cases']}
        report['regressions'] = [r['id'] for r in results if r['errors'] and not before.get(r['id'], [])]
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, default=str, indent=2) + '\n')
    return report


def dataset_fingerprint(dataset: Path, data: dict[str, Any], promoted: list[dict[str, Any]]) -> str:
    dataset_hash = hashlib.sha256(dataset.read_bytes())
    for name in sorted({name for case in data['cases'] for name in case.get('attachments', []) + case.get('followup_attachments', [])}):
        asset = (dataset.parent / name).resolve()
        if not asset.is_relative_to(dataset.parent.resolve()):
            raise ValueError('Allegato esterno al dataset.')
        dataset_hash.update(name.encode())
        dataset_hash.update(asset.read_bytes())
    dataset_hash.update(json.dumps(promoted, ensure_ascii=False, sort_keys=True).encode())
    return dataset_hash.hexdigest()


def validate_release(dataset: Path, report_path: Path, engine: Engine) -> list[str]:
    report = json.loads(report_path.read_text())
    data = load_cases(dataset)
    promoted = QualityStore(engine).promoted()
    data['cases'].extend(promoted)
    errors = []
    if report.get('dataset_sha256') != dataset_fingerprint(dataset, data, promoted):
        errors.append('Dataset o regressioni promosse cambiati: riesegui la suite.')
    if not report.get('passed') or any(c.get('errors') for c in report.get('cases', [])):
        errors.append('Gli invarianti deterministici non passano.')
    if {c['id'] for c in data['cases']} != {c['id'] for c in report.get('cases', [])}:
        errors.append('Il report non copre tutti i casi correnti.')
    for case in data['cases']:
        if not case.get('reviewed_by'):
            errors.append(f"{case['id']}: riferimento ancora da validare con un RSPP.")
    for case in report.get('cases', []):
        if any(case.get('versions', {}).get(k) != v for k, v in current_versions().items()):
            errors.append(f"{case['id']}: prompt, tool o corpus diversi dal codice corrente.")
        if case.get('versions', {}).get('model') != os.environ.get('OCIO_DOSSIER_MODEL', 'gpt-4.1'):
            errors.append(f"{case['id']}: modello diverso dalla configurazione corrente.")
        review = case.get('editorial_review', {})
        scores = review.get('scores')
        if not review.get('reviewed_by') or not isinstance(scores, dict) or set(scores) != set(data.get('rubric', [])) or not all(isinstance(v, int) and 1 <= v <= 5 for v in scores.values()):
            errors.append(f"{case['id']}: valutazione editoriale incompleta.")
    return errors
