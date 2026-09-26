"""Store the current parsed document structure and its source locations."""

from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "20260925_01"
down_revision = "20260923_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Replace historical redactions with one current document structure."""
    op.add_column("atti_normativi", sa.Column("codice", sa.Text(), nullable=True))
    op.add_column(
        "atti_normativi",
        sa.Column("tipo_documento", sa.Text(), nullable=False, server_default="atto_normativo"),
    )
    op.add_column("atti_normativi", sa.Column("vigente_dal", sa.Date()))
    op.add_column("atti_normativi", sa.Column("vigente_al", sa.Date()))
    op.add_column("atti_normativi", sa.Column("snapshot_al", sa.Date()))
    op.add_column("atti_normativi", sa.Column("pubblicato_il", sa.Date()))
    op.add_column(
        "atti_normativi",
        sa.Column("abilitato_per_agente", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.execute(
        "UPDATE atti_normativi SET codice = 'legacy-' || id::text "
        "WHERE codice IS NULL"
    )

    op.add_column(
        "partizioni_normative",
        sa.Column("documento_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "partizioni_normative",
        sa.Column("acquisizione_fonte_id", sa.BigInteger(), nullable=True),
    )
    op.add_column("partizioni_normative", sa.Column("rubrica", sa.Text()))
    op.add_column(
        "partizioni_normative",
        sa.Column(
            "localizzatore",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column("partizioni_normative", sa.Column("vigente_dal", sa.Date()))
    op.add_column("partizioni_normative", sa.Column("vigente_al", sa.Date()))

    op.execute(
        "WITH current_redazioni AS ("
        "  SELECT DISTINCT ON (atto_normativo_id) "
        "         id, atto_normativo_id, acquisizione_fonte_id, vigente_dal, vigente_al "
        "  FROM redazioni "
        "  ORDER BY atto_normativo_id, vigente_dal DESC, id DESC"
        ") "
        "UPDATE atti_normativi AS atto "
        "SET vigente_dal = redazione.vigente_dal, "
        "    vigente_al = redazione.vigente_al, "
        "    snapshot_al = CASE "
        "      WHEN acquisizione.metadati->>'snapshot_as_of' ~ '^\\d{4}-\\d{2}-\\d{2}$' "
        "      THEN (acquisizione.metadati->>'snapshot_as_of')::date END, "
        "    pubblicato_il = CASE "
        "      WHEN acquisizione.metadati->>'published_on' ~ '^\\d{4}-\\d{2}-\\d{2}$' "
        "      THEN (acquisizione.metadati->>'published_on')::date END "
        "FROM current_redazioni AS redazione "
        "JOIN acquisizioni_fonti AS acquisizione "
        "  ON acquisizione.id = redazione.acquisizione_fonte_id "
        "WHERE atto.id = redazione.atto_normativo_id"
    )
    op.execute(
        "WITH current_redazioni AS ("
        "  SELECT DISTINCT ON (atto_normativo_id) "
        "         id, atto_normativo_id, acquisizione_fonte_id "
        "  FROM redazioni "
        "  ORDER BY atto_normativo_id, vigente_dal DESC, id DESC"
        ") "
        "UPDATE partizioni_normative AS partizione "
        "SET documento_id = redazione.atto_normativo_id, "
        "    acquisizione_fonte_id = redazione.acquisizione_fonte_id "
        "FROM current_redazioni AS redazione "
        "WHERE partizione.redazione_id = redazione.id"
    )
    op.execute(
        "DELETE FROM partizioni_normative WHERE documento_id IS NULL"
    )

    op.drop_constraint(
        "fk_partizioni_normative_genitore_stessa_redazione",
        "partizioni_normative",
        type_="foreignkey",
    )
    op.drop_constraint(
        "partizioni_normative_redazione_id_fkey",
        "partizioni_normative",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_partizioni_normative_redazione_identificatore",
        "partizioni_normative",
        type_="unique",
    )
    op.drop_constraint(
        "uq_partizioni_normative_id_redazione",
        "partizioni_normative",
        type_="unique",
    )
    op.drop_column("partizioni_normative", "redazione_id")
    op.alter_column("partizioni_normative", "documento_id", nullable=False)
    op.alter_column("partizioni_normative", "acquisizione_fonte_id", nullable=False)

    op.rename_table("atti_normativi", "documenti")
    op.alter_column("documenti", "urn", existing_type=sa.Text(), nullable=True)
    op.alter_column("documenti", "codice", existing_type=sa.Text(), nullable=False)
    op.create_unique_constraint("uq_documenti_codice", "documenti", ["codice"])
    op.create_check_constraint(
        "ck_documenti_intervallo_vigenza_positivo",
        "documenti",
        "vigente_dal IS NULL OR vigente_al IS NULL OR vigente_al > vigente_dal",
    )

    op.rename_table("partizioni_normative", "partizioni_documentali")
    op.create_foreign_key(
        "fk_partizioni_documentali_documento",
        "partizioni_documentali",
        "documenti",
        ["documento_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_partizioni_documentali_acquisizione",
        "partizioni_documentali",
        "acquisizioni_fonti",
        ["acquisizione_fonte_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_unique_constraint(
        "uq_partizioni_documentali_id_documento",
        "partizioni_documentali",
        ["id", "documento_id"],
    )
    op.create_unique_constraint(
        "uq_partizioni_documentali_documento_identificatore",
        "partizioni_documentali",
        ["documento_id", "identificatore"],
    )
    op.create_foreign_key(
        "fk_partizioni_documentali_genitore_stesso_documento",
        "partizioni_documentali",
        "partizioni_documentali",
        ["partizione_genitore_id", "documento_id"],
        ["id", "documento_id"],
        ondelete="CASCADE",
    )
    op.create_check_constraint(
        "ck_partizioni_documentali_intervallo_vigenza_positivo",
        "partizioni_documentali",
        "vigente_dal IS NULL OR vigente_al IS NULL OR vigente_al > vigente_dal",
    )
    op.drop_table("redazioni")
    op.alter_column(
        "documenti", "tipo_documento", existing_type=sa.Text(), server_default=None
    )


def downgrade() -> None:
    """Restore one legacy redaction per document with a sourceable URN."""
    # The legacy schema cannot represent FAQs or source documents without URNs.
    # Remove those rows before restoring its stricter constraints.
    op.execute(
        "DELETE FROM documenti AS documento "
        "WHERE documento.urn IS NULL OR NOT EXISTS ("
        "  SELECT 1 FROM partizioni_documentali AS partizione "
        "  WHERE partizione.documento_id = documento.id"
        ")"
    )
    op.drop_constraint(
        "ck_partizioni_documentali_intervallo_vigenza_positivo",
        "partizioni_documentali",
        type_="check",
    )
    op.drop_constraint(
        "fk_partizioni_documentali_genitore_stesso_documento",
        "partizioni_documentali",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_partizioni_documentali_documento_identificatore",
        "partizioni_documentali",
        type_="unique",
    )
    op.drop_constraint(
        "uq_partizioni_documentali_id_documento",
        "partizioni_documentali",
        type_="unique",
    )
    op.drop_constraint(
        "fk_partizioni_documentali_acquisizione",
        "partizioni_documentali",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_partizioni_documentali_documento",
        "partizioni_documentali",
        type_="foreignkey",
    )
    op.drop_column("partizioni_documentali", "vigente_al")
    op.drop_column("partizioni_documentali", "vigente_dal")
    op.drop_column("partizioni_documentali", "localizzatore")
    op.drop_column("partizioni_documentali", "rubrica")

    op.rename_table("documenti", "atti_normativi")

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
        "EXCLUDE USING gist (atto_normativo_id WITH =, "
        "daterange(vigente_dal, vigente_al, '[)') WITH &&)"
    )
    op.add_column(
        "partizioni_documentali", sa.Column("redazione_id", sa.BigInteger())
    )
    op.execute(
        "INSERT INTO redazioni (atto_normativo_id, acquisizione_fonte_id, vigente_dal, vigente_al) "
        "SELECT documento.id, MIN(partizione.acquisizione_fonte_id), "
        "       COALESCE(documento.vigente_dal, DATE '0001-01-01'), documento.vigente_al "
        "FROM atti_normativi AS documento "
        "LEFT JOIN partizioni_documentali AS partizione "
        "  ON partizione.documento_id = documento.id "
        "GROUP BY documento.id, documento.vigente_dal, documento.vigente_al "
        "HAVING MIN(partizione.acquisizione_fonte_id) IS NOT NULL"
    )
    op.execute(
        "UPDATE partizioni_documentali AS partizione "
        "SET redazione_id = redazione.id "
        "FROM redazioni AS redazione "
        "WHERE redazione.atto_normativo_id = partizione.documento_id"
    )
    op.alter_column("partizioni_documentali", "redazione_id", nullable=False)
    op.drop_column("partizioni_documentali", "acquisizione_fonte_id")
    op.drop_column("partizioni_documentali", "documento_id")
    op.alter_column("partizioni_documentali", "identificatore", nullable=False)
    op.create_unique_constraint(
        "uq_partizioni_normative_redazione_identificatore",
        "partizioni_documentali",
        ["redazione_id", "identificatore"],
    )
    op.create_unique_constraint(
        "uq_partizioni_normative_id_redazione",
        "partizioni_documentali",
        ["id", "redazione_id"],
    )

    op.alter_column("atti_normativi", "urn", existing_type=sa.Text(), nullable=False)
    op.drop_constraint("uq_documenti_codice", "atti_normativi", type_="unique")
    op.drop_constraint(
        "ck_documenti_intervallo_vigenza_positivo", "atti_normativi", type_="check"
    )
    op.drop_column("atti_normativi", "abilitato_per_agente")
    op.drop_column("atti_normativi", "pubblicato_il")
    op.drop_column("atti_normativi", "snapshot_al")
    op.drop_column("atti_normativi", "vigente_al")
    op.drop_column("atti_normativi", "vigente_dal")
    op.drop_column("atti_normativi", "tipo_documento")
    op.drop_column("atti_normativi", "codice")
    op.rename_table("partizioni_documentali", "partizioni_normative")
    op.create_foreign_key(
        "partizioni_normative_redazione_id_fkey",
        "partizioni_normative",
        "redazioni",
        ["redazione_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fk_partizioni_normative_genitore_stessa_redazione",
        "partizioni_normative",
        "partizioni_normative",
        ["partizione_genitore_id", "redazione_id"],
        ["id", "redazione_id"],
        ondelete="CASCADE",
    )
