"""Create the canonical corpus schema."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260921_02"
down_revision = "20260921_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create normative acts, source acquisitions, redactions, and partitions."""
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.create_table(
        "atti_normativi",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("urn", sa.Text(), nullable=False),
        sa.Column("titolo", sa.Text(), nullable=False),
        sa.UniqueConstraint("urn", name="uq_atti_normativi_urn"),
    )
    op.create_table(
        "acquisizioni_fonti",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("fonte", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("contenuto", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column(
            "acquisita_il",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "fonte", "sha256", name="uq_acquisizioni_fonti_fonte_sha256"
        ),
    )
    op.create_table(
        "redazioni",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "atto_normativo_id",
            sa.BigInteger(),
            sa.ForeignKey("atti_normativi.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "acquisizione_fonte_id",
            sa.BigInteger(),
            sa.ForeignKey("acquisizioni_fonti.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("vigente_dal", sa.Date(), nullable=False),
        sa.Column("vigente_al", sa.Date()),
        sa.CheckConstraint(
            "vigente_al IS NULL OR vigente_al > vigente_dal",
            name="ck_redazioni_intervallo_vigenza_positivo",
        ),
    )
    op.execute(
        "ALTER TABLE redazioni ADD CONSTRAINT "
        "ex_redazioni_atto_intervallo_vigenza "
        "EXCLUDE USING gist ("
        "atto_normativo_id WITH =, "
        "daterange(vigente_dal, vigente_al, '[)') WITH &&)"
    )
    op.create_table(
        "partizioni_normative",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column(
            "redazione_id",
            sa.BigInteger(),
            sa.ForeignKey("redazioni.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "partizione_genitore_id",
            sa.BigInteger(),
        ),
        sa.Column("identificatore", sa.Text(), nullable=False),
        sa.Column("tipo", sa.Text(), nullable=False),
        sa.Column("ordine", sa.Integer(), nullable=False),
        sa.Column("contenuto", sa.Text(), nullable=False),
        sa.UniqueConstraint(
            "redazione_id",
            "identificatore",
            name="uq_partizioni_normative_redazione_identificatore",
        ),
        sa.UniqueConstraint(
            "id",
            "redazione_id",
            name="uq_partizioni_normative_id_redazione",
        ),
        sa.ForeignKeyConstraint(
            ["partizione_genitore_id", "redazione_id"],
            ["partizioni_normative.id", "partizioni_normative.redazione_id"],
            name="fk_partizioni_normative_genitore_stessa_redazione",
            ondelete="CASCADE",
        ),
    )


def downgrade() -> None:
    """Drop the canonical corpus schema."""
    op.drop_table("partizioni_normative")
    op.drop_table("redazioni")
    op.drop_table("acquisizioni_fonti")
    op.drop_table("atti_normativi")
