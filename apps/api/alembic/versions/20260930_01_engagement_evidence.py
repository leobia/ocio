"""Persist engagement messages, original files and traceable observations."""

from alembic import op

revision = "20260930_01"
down_revision = "20260929_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE messaggi_incarico (
            id uuid PRIMARY KEY,
            incarico_id uuid NOT NULL REFERENCES incarichi(id) ON DELETE CASCADE,
            contenuto text NOT NULL,
            creato_il timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX messaggi_incarico_ordine ON messaggi_incarico (incarico_id, creato_il, id);
        CREATE TABLE allegati_incarico (
            id uuid PRIMARY KEY,
            messaggio_id uuid NOT NULL REFERENCES messaggi_incarico(id) ON DELETE CASCADE,
            nome text NOT NULL,
            tipo text NOT NULL,
            istruzione text NOT NULL,
            contenuto bytea NOT NULL,
            stato text NOT NULL DEFAULT 'in_attesa'
                CHECK (stato IN ('in_attesa', 'analizzato', 'errore')),
            errore text,
            creato_il timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE osservazioni_incarico (
            id uuid PRIMARY KEY,
            messaggio_id uuid NOT NULL REFERENCES messaggi_incarico(id) ON DELETE CASCADE,
            allegato_id uuid REFERENCES allegati_incarico(id) ON DELETE CASCADE,
            sezione text,
            informazione text NOT NULL,
            esito text NOT NULL CHECK (esito IN ('osservato', 'non_leggibile', 'non_determinabile')),
            testo text NOT NULL,
            posizione text,
            istruzione text NOT NULL,
            metodo text NOT NULL,
            versione text NOT NULL,
            creata_il timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX osservazioni_incarico_messaggio ON osservazioni_incarico (messaggio_id);
        """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE osservazioni_incarico;
        DROP TABLE allegati_incarico;
        DROP TABLE messaggi_incarico;
        """)
