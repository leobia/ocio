from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from ocio.api import PostgresStore
from ocio.company_research import (
    CompanyResearchStore,
    IdentityInput,
    PublicDecision,
    SearchResult,
)
from ocio.dossier_agent import PostgresAgentStore


def test_research_requires_identity_confirmation_and_rejects_operational_fields():
    with pytest.raises(ValidationError):
        IdentityInput(company='Fittizia', location='Sede', identifier='000', author='RSPP', confirmed=False)
    with pytest.raises(ValidationError):
        SearchResult(ambiguous=False, message='', proposals=[{'field': 'lavoratori', 'value': '12', 'url': 'https://example.org', 'source_type': 'altro'}])


@pytest.mark.integration
def test_research_keeps_proposals_out_of_agent_state_until_review(case_db):
    identifier = uuid4()
    PostgresStore(case_db).create_engagement(identifier, {'company': 'Fittizia', 'site': 'Sede', 'reference_date': '2026-10-02', 'template_revision_id': UUID('00000000-0000-4000-8000-000000000242')})
    identity = IdentityInput(company='Fittizia', location='Sede', identifier='fittizia.example', confirmed=True, author='RSPP')
    class Provider:
        def search(self, identity):
            return SearchResult(ambiguous=False, message='Verifica i dati.', proposals=[{'field': 'sito_ufficiale', 'value': 'https://fittizia.example', 'url': 'https://fittizia.example/contatti', 'source_type': 'aziendale'}])
    research = CompanyResearchStore(case_db, Provider())
    agent = PostgresAgentStore(case_db)
    research.search(identifier, identity)
    p = research.list(identifier)[0]['proposals'][0]
    assert p['status'] == 'da_verificare'
    assert p['consulted_at'] and p['url']
    assert agent.snapshot(identifier)['public_identity'] == []
    research.decide(identifier, p['id'], PublicDecision(expected_version=0, action='confermata', author='RSPP', reason='Verifica identità'))
    public = agent.snapshot(identifier)['public_identity']
    assert public[0]['value'] == 'https://fittizia.example'
    with pytest.raises(HTTPException):
        research.decide(identifier, p['id'], PublicDecision(expected_version=1, action='rifiutata', author='RSPP', reason='Duplicato'))
    class Ambiguous:
        def search(self, identity):
            return SearchResult(ambiguous=True, message='Omonimi', proposals=[{'field': 'partita_iva', 'value': '000', 'url': 'https://example.org', 'source_type': 'altro'}])
    research.provider = Ambiguous()
    research.search(identifier, identity)
    assert research.list(identifier)[0]['proposals'] == []
    class Unavailable:
        def search(self, identity):
            raise TimeoutError('Private provider detail')
    research.provider = Unavailable()
    research.search(identifier, identity)
    assert research.list(identifier)[0]['status'] == 'errore'
    assert agent.snapshot(identifier)['public_identity'] == public
