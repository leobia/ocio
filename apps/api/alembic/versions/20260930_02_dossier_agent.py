"""Persist dossier agent runs, decisions and idempotent effects."""

from alembic import op
from sqlalchemy import text

from ocio.dossier import section_titles

revision = "20260930_02"
down_revision = "20260930_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE incarichi ADD COLUMN stato text NOT NULL DEFAULT 'in_corso'
            CHECK (stato IN ('in_corso', 'in_attesa', 'completato', 'fallito'));
        ALTER TABLE incarichi ADD COLUMN versione_stato integer NOT NULL DEFAULT 0;
        ALTER TABLE revisioni_modello_fascicolo ADD COLUMN pertinenza jsonb NOT NULL DEFAULT '{}'::jsonb;
        ALTER TABLE revisioni_fascicolo DROP CONSTRAINT revisioni_fascicolo_motivo_check;
        ALTER TABLE revisioni_fascicolo ADD CONSTRAINT revisioni_fascicolo_motivo_check
            CHECK (motivo IN ('creazione', 'modifica_manuale', 'migrazione', 'agente'));
        ALTER TABLE messaggi_incarico ADD COLUMN ruolo text NOT NULL DEFAULT 'user'
            CHECK (ruolo IN ('user', 'assistant'));
        CREATE TABLE run_fascicolo (
            id uuid PRIMARY KEY,
            incarico_id uuid NOT NULL REFERENCES incarichi(id) ON DELETE CASCADE,
            stato text NOT NULL CHECK (stato IN ('in_corso', 'in_attesa', 'completato', 'fallito')),
            modello text NOT NULL,
            versione_prompt text NOT NULL,
            revisione_modello_id uuid NOT NULL REFERENCES revisioni_modello_fascicolo(id),
            piano text NOT NULL DEFAULT '',
            domande jsonb NOT NULL DEFAULT '[]'::jsonb,
            motivo text NOT NULL DEFAULT '',
            creato_il timestamptz NOT NULL DEFAULT now(),
            concluso_il timestamptz
        );
        CREATE UNIQUE INDEX run_fascicolo_attivo ON run_fascicolo (incarico_id)
            WHERE stato = 'in_corso';
        CREATE TABLE pertinenza_sezioni (
            incarico_id uuid NOT NULL REFERENCES incarichi(id) ON DELETE CASCADE,
            sezione text NOT NULL,
            stato text NOT NULL CHECK (stato IN ('da_valutare', 'pertinente', 'non_pertinente', 'da_chiarire')),
            motivo text NOT NULL,
            riferimenti jsonb NOT NULL DEFAULT '[]'::jsonb,
            origine text NOT NULL CHECK (origine IN ('sistema', 'agente', 'operatore')),
            aggiornata_il timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (incarico_id, sezione)
        );
        CREATE TABLE revisioni_pertinenza (
            id uuid PRIMARY KEY,
            incarico_id uuid NOT NULL REFERENCES incarichi(id) ON DELETE CASCADE,
            run_id uuid REFERENCES run_fascicolo(id),
            sezione text NOT NULL,
            stato text NOT NULL,
            motivo text NOT NULL,
            riferimenti jsonb NOT NULL,
            origine text NOT NULL,
            creata_il timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE fatti_proposti_incarico (
            id uuid PRIMARY KEY,
            incarico_id uuid NOT NULL REFERENCES incarichi(id) ON DELETE CASCADE,
            run_id uuid NOT NULL REFERENCES run_fascicolo(id),
            sezione text NOT NULL,
            testo text NOT NULL,
            riferimenti jsonb NOT NULL,
            creato_il timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE eventi_run_fascicolo (
            id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            run_id uuid NOT NULL REFERENCES run_fascicolo(id) ON DELETE CASCADE,
            tipo text NOT NULL,
            dati jsonb NOT NULL,
            creato_il timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE operazioni_fascicolo (
            id uuid PRIMARY KEY,
            incarico_id uuid NOT NULL REFERENCES incarichi(id) ON DELETE CASCADE,
            run_id uuid NOT NULL REFERENCES run_fascicolo(id),
            tipo text NOT NULL,
            payload jsonb NOT NULL,
            risultato jsonb NOT NULL,
            creata_il timestamptz NOT NULL DEFAULT now()
        );
    """)
    connection = op.get_bind()
    for engagement_id, markdown in connection.execute(text(
        "SELECT id, fascicolo_markdown FROM incarichi"
    )):
        for title in dict.fromkeys(section_titles(markdown)):
            connection.execute(text(
                "INSERT INTO pertinenza_sezioni (incarico_id, sezione, stato, motivo, origine) "
                "VALUES (:id, :section, 'da_valutare', 'Sezione del fascicolo esistente.', 'sistema')"
            ), {"id": engagement_id, "section": title})


def downgrade() -> None:
    op.execute("""
        DROP TABLE operazioni_fascicolo;
        DROP TABLE eventi_run_fascicolo;
        DROP TABLE fatti_proposti_incarico;
        DROP TABLE revisioni_pertinenza;
        DROP TABLE pertinenza_sezioni;
        DROP TABLE run_fascicolo;
        ALTER TABLE messaggi_incarico DROP COLUMN ruolo;
        ALTER TABLE revisioni_fascicolo DROP CONSTRAINT revisioni_fascicolo_motivo_check;
        ALTER TABLE revisioni_fascicolo ADD CONSTRAINT revisioni_fascicolo_motivo_check
            CHECK (motivo IN ('creazione', 'modifica_manuale', 'migrazione'));
        ALTER TABLE revisioni_modello_fascicolo DROP COLUMN pertinenza;
        ALTER TABLE incarichi DROP COLUMN stato;
        ALTER TABLE incarichi DROP COLUMN versione_stato;
    """)
