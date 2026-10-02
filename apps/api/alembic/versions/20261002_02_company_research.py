"""Keep public company proposals separate from verified engagement information."""
from alembic import op

revision = '20261002_02'
down_revision = '20261002_01'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE ricerche_azienda (
            id uuid PRIMARY KEY,
            incarico_id uuid NOT NULL REFERENCES incarichi(id),
            identita jsonb NOT NULL,
            stato text NOT NULL CHECK (stato IN ('completata', 'ambigua', 'errore')),
            messaggio text NOT NULL,
            creata_il timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE proposte_anagrafica (
            id uuid PRIMARY KEY,
            ricerca_id uuid NOT NULL REFERENCES ricerche_azienda(id),
            campo text NOT NULL CHECK (campo IN ('sito_ufficiale', 'sede_pubblicata', 'attivita_pubblicata', 'partita_iva')),
            valore text NOT NULL,
            url text NOT NULL,
            tipo_fonte text NOT NULL CHECK (tipo_fonte IN ('istituzionale', 'aziendale', 'altro')),
            consultata_il timestamptz NOT NULL DEFAULT now(),
            stato text NOT NULL DEFAULT 'da_verificare' CHECK (stato IN ('da_verificare', 'confermata', 'corretta', 'rifiutata')),
            valore_confermato text,
            autore text,
            motivo text,
            decisa_il timestamptz
        );
    """)


def downgrade() -> None:
    op.execute('DROP TABLE proposte_anagrafica; DROP TABLE ricerche_azienda;')
