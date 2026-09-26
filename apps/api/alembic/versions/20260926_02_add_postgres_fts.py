"""Aggiunge la ricerca full-text italiana ai chunk."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260926_02"
down_revision = "20260926_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Indicizza il contenuto dei soli chunk ricercabili."""
    op.add_column(
        "chunk",
        sa.Column(
            "vettore_ricerca",
            postgresql.TSVECTOR(),
            sa.Computed(
                "to_tsvector('italian'::regconfig, contenuto)", persisted=True
            ),
        ),
    )
    op.create_index(
        "ix_chunk_vettore_ricerca_ricercabile",
        "chunk",
        ["vettore_ricerca"],
        postgresql_using="gin",
        postgresql_where=sa.text("ruolo = 'ricercabile'"),
    )


def downgrade() -> None:
    """Rimuove l'indice full-text e il relativo vettore."""
    op.drop_index("ix_chunk_vettore_ricerca_ricercabile", table_name="chunk")
    op.drop_column("chunk", "vettore_ricerca")
