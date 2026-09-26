"""Aggiunge un indice BM25 isolato per ogni insieme di chunk."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260926_03"
down_revision = "20260926_02"
branch_labels = None
depends_on = None


def _index_name(chunk_set_id: int) -> str:
    return f"ix_chunk_contenuto_bm25_insieme_{chunk_set_id}"


def upgrade() -> None:
    """Create an Italian partial BM25 index for every existing chunk set."""
    connection = op.get_bind()
    chunk_set_ids = connection.execute(
        sa.text("SELECT id FROM insiemi_chunk ORDER BY id")
    ).scalars()
    for chunk_set_id in chunk_set_ids:
        set_id = int(chunk_set_id)
        op.execute(
            "CREATE INDEX IF NOT EXISTS "
            f"{_index_name(set_id)} ON chunk USING bm25 (contenuto) "
            "WITH (text_config = 'italian', k1 = 1.2, b = 0.75) "
            f"WHERE insieme_chunk_id = {set_id} AND ruolo = 'ricercabile'"
        )


def downgrade() -> None:
    """Drop the per-set BM25 indexes."""
    connection = op.get_bind()
    index_names = connection.execute(
        sa.text(
            "SELECT indexname FROM pg_indexes "
            "WHERE schemaname = current_schema() AND tablename = 'chunk' "
            "AND indexname LIKE 'ix_chunk_contenuto_bm25_insieme_%'"
        )
    ).scalars()
    for index_name in index_names:
        if str(index_name).removeprefix(
            "ix_chunk_contenuto_bm25_insieme_"
        ).isdigit():
            op.execute(f"DROP INDEX IF EXISTS {index_name}")
