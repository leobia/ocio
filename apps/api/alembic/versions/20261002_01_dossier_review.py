"""Protect reviewed text and preserve immutable approvals and review decisions."""
from sqlalchemy import text

from alembic import op
from ocio.dossier import section_titles

revision = "20261002_01"
down_revision = "20260930_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE incarichi ADD COLUMN sezioni_protette jsonb NOT NULL DEFAULT '[]';
        CREATE TABLE proposte_sezione (
            id uuid PRIMARY KEY,
            incarico_id uuid NOT NULL REFERENCES incarichi(id),
            run_id uuid NOT NULL REFERENCES run_fascicolo(id),
            sezione text NOT NULL,
            precedente text NOT NULL,
            proposto text NOT NULL,
            riferimenti jsonb NOT NULL,
            stato text NOT NULL CHECK (stato IN ('proposta', 'bozza', 'accettata', 'corretta', 'rifiutata', 'superata')),
            creata_il timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE decisioni_revisione (
            id uuid PRIMARY KEY,
            incarico_id uuid NOT NULL REFERENCES incarichi(id),
            proposta_id uuid REFERENCES proposte_sezione(id),
            run_id uuid REFERENCES run_fascicolo(id),
            revisione_id uuid NOT NULL REFERENCES revisioni_fascicolo(id),
            azione text NOT NULL,
            autore text NOT NULL,
            motivo text NOT NULL,
            creata_il timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE approvazioni_fascicolo (
            id uuid PRIMARY KEY,
            incarico_id uuid NOT NULL REFERENCES incarichi(id),
            revisione_id uuid NOT NULL REFERENCES revisioni_fascicolo(id),
            autore text NOT NULL,
            markdown text NOT NULL,
            contesto jsonb NOT NULL,
            creata_il timestamptz NOT NULL DEFAULT now()
        );
    """)
    import json
    connection = op.get_bind()
    for row in connection.execute(text(
        "SELECT id, fascicolo_markdown FROM incarichi i WHERE EXISTS "
        "(SELECT 1 FROM revisioni_fascicolo r WHERE r.incarico_id = i.id AND motivo = 'modifica_manuale')"
    )):
        connection.execute(text("UPDATE incarichi SET sezioni_protette = CAST(:sections AS jsonb) WHERE id = :id"),
                           {"id": row[0], "sections": json.dumps(section_titles(row[1]))})


def downgrade() -> None:
    op.execute("""
        DROP TABLE approvazioni_fascicolo;
        DROP TABLE decisioni_revisione;
        DROP TABLE proposte_sezione;
        ALTER TABLE incarichi DROP COLUMN sezioni_protette;
    """)
