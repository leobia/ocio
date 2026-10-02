import asyncio
import copy
import json
from types import SimpleNamespace
from uuid import uuid4

import pytest

from ocio.dossier_evaluation import (
    ROOT,
    evaluate_result,
    load_cases,
    run_dossier_evaluation,
)

DATASET = ROOT / 'evaluation/dossier/cases-v1.yaml'


@pytest.mark.integration
def test_evaluation_runs_real_persistence_with_synthetic_cases_and_compares_baseline(case_db, tmp_path):
    cases = load_cases(DATASET)['cases']
    class Analyzer:
        def analyze(self, content, media_type, instruction, sections):
            assert media_type in ('text/plain', 'image/png') and content
            return 'fixture-v1', [{'information': 'Materiale fittizio', 'status': 'osservato', 'text': 'Schema fittizio, non in scala.', 'position': 'schema', 'section': sections[0]}]
    async def runner(run_id, instructions, payload, service):
        case = next(c for c in cases if c['company'] == payload['engagement']['company'])
        version = payload['engagement']['version']
        refs = [m['id'] for m in payload['messages'] if m['role'] == 'user']
        def effect(kind, values):
            nonlocal version
            operation = uuid4()
            result = service.store.effect(run_id, operation, version, kind, values)
            # Network retry preserves both revision and operation result.
            assert service.store.effect(run_id, operation, version, kind, values) == result
            version = result['version']
        effect('plan', {'plan': 'Completare sezioni indipendenti, poi chiedere chiarimenti.'})
        for section, status in case['expected_relevance'].items():
            if status == 'non_pertinente' and not payload['previous_run']:
                status = 'da_chiarire'
            effect('relevance', {'section': section, 'status': status, 'reason': 'Evidenze dell’operatore', 'references': refs})
            if status == 'pertinente':
                effect('write', {'section': section, 'body': case['reference'] + '\n\nEvidenze: ' + ', '.join(refs), 'references': refs})
        if not payload['previous_run']:
            effect('question', {'section': next(iter(case['expected_relevance'])), 'question': 'Puoi chiarire le informazioni mancanti?', 'impact': 4})
        return 'Bozza da revisionare.'
    first = run_dossier_evaluation(DATASET, tmp_path / 'baseline.json', engine=case_db, runner=runner, analyzer=Analyzer())
    assert first['passed'], [c['errors'] for c in first['cases']]
    assert first['human_validation_pending'] is True
    second = run_dossier_evaluation(DATASET, tmp_path / 'result.json', baseline=tmp_path / 'baseline.json', engine=case_db, runner=runner, analyzer=Analyzer())
    assert second['regressions'] == []
    broken = copy.deepcopy(first['cases'][0])
    broken['markdown'] += '\nAzienda conforme'
    broken['runs'][0]['events'].append({'type': 'write', 'data': {'payload': {'section': 'Attività', 'body': 'Fatto inventato.', 'references': ['inesistente']}}})
    broken['versions'].pop('corpus')
    errors = evaluate_result(cases[0], broken)
    assert any('non supportata' in error for error in errors)
    assert any('riferimenti verificabili' in error for error in errors)
    assert 'Versione assente: corpus' in errors
    changed = json.loads((tmp_path / 'baseline.json').read_text())
    changed['dataset_sha256'] = 'other'
    (tmp_path / 'other.json').write_text(json.dumps(changed))
    with pytest.raises(ValueError, match='dataset diversi'):
        run_dossier_evaluation(DATASET, tmp_path / 'bad.json', baseline=tmp_path / 'other.json', engine=case_db, runner=runner, analyzer=Analyzer())


def test_sdk_budget_stops_and_tool_errors_are_recoverable(monkeypatch):
    from agents import RunContextWrapper, Runner

    from ocio.dossier_agent import MAX_TOKENS, DossierAgentService
    events = []
    class Store:
        def event(self, run, kind, data):
            events.append((kind, data))
        def effect(self, *args):
            raise ValueError('Riferimento inesistente')
    async def inspect(agent, input, **kwargs):
        context = RunContextWrapper(context=None)
        tool = next(t for t in agent.tools if t.name == 'write_section')
        reply = await tool.on_invoke_tool(context, json.dumps({'operation_id': str(uuid4()), 'expected_version': 0, 'section': 'A', 'body': 'Non sostenuto', 'references': []}))
        assert 'error' in reply.lower()
        usage = SimpleNamespace(total_tokens=MAX_TOKENS, input_tokens=MAX_TOKENS-1, output_tokens=1)
        with pytest.raises(RuntimeError, match='Budget'):
            await kwargs['hooks'].on_llm_end(context, agent, SimpleNamespace(usage=usage))
        return SimpleNamespace(final_output='Controlli eseguiti')
    monkeypatch.setattr(Runner, 'run', inspect)
    asyncio.run(DossierAgentService(Store(), None)._run_sdk(uuid4(), 'gpt-4.1', 'Test', {'engagement': {'id': str(uuid4())}}))
    assert events[-1][0] == 'model_usage'


@pytest.mark.integration
def test_release_gate_rejects_stale_or_unreviewed_reports(case_db, tmp_path):
    from ocio.dossier_evaluation import dataset_fingerprint, validate_release
    from ocio.quality import current_versions
    data = load_cases(DATASET)
    report = {'dataset_sha256': dataset_fingerprint(DATASET, data, []), 'passed': True, 'cases': [
        {'id': c['id'], 'errors': [], 'versions': {**current_versions(), 'model': 'gpt-4.1'}, 'editorial_review': {}}
        for c in data['cases']
    ]}
    path = tmp_path / 'report.json'
    path.write_text(json.dumps(report))
    errors = validate_release(DATASET, path, case_db)
    assert any('RSPP' in e for e in errors)
    assert any('editoriale incompleta' in e for e in errors)
    report['dataset_sha256'] = 'outdated'
    report['cases'][0]['versions']['tools'] = 'outdated'
    path.write_text(json.dumps(report))
    errors = validate_release(DATASET, path, case_db)
    assert any('riesegui' in e for e in errors)
    assert any('codice corrente' in e for e in errors)
