"""Aggiunge gli embedding dense dei contenuti e i relativi indici HNSW."""

from __future__ import annotations

from alembic import op

revision = "20260926_04"
down_revision = "20260926_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Conserva una riga per contenuto per entrambi i modelli supportati."""
    op.execute(
        "CREATE TABLE embedding_contenuti ("
        "sha256_contenuto char(64) PRIMARY KEY, "
        "embedding_small vector(1536), "
        "embedding_large vector(3072), "
        "CONSTRAINT ck_embedding_contenuti_presente CHECK ("
        "embedding_small IS NOT NULL OR embedding_large IS NOT NULL))"
    )
    op.execute(
        "CREATE INDEX ix_embedding_contenuti_small_hnsw "
        "ON embedding_contenuti USING hnsw (embedding_small vector_ip_ops) "
        "WHERE embedding_small IS NOT NULL"
    )
    # pgvector indicizza vector fino a 2000 dimensioni, ma halfvec fino a 4000.
    op.execute(
        "CREATE INDEX ix_embedding_contenuti_large_halfvec_hnsw "
        "ON embedding_contenuti USING hnsw "
        "((embedding_large::halfvec(3072)) halfvec_ip_ops) "
        "WHERE embedding_large IS NOT NULL"
    )


def downgrade() -> None:
    """Rimuove gli indici e gli embedding dense."""
    op.drop_table("embedding_contenuti")
