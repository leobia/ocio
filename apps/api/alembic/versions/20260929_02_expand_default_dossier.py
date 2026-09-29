"""Publish a narrative default dossier revision without rewriting existing cases."""

import json
from uuid import UUID, uuid4

from sqlalchemy import text

from alembic import op
from ocio.dossier import migration

revision = "20260929_02"
down_revision = "20260929_01"
branch_labels = None
depends_on = None

TEMPLATE_ID = UUID("00000000-0000-4000-8000-000000000241")
REVISION_ID = UUID("00000000-0000-4000-8000-000000000243")

# Versioned seed content: change it by publishing another revision, not by editing this one.
MARKDOWN = """# Fascicolo sicurezza aziendale

## Azienda e organizzazione

| Dato | Valore |
| --- | --- |
| Azienda | |
| Sedi comprese nell’incarico | |
| Attività svolte | |
| Data di riferimento | |

### Ambito dell’incarico

### Organizzazione della sicurezza

## Attività, processi e mansioni

### Ciclo di lavoro e fasi operative

### Mansioni e organizzazione del lavoro

## Ambienti di lavoro

### Descrizione degli spazi e del layout

### Condizioni osservate durante il sopralluogo

## Macchine, attrezzature e impianti

### Impiego e modalità operative

| Bene | Identificazione e ubicazione | Impiego | Documentazione disponibile |
| --- | --- | --- | --- |

## Sostanze e materiali

### Materiali impiegati e modalità d’uso

| Prodotto o materiale | Fase e impiego | Documentazione disponibile |
| --- | --- | --- |

## Valutazione dei rischi

### Criteri, metodo e informazioni utilizzate

### Analisi per attività, mansione o ambiente

### Valutazioni specifiche e limiti delle informazioni

## Misure e procedure operative

### Misure tecniche e organizzative in atto

### Procedure e modalità di lavoro

### Dispositivi di protezione individuale

## Emergenze

### Organizzazione e gestione delle emergenze

### Documentazione, presidi e prove

## Formazione e addestramento

### Percorsi svolti e documentazione disponibile

### Esigenze di formazione e aggiornamento

## Sorveglianza sanitaria

### Organizzazione e documentazione

## Appalti e interferenze

### Attività affidate e compresenze

### Coordinamento e documentazione

## Programma di miglioramento e riesame

### Interventi proposti e motivazioni

| Intervento | Motivazione e riferimento | Responsabile | Termine previsto |
| --- | --- | --- | --- |

### Aggiornamento del fascicolo

## Documentazione di riferimento

| Materiale | Data o revisione | Provenienza | Sezioni collegate |
| --- | --- | --- | --- |
"""

