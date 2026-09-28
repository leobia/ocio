"""Create the durable HTTP API state."""

from alembic import op

revision = "20260928_01"
down_revision = "20260927_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE conversazioni (
            id uuid PRIMARY KEY,
            creata_il timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE messaggi_conversazione (
            id uuid PRIMARY KEY,
            conversazione_id uuid NOT NULL REFERENCES conversazioni(id),
            ruolo text NOT NULL CHECK (ruolo IN ('user', 'assistant')),
            contenuto text NOT NULL,
            stato text CHECK (stato IN ('ANSWER', 'ABSTAIN')),
            creato_il timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_messaggi_conversazione
            ON messaggi_conversazione (conversazione_id, creato_il, id);
        CREATE TABLE fatti_conversazione (
            id uuid PRIMARY KEY,
            conversazione_id uuid NOT NULL REFERENCES conversazioni(id),
            nome text NOT NULL,
            valore jsonb,
            stato text NOT NULL CHECK (stato IN ('confirmed', 'inferred', 'unknown')),
            messaggio_sorgente_id uuid REFERENCES messaggi_conversazione(id),
            creato_il timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_fatti_conversazione
            ON fatti_conversazione (conversazione_id, nome, creato_il DESC);
        CREATE TABLE citazioni_api (
            id uuid PRIMARY KEY,
            messaggio_id uuid NOT NULL REFERENCES messaggi_conversazione(id),
            dati jsonb NOT NULL,
            creata_il timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE trace_api (
            id uuid PRIMARY KEY,
            messaggio_id uuid NOT NULL REFERENCES messaggi_conversazione(id),
            request_id uuid NOT NULL,
            dati jsonb NOT NULL,
            creata_il timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX ix_trace_api_request_id ON trace_api (request_id);
        CREATE TABLE feedback_messaggi (
            messaggio_id uuid PRIMARY KEY REFERENCES messaggi_conversazione(id),
            rating integer NOT NULL CHECK (rating BETWEEN 1 AND 5),
            reason text,
            details text,
            aggiornato_il timestamptz NOT NULL DEFAULT now()
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE feedback_messaggi;
        DROP TABLE trace_api;
        DROP TABLE citazioni_api;
        DROP TABLE fatti_conversazione;
        DROP TABLE messaggi_conversazione;
        DROP TABLE conversazioni;
        """
    )
