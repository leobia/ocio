"""Govern review feedback without modifying prompts or the authoritative corpus."""
from alembic import op

revision = '20261002_03'
down_revision = '20261002_02'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE candidati_qualita (
            id uuid PRIMARY KEY,
            incarico_id uuid NOT NULL REFERENCES incarichi(id),
            decisione_id uuid UNIQUE REFERENCES decisioni_revisione(id),
            run_id uuid REFERENCES run_fascicolo(id),
            revisione_id uuid NOT NULL REFERENCES revisioni_fascicolo(id),
            sezione text,
            categoria text NOT NULL CHECK (categoria IN ('revisione', 'fatto_errato', 'omissione', 'domanda_superflua', 'citazione_inadeguata')),
            dettaglio text NOT NULL,
            autore text NOT NULL,
            causa text CHECK (causa IN ('dato_del_caso', 'estrazione', 'ricerca_normativa', 'scelta_tool', 'istruzione', 'output_finale')),
            stato text NOT NULL DEFAULT 'aperto' CHECK (stato IN ('aperto', 'scartato', 'solo_incarico', 'regressione')),
            caso_anonimo jsonb,
            creata_il timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE decisioni_qualita (
            id uuid PRIMARY KEY,
            candidato_id uuid NOT NULL REFERENCES candidati_qualita(id),
            autore text NOT NULL,
            motivo text NOT NULL,
            ambito text NOT NULL,
            causa text NOT NULL,
            versioni jsonb NOT NULL,
            caso_anonimo jsonb,
            creata_il timestamptz NOT NULL DEFAULT now()
        );
        CREATE FUNCTION raccogli_feedback_revisione() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            INSERT INTO candidati_qualita (id, incarico_id, decisione_id, run_id, revisione_id, sezione, categoria, dettaglio, autore)
            VALUES (NEW.id, NEW.incarico_id, NEW.id, NEW.run_id, NEW.revisione_id,
                    (SELECT sezione FROM proposte_sezione WHERE id = NEW.proposta_id),
                    'revisione', NEW.azione, NEW.autore);
            RETURN NEW;
        END;
        $$;
        CREATE TRIGGER feedback_revisione AFTER INSERT ON decisioni_revisione
            FOR EACH ROW EXECUTE FUNCTION raccogli_feedback_revisione();
        INSERT INTO candidati_qualita (id, incarico_id, decisione_id, run_id, revisione_id, sezione, categoria, dettaglio, autore)
            SELECT d.id, d.incarico_id, d.id, d.run_id, d.revisione_id, p.sezione, 'revisione', d.azione, d.autore
            FROM decisioni_revisione d LEFT JOIN proposte_sezione p ON p.id = d.proposta_id;
    """)


def downgrade() -> None:
    op.execute('DROP TRIGGER feedback_revisione ON decisioni_revisione; DROP FUNCTION raccogli_feedback_revisione(); DROP TABLE decisioni_qualita; DROP TABLE candidati_qualita;')