WRITING_GUIDANCE = (
    "Sviluppa gli appunti in paragrafi tecnici chiari e coerenti, proporzionati alle "
    "informazioni disponibili. Conserva dettagli utili, incertezze e provenienza; "
    "non inventare fatti aziendali, valutazioni o misure attuate. Distingui osservazioni "
    "e raccomandazioni. Adatta il lessico alle attività effettive: il solo settore non "
    "dimostra condizioni o rischi presenti. Usa tabelle per dati confrontabili, senza "
    "sostituire le spiegazioni con elenchi generici. "
)
INSTRUCTIONS = {
    title: WRITING_GUIDANCE + instruction
    for title, instruction in {
        "Azienda e organizzazione": (
            "Riporta identità, sedi e perimetro documentati. Descrivi l’organizzazione "
            "e i ruoli della sicurezza con i riferimenti alle nomine disponibili. "
            "Non identificare automaticamente il fascicolo con un DVR completo."
        ),
        "Attività, processi e mansioni": (
            "Ricostruisci il ciclo in fasi e descrivi operazioni, mansioni, turni, "
            "compresenze e variabilità riferiti negli appunti. Per attività miste "
            "distingui i processi. Non assegnare numero di lavoratori o mansioni "
            "sulla base del codice ATECO o del settore."
        ),
        "Ambienti di lavoro": (
            "Descrivi spazi, collegamenti, postazioni e flussi osservati, richiamando "
            "foto o planimetrie disponibili. Distingui quanto visto nel sopralluogo "
            "dalle condizioni abituali riferite. Non ricavare dimensioni o giudizi "
            "di conformità da immagini che non li documentano."
        ),
        "Macchine, attrezzature e impianti": (
            "Collega ogni bene identificato alle fasi e alle modalità d’impiego. "
            "Riporta manuali, dichiarazioni, manutenzioni e verifiche solo se "
            "documentati. L’assenza di un allegato non dimostra l’assenza di una misura."
        ),
        "Sostanze e materiali": (
            "Descrivi impiego, manipolazione e deposito riportati nel materiale. "
            "Richiama etichette e schede di sicurezza disponibili. Non attribuire "
            "classificazioni, quantità o livelli di esposizione senza una base verificabile."
        ),
        "Valutazione dei rischi": (
            "Esplicita metodo e criteri forniti dal consulente. Organizza l’analisi "
            "per fase, mansione o ambiente collegando situazione osservata, fattori, "
            "possibili effetti, persone coinvolte ed evidenze. Integra spiegazioni "
            "tecniche pertinenti con fonti verificabili; non assegnare punteggi o "
            "livelli di rischio arbitrari e non dichiarare autonomamente la conformità. "
            "Collega gli approfondimenti esistenti senza inventare misurazioni o relazioni."
        ),
        "Misure e procedure operative": (
            "Descrivi come le misure documentate operano nelle attività reali e chi "
            "le attua quando noto. Collega i DPI a mansioni, consegne e addestramento "
            "documentati. Se proponi una misura motivala come raccomandazione, "
            "senza presentarla come già adottata; rimanda gli interventi al programma."
        ),
        "Emergenze": (
            "Descrivi organizzazione, incarichi e modalità di gestione conosciuti. "
            "Collega piani, planimetrie, presidi, controlli e prove con date documentate. "
            "Non compilare automaticamente una procedura standard come se fosse quella aziendale."
        ),
        "Formazione e addestramento": (
            "Collega percorsi e attestati alle mansioni o ai gruppi documentati. "
            "Distingui attività svolte, documenti non acquisiti ed esigenze proposte. "
            "Motiva eventuali requisiti normativi con fonti pertinenti e verificabili; "
            "non inventare attestazioni o scadenze."
        ),
        "Sorveglianza sanitaria": (
            "Descrivi l’organizzazione documentata e i riferimenti a nomina, "
            "protocollo e gestione delle scadenze quando disponibili. Non inserire "
            "diagnosi, referti o altri dati sanitari individuali, né formulare "
            "giudizi di idoneità o dedurre il protocollo dal solo settore."
        ),
        "Appalti e interferenze": (
            "Descrivi attività affidate, luoghi, tempi e compresenze noti. Collega "
            "le modalità di coordinamento e i documenti acquisiti, compreso il DUVRI "
            "quando disponibile e pertinente. Non dedurre l’assenza di interferenze "
            "dalla sola mancanza di annotazioni."
        ),
        "Programma di miglioramento e riesame": (
            "Raccogli gli interventi motivati dall’analisi, distinguendo proposte "
            "e decisioni del consulente. Riporta responsabili, priorità e termini "
            "solo se definiti. Descrivi le ragioni documentate degli aggiornamenti. "
            "Questa sezione non è una checklist preparatoria del sopralluogo."
        ),
        "Documentazione di riferimento": (
            "Elenca soltanto materiale realmente acquisito e fonti effettivamente "
            "consultate, mantenendo nome, data o revisione, provenienza e collegamenti "
            "alle sezioni. Distingui evidenze aziendali e fonti normative ufficiali. "
            "Segnala nel testo pertinente il materiale mancante senza creare allegati fittizi."
        ),
    }.items()
}


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(text(
        "SELECT id FROM modelli_fascicolo WHERE id = :id FOR UPDATE"
    ), {"id": TEMPLATE_ID}).scalar_one()
    number = connection.execute(text(
        "SELECT COALESCE(max(numero), 0) + 1 FROM revisioni_modello_fascicolo "
        "WHERE modello_id = :id"
    ), {"id": TEMPLATE_ID}).scalar_one()
    connection.execute(text(
        "INSERT INTO revisioni_modello_fascicolo "
        "(id, modello_id, numero, schema_markdown, indicazioni) "
        "VALUES (:id, :template_id, :number, :markdown, CAST(:instructions AS jsonb))"
    ), {
        "id": REVISION_ID, "template_id": TEMPLATE_ID, "number": number,
        "markdown": MARKDOWN, "instructions": json.dumps(INSTRUCTIONS),
    })
    engagements = connection.execute(text(
        "SELECT i.id, i.revisione_modello_id, i.fascicolo_markdown "
        "FROM incarichi i JOIN revisioni_modello_fascicolo r ON r.id = i.revisione_modello_id "
        "WHERE r.modello_id = :id FOR UPDATE OF i"
    ), {"id": TEMPLATE_ID}).mappings().all()
    for item in engagements:
        proposed, diff = migration(item["fascicolo_markdown"], MARKDOWN)
        connection.execute(text(
            "UPDATE migrazioni_fascicolo SET stato = 'superata' "
            "WHERE incarico_id = :id AND stato = 'proposta'"
        ), {"id": item["id"]})
        connection.execute(text(
            "INSERT INTO migrazioni_fascicolo "
            "(id, incarico_id, revisione_origine_id, revisione_destinazione_id, "
            "fascicolo_origine, fascicolo_proposto, diff) "
            "VALUES (:id, :engagement_id, :source_id, :target_id, :current, :proposed, :diff)"
        ), {
            "id": uuid4(), "engagement_id": item["id"],
            "source_id": item["revisione_modello_id"], "target_id": REVISION_ID,
            "current": item["fascicolo_markdown"], "proposed": proposed, "diff": diff,
        })


def downgrade() -> None:
    # Published template revisions can be adopted and cited in dossier history.
    raise RuntimeError(
        "La revisione pubblicata va conservata: per ripristinare il modello precedente, "
        "pubblicarlo come nuova revisione senza cancellare la cronologia."
    )
