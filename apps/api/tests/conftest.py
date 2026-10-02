import runpy
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, text

from ocio.database import database_url


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
            for name in ['20260929_01_create_engagements.py', '20260930_01_engagement_evidence.py', '20260930_02_dossier_agent.py', '20261002_01_dossier_review.py', '20261002_02_company_research.py']:
                runpy.run_path(str(Path(__file__).parents[1] / 'alembic/versions' / name))['upgrade']()
        yield engine
    finally:
        engine.dispose()
        with root.begin() as c:
            c.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        root.dispose()


