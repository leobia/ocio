"""Create versioned dossier templates and engagements."""

from alembic import op

revision = "20260929_01"
down_revision = "20260928_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        r"""
        CREATE TABLE modelli_fascicolo (
            id uuid PRIMARY KEY,
            nome text NOT NULL,
            predefinito boolean NOT NULL DEFAULT false,
            creato_il timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE revisioni_modello_fascicolo (
            id uuid PRIMARY KEY,
            modello_id uuid NOT NULL REFERENCES modelli_fascicolo(id),
            numero integer NOT NULL CHECK (numero > 0),
            schema_markdown text NOT NULL,
            indicazioni jsonb NOT NULL DEFAULT '{}'::jsonb,
            creata_il timestamptz NOT NULL DEFAULT now(),
            UNIQUE (modello_id, numero)
        );
        CREATE TABLE incarichi (
            id uuid PRIMARY KEY,
            azienda text NOT NULL,
            sede text NOT NULL,
            data_riferimento date NOT NULL,
            revisione_modello_id uuid NOT NULL REFERENCES revisioni_modello_fascicolo(id),
            fascicolo_markdown text NOT NULL,
            creato_il timestamptz NOT NULL DEFAULT now(),
            aggiornato_il timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE revisioni_fascicolo (
            id uuid PRIMARY KEY,
            incarico_id uuid NOT NULL REFERENCES incarichi(id),
            numero integer NOT NULL CHECK (numero > 0),
            revisione_modello_id uuid NOT NULL REFERENCES revisioni_modello_fascicolo(id),
            fascicolo_markdown text NOT NULL,
            motivo text NOT NULL CHECK (motivo IN ('creazione', 'modifica_manuale', 'migrazione')),
            creata_il timestamptz NOT NULL DEFAULT now(),
            UNIQUE (incarico_id, numero)
        );
        CREATE TABLE migrazioni_fascicolo (
            id uuid PRIMARY KEY,
            incarico_id uuid NOT NULL REFERENCES incarichi(id),
            revisione_origine_id uuid NOT NULL REFERENCES revisioni_modello_fascicolo(id),
            revisione_destinazione_id uuid NOT NULL REFERENCES revisioni_modello_fascicolo(id),
            fascicolo_origine text NOT NULL,
            fascicolo_proposto text NOT NULL,
            diff text NOT NULL,
            stato text NOT NULL DEFAULT 'proposta' CHECK (stato IN ('proposta', 'applicata', 'superata')),
            creata_il timestamptz NOT NULL DEFAULT now(),
            applicata_il timestamptz,
            UNIQUE (incarico_id, revisione_destinazione_id)
        );

        INSERT INTO modelli_fascicolo (id, nome, predefinito)
        VALUES ('00000000-0000-4000-8000-000000000241', 'Fascicolo sicurezza aziendale', true);

        INSERT INTO revisioni_modello_fascicolo
            (id, modello_id, numero, schema_markdown, indicazioni)
        VALUES (
            '00000000-0000-4000-8000-000000000242',
            '00000000-0000-4000-8000-000000000241',
            1,
            $schema$# Fascicolo sicurezza aziendale

## 1. Anagrafica e organizzazione

- Dati azienda e sedi
- Organigramma e nomine della sicurezza
- Mansioni e gruppi omogenei

## 2. Valutazione dei rischi

- DVR generale e valutazioni specifiche applicabili
- Piano di miglioramento

## 3. Procedure operative

- Procedure e istruzioni di sicurezza
- Gestione DPI, manutenzioni e lavorazioni particolari

## 4. Emergenze

- Piano, planimetrie, nomine e prove di evacuazione
- Controlli dei presidi antincendio

## 5. Formazione

- Matrice e scadenziario
- Attestati e addestramenti

## 6. Sorveglianza sanitaria

- Nomina, protocollo, giudizi e scadenziario visite

## 7. DPI

- Elenco per mansione, consegne, schede e addestramenti

## 8. Macchine, attrezzature e impianti

- Elenco, manuali, dichiarazioni, manutenzioni e verifiche

## 9. Appalti e fornitori

- Idoneità, informativa rischi, DUVRI e coordinamento

## 10. Controlli e gestione periodica

- Sopralluoghi, audit, riunioni, eventi e scadenze
$schema$,
            $instructions${
              "1. Anagrafica e organizzazione": "Indicare dati della sede, ruoli nominati, mansioni e gruppi omogenei.",
              "2. Valutazione dei rischi": "Elencare solo valutazioni applicabili e collegare il piano di miglioramento.",
              "3. Procedure operative": "Collegare le procedure vigenti e indicarne responsabile e revisione.",
              "4. Emergenze": "Registrare piani, addetti, prove e controlli con relative date.",
              "5. Formazione": "Riportare requisiti, attestati e scadenze verificabili.",
              "6. Sorveglianza sanitaria": "Non inserire dati sanitari; registrare soltanto documenti e scadenze.",
              "7. DPI": "Collegare DPI, mansioni, consegne e addestramenti.",
              "8. Macchine, attrezzature e impianti": "Associare documenti, manutenzioni e verifiche a ogni bene.",
              "9. Appalti e fornitori": "Conservare verifiche, informative e verbali per ciascun affidamento.",
              "10. Controlli e gestione periodica": "Registrare esiti, azioni, responsabili e scadenze."
            }$instructions$::jsonb
        );
        """
    )


def downgrade() -> None:
    op.execute(
        """
        DROP TABLE migrazioni_fascicolo;
        DROP TABLE revisioni_fascicolo;
        DROP TABLE incarichi;
        DROP TABLE revisioni_modello_fascicolo;
        DROP TABLE modelli_fascicolo;
        """
    )
