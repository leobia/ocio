"""Aggiunge i marcatori giuridici canonici alle partizioni."""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "20260927_01"
down_revision = "20260926_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("partizioni_documentali", sa.Column("marcatore", sa.Text()))
    # Il backfill mantiene utilizzabili i corpus già normalizzati. Le successive
    # normalizzazioni scrivono il valore direttamente dai parser.
    op.execute(
        "UPDATE partizioni_documentali SET marcatore = CASE "
        "WHEN tipo = 'articolo' THEN substring(identificatore FROM "
        "'art[-_]([0-9]+(-bis|-ter|-quater)?)') "
        "WHEN tipo = 'comma' AND identificatore LIKE '%comma-%' "
        "THEN substring(identificatore FROM 'comma-([0-9]+(-bis|-ter|-quater)?)') "
        "WHEN tipo = 'comma' THEN substring(identificatore FROM "
        "'para_([0-9]+(-bis|-ter|-quater)?)') "
        "WHEN tipo = 'lettera' AND identificatore LIKE '%lettera-%' "
        "THEN substring(identificatore FROM 'lettera-([a-z])') "
        "WHEN tipo = 'lettera' THEN substring(identificatore FROM "
        "'point_([a-z])') END"
    )
    op.create_index(
        "ix_partizioni_documentali_riferimento",
        "partizioni_documentali",
        ["documento_id", "tipo", "marcatore"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_partizioni_documentali_riferimento",
        table_name="partizioni_documentali",
    )
    op.drop_column("partizioni_documentali", "marcatore")
