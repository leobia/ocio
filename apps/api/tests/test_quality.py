from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import text

from ocio.api import PostgresStore
from ocio.dossier_agent import PostgresAgentStore
from ocio.dossier_review import DecisionInput, ReviewStore
from ocio.quality import QualityDecision, QualitySignal, QualityStore, RegressionCase


def regression_case():
    return RegressionCase(company='Impresa sintetica Beta', template='## Attività\n', descriptions={'Attività': 'Descrivere gli appunti.'}, notes='Due postazioni amministrative.', expected_relevance={'Attività': 'pertinente'}, required_terms=['postazioni'], forbidden_terms=['azienda conforme'], reference='Sono documentate due postazioni amministrative.')


def test_regression_requires_defined_sections_and_no_contact_details():
    case = regression_case().model_dump()
    with pytest.raises(ValidationError):
        RegressionCase(**{**case, 'notes': 'Scrivere a reale@example.org'})
    with pytest.raises(ValidationError):
        RegressionCase(**{**case, 'expected_relevance': {}})


@pytest.mark.integration
def test_feedback_is_correlated_local_correction_and_promotion_are_reversible(case_db):
    identifier = uuid4()
    store = PostgresStore(case_db)
    store.create_engagement(identifier, {'company': 'Nome azienda originale', 'site': 'Sede', 'reference_date': '2026-10-02', 'template_revision_id': UUID('00000000-0000-4000-8000-000000000242')})
    store.update_dossier(identifier, '## Attività\n\nAppunto originale.')
    agent = PostgresAgentStore(case_db)
    run = agent.start(identifier, 'test-model')
    version = agent.snapshot(identifier)['version']
    version = agent.effect(run, uuid4(), version, 'relevance', {'section': 'Attività', 'status': 'pertinente', 'reason': 'Dati iniziali', 'references': ['incarico:azienda']})['version']
    agent.effect(run, uuid4(), version, 'write', {'section': 'Attività', 'body': 'Proposta su incarico:azienda.', 'references': ['incarico:azienda']})
    agent.finish(run, 'completato', 'Bozza')
    review = ReviewStore(case_db)
    proposal = review.state(identifier)['proposals'][0]
    review.decide(identifier, proposal['id'], DecisionInput(action='rifiutata', expected_version=agent.snapshot(identifier)['version'], author='RSPP', reason='Dato errato'))
    quality = QualityStore(case_db)
    candidate = quality.inbox()[0]
    assert candidate['run_id'] == run
    assert candidate['revision_id']
    assert 'Nome azienda originale' not in str(candidate)
    local = QualityDecision(action='solo_incarico', cause='dato_del_caso', author='Responsabile', reason='Correzione del solo caso', body='Attività amministrativa verificata.', expected_version=agent.snapshot(identifier)['version'])
    quality.decide(candidate['id'], local)
    assert 'Attività amministrativa verificata.' in agent.snapshot(identifier)['dossier_markdown']
    assert quality.promoted() == []
    quality.decide(candidate['id'], QualityDecision(action='aperto', cause='output_finale', author='Responsabile', reason='Valutare regressione'))
    with pytest.raises(HTTPException):
        quality.decide(candidate['id'], QualityDecision(action='regressione', cause='output_finale', author='Responsabile', reason='Caso minimo', regression_case=regression_case()))
    quality.decide(candidate['id'], QualityDecision(action='regressione', cause='output_finale', author='Responsabile', reason='Caso minimo', regression_case=regression_case(), anonymized_confirmed=True))
    assert len(quality.promoted()) == 1
    assert quality.promoted()[0]['reviewed_by'] == 'Responsabile'
    history = quality.history(candidate['id'])
    assert history[-1]['versions']['origin']['modello'] == 'test-model'
    assert history[-1]['created_at']
    quality.decide(candidate['id'], QualityDecision(action='aperto', cause='output_finale', author='Responsabile', reason='Revoca promozione'))
    assert quality.promoted() == []
    assert len(quality.history(candidate['id'])) == 4
    for category in ('fatto_errato', 'omissione', 'domanda_superflua', 'citazione_inadeguata'):
        quality.signal(identifier, QualitySignal(category=category, section='Attività', detail='Problema riproducibile senza dati personali.', author='RSPP', expected_version=agent.snapshot(identifier)['version']))
    with case_db.connect() as c:
        assert c.execute(text('SELECT count(*) FROM candidati_qualita')).scalar_one() == 5
