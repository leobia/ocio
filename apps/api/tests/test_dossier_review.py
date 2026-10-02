"""Exercise review transactions against PostgreSQL, without provider calls."""
import runpy
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from fastapi import HTTPException
from sqlalchemy import create_engine, text

from ocio.api import PostgresStore
from ocio.database import database_url
from ocio.dossier_agent import PostgresAgentStore
from ocio.dossier_review import DecisionInput, ReviewInput, ReviewStore


@pytest.fixture
def case_db():
    try:
        url = database_url()
    except RuntimeError:
        pytest.skip('PostgreSQL environment not configured')
    root = create_engine(url)
    schema = f'test_review_{uuid4().hex}'
    with root.begin() as c:
        c.execute(text(f'CREATE SCHEMA "{schema}"'))
    engine = create_engine(url, connect_args={'options': f'-csearch_path={schema}'})
    try:
        with engine.begin() as c, Operations.context(MigrationContext.configure(c)):
            for name in ['20260929_01_create_engagements.py', '20260930_01_engagement_evidence.py', '20260930_02_dossier_agent.py', '20261002_01_dossier_review.py']:
                runpy.run_path(str(Path(__file__).parents[1] / 'alembic/versions' / name))['upgrade']()
        yield engine
    finally:
        engine.dispose()
        with root.begin() as c:
            c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        root.dispose()


@pytest.mark.integration
def test_protected_proposals_review_approval_and_restore(case_db):
    store = PostgresStore(case_db)
    agent = PostgresAgentStore(case_db)
    review = ReviewStore(case_db)
    identifier = uuid4()
    store.create_engagement(identifier, {'company': 'Impresa fittizia', 'site': 'Sede fittizia', 'reference_date': '2026-10-02', 'template_revision_id': UUID('00000000-0000-4000-8000-000000000242')})
    original = store.update_dossier(identifier, '# Fascicolo\n\n## Attività\n\nTesto manuale.\n\n## Chimico\n\nDa chiarire.')
    run = agent.start(identifier, 'test-model')
    version = agent.snapshot(identifier)['version']
    version = agent.effect(run, uuid4(), version, 'relevance', {'section': 'Attività', 'status': 'pertinente', 'reason': 'Identità confermata', 'references': ['incarico:azienda']})['version']
    result = agent.effect(run, uuid4(), version, 'write', {'section': 'Attività', 'body': 'Attività di incarico:azienda da verificare.', 'references': ['incarico:azienda']})
    assert result['status'] == 'proposed'
    assert 'Testo manuale.' in store.engagement(identifier)['dossier_markdown']
    agent.finish(run, 'completato', 'Bozza pronta')
    proposal = review.state(identifier)['proposals'][0]
    version = agent.snapshot(identifier)['version']
    with pytest.raises(HTTPException) as stale:
        review.decide(identifier, proposal['id'], DecisionInput(expected_version=version-1, author='RSPP prova', reason='Verifica', action='accettata'))
    assert stale.value.status_code == 409
    review.decide(identifier, proposal['id'], DecisionInput(expected_version=version, author='RSPP prova', reason='Correzione circoscritta', action='corretta', body='Testo verificato.'))
    version = agent.snapshot(identifier)['version']
    approval = review.approve(identifier, ReviewInput(expected_version=version, author='RSPP prova', reason='Revisione con riserve'))
    with case_db.connect() as c:
        exported = c.execute(text('SELECT markdown FROM approvazioni_fascicolo WHERE id = :id'), {'id': approval}).scalar_one()
        assert 'Testo verificato.' in exported
        assert 'Chimico' in exported and 'da_valutare' in exported
        assert 'RSPP prova' in exported
        assert c.execute(text('SELECT count(*) FROM decisioni_revisione')).scalar_one() == 1
    store.update_dossier(identifier, '# Fascicolo\n\n## Attività\n\nNuovo contenuto.')
    with case_db.connect() as c:
        assert c.execute(text('SELECT markdown FROM approvazioni_fascicolo WHERE id = :id'), {'id': approval}).scalar_one() == exported
    review.restore(identifier, UUID(original['history'][0]['id']), ReviewInput(expected_version=agent.snapshot(identifier)['version'], author='RSPP prova', reason='Ripristino'))
    assert 'Testo manuale.' in store.engagement(identifier)['dossier_markdown']
    assert store.engagement(identifier)['relevance']['Chimico']['status'] == 'da_chiarire'


@pytest.mark.integration
def test_agent_draft_rejection_and_export_exclusion(case_db):
    store = PostgresStore(case_db)
    agent = PostgresAgentStore(case_db)
    review = ReviewStore(case_db)
    identifier = uuid4()
    store.create_engagement(identifier, {'company': 'Fittizia', 'site': 'Sede', 'reference_date': '2026-10-02', 'template_revision_id': UUID('00000000-0000-4000-8000-000000000242')})
    title = '1. Anagrafica e organizzazione'
    run = agent.start(identifier, 'test-model')
    version = agent.effect(run, uuid4(), 0, 'relevance', {'section': title, 'status': 'pertinente', 'reason': 'Identità', 'references': ['incarico:azienda']})['version']
    payload = {'section': title, 'body': 'Fonte incarico:azienda.', 'references': ['incarico:azienda']}
    version = agent.effect(run, uuid4(), version, 'write', payload)['version']
    agent.effect(run, uuid4(), version, 'write', payload)
    assert len(review.state(identifier)['proposals']) == 1
    agent.finish(run, 'completato', 'Bozza')
    p = review.state(identifier)['proposals'][0]
    review.decide(identifier, p['id'], DecisionInput(expected_version=agent.snapshot(identifier)['version'], author='RSPP', reason='Rifiuto', action='rifiutata'))
    assert 'Fonte incarico:azienda.' not in agent.snapshot(identifier)['dossier_markdown']
    agent.relevance(identifier, title, 'non_pertinente', 'Esclusa dal RSPP', [])
    approval = review.approve(identifier, ReviewInput(expected_version=agent.snapshot(identifier)['version'], author='RSPP', reason='Riserve esplicite'))
    with case_db.connect() as c:
        markdown = c.execute(text('SELECT markdown FROM approvazioni_fascicolo WHERE id = :id'), {'id': approval}).scalar_one()
        assert '## ' + title not in markdown
