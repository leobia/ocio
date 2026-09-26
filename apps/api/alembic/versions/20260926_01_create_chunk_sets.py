"""Create immutable, sourceable chunk sets."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260926_01"
down_revision = "20260925_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create chunk sets, chunks, and ordered source links."""
    op.create_table(
        "insiemi_chunk",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("strategia", sa.Text(), nullable=False),
        sa.Column("revisione", sa.Integer(), nullable=False),
        sa.Column("configurazione", postgresql.JSONB(), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "creato_il",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "strategia IN ('fixed', 'structural')",
            name="ck_insiemi_chunk_strategia",
        ),
        sa.CheckConstraint("revisione > 0", name="ck_insiemi_chunk_revisione"),
        sa.UniqueConstraint("fingerprint", name="uq_insiemi_chunk_fingerprint"),
    )
    op.create_table(
        "chunk",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "insieme_chunk_id",
            sa.BigInteger(),
            sa.ForeignKey("insiemi_chunk.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "documento_id",
            sa.BigInteger(),
            sa.ForeignKey("documenti.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("chunk_genitore_id", sa.BigInteger()),
        sa.Column("identificatore", sa.Text(), nullable=False),
        sa.Column("ruolo", sa.Text(), nullable=False),
        sa.Column("ordine", sa.Integer(), nullable=False),
        sa.Column("contenuto", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.CheckConstraint("ruolo IN ('ricercabile', 'parent')", name="ck_chunk_ruolo"),
        sa.CheckConstraint("ordine >= 0", name="ck_chunk_ordine"),
        sa.UniqueConstraint(
            "insieme_chunk_id",
            "documento_id",
            "identificatore",
            name="uq_chunk_insieme_documento_identificatore",
        ),
        sa.UniqueConstraint(
            "id",
            "insieme_chunk_id",
            "documento_id",
            name="uq_chunk_id_insieme_documento",
        ),
        sa.ForeignKeyConstraint(
            ["chunk_genitore_id", "insieme_chunk_id", "documento_id"],
            ["chunk.id", "chunk.insieme_chunk_id", "chunk.documento_id"],
            name="fk_chunk_genitore_stesso_insieme_documento",
            ondelete="RESTRICT",
        ),
    )
    op.create_table(
        "chunk_partizioni",
        sa.Column(
            "chunk_id",
            sa.BigInteger(),
            sa.ForeignKey("chunk.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("posizione", sa.Integer(), nullable=False),
        sa.Column(
            "partizione_documentale_id",
            sa.BigInteger(),
            sa.ForeignKey("partizioni_documentali.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "acquisizione_fonte_id",
            sa.BigInteger(),
            sa.ForeignKey("acquisizioni_fonti.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("identificatore_partizione", sa.Text(), nullable=False),
        sa.Column("sha256_contenuto", sa.String(length=64), nullable=False),
        sa.CheckConstraint("posizione >= 0", name="ck_chunk_partizioni_posizione"),
        sa.PrimaryKeyConstraint("chunk_id", "posizione"),
    )


def downgrade() -> None:
    """Drop chunking data."""
    op.drop_table("chunk_partizioni")
    op.drop_table("chunk")
    op.drop_table("insiemi_chunk")
