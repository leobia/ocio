"""Separate section descriptions from the application writing instructions."""

import json
from uuid import UUID, uuid4

from sqlalchemy import text

from alembic import op
from ocio.dossier import migration

revision = "20260929_03"
down_revision = "20260929_02"
branch_labels = None
depends_on = None

TEMPLATE_ID = UUID("00000000-0000-4000-8000-000000000241")
PREVIOUS_SEED = UUID("00000000-0000-4000-8000-000000000243")
REVISION_ID = UUID("00000000-0000-4000-8000-000000000244")

# Exact application-owned prefix shipped in revision 20260929_02.
LEGACY_PREFIX = (
    "Sviluppa gli appunti in paragrafi tecnici chiari e coerenti, proporzionati alle "
    "informazioni disponibili. Conserva dettagli utili, incertezze e provenienza; "
    "non inventare fatti aziendali, valutazioni o misure attuate. Distingui osservazioni "
    "e raccomandazioni. Adatta il lessico alle attività effettive: il solo settore non "
    "dimostra condizioni o rischi presenti. Usa tabelle per dati confrontabili, senza "
    "sostituire le spiegazioni con elenchi generici. "
)
DESCRIPTIONS = {
    "Azienda e organizzazione": (
        "Identità dell’azienda, sedi e ambito dell’incarico. Organizzazione aziendale, "
        "ruoli della sicurezza e riferimenti alle nomine."
    ),
    "Attività, processi e mansioni": (
        "Descrizione del ciclo di lavoro e delle singole fasi: operazioni svolte, "
        "mansioni, turni, compresenze e variazioni delle attività. Nei contesti misti, "
        "distinzione tra i diversi processi."
    ),
    "Ambienti di lavoro": (
        "Descrizione dei locali, delle postazioni, dei collegamenti e dei flussi di "
        "persone e materiali. Condizioni osservate durante il sopralluogo e riferimenti "
        "a fotografie e planimetrie."
    ),
    "Macchine, attrezzature e impianti": (
        "Beni utilizzati nelle diverse fasi, loro ubicazione e modalità d’impiego. "
        "Inventario e riferimenti a manuali, dichiarazioni, manutenzioni e verifiche."
    ),
    "Sostanze e materiali": (
        "Prodotti e materiali utilizzati, fasi di impiego, modalità di manipolazione "
        "e deposito. Riferimenti a etichette e schede di sicurezza."
    ),
    "Valutazione dei rischi": (
        "Metodo e criteri adottati dal consulente. Analisi per fase, mansione o "
        "ambiente che colleghi situazioni osservate, fattori di rischio, possibili "
        "effetti e persone coinvolte. Motivazioni della valutazione, limiti delle "
        "informazioni e rimandi agli approfondimenti specifici."
    ),
    "Misure e procedure operative": (
        "Misure tecniche e organizzative in atto, loro applicazione nel lavoro e "
        "ruoli incaricati. Procedure operative e DPI associati alle mansioni. "
        "Collegamenti agli interventi proposti nel programma di miglioramento."
    ),
    "Emergenze": (
        "Organizzazione delle emergenze, incarichi e modalità di gestione. "
        "Piani, planimetrie, presidi, controlli e prove svolte."
    ),
    "Formazione e addestramento": (
        "Percorsi svolti e attestati collegati a mansioni o gruppi di lavoratori. "
        "Esigenze di formazione, addestramento e aggiornamento, con riferimenti "
        "alla documentazione e alle scadenze disponibili."
    ),
    "Sorveglianza sanitaria": (
        "Organizzazione della sorveglianza sanitaria e riferimenti alla nomina "
        "del medico competente, al protocollo e alla gestione delle scadenze."
    ),
    "Appalti e interferenze": (
        "Attività affidate a imprese esterne, luoghi, tempi e compresenze. "
        "Modalità di coordinamento e documentazione pertinente, compreso "
        "il DUVRI quando disponibile."
    ),
    "Programma di miglioramento e riesame": (
        "Interventi e relative motivazioni, collegati all’analisi del fascicolo. "
        "Decisioni del consulente, responsabili, priorità e termini definiti. "
        "Criteri e ragioni degli aggiornamenti successivi."
    ),
    "Documentazione di riferimento": (
        "Indice del materiale acquisito e delle fonti consultate: nome, data o "
        "revisione, provenienza e sezioni collegate. Distinzione tra documentazione "
        "aziendale e fonti normative."
    ),
}


def upgrade() -> None:
    connection = op.get_bind()
    connection.execute(text(
        "SELECT id FROM modelli_fascicolo WHERE id = :id FOR UPDATE"
    ), {"id": TEMPLATE_ID}).scalar_one()
    latest = connection.execute(text(
        "SELECT numero, schema_markdown, indicazioni FROM revisioni_modello_fascicolo "
        "WHERE modello_id = :id ORDER BY numero DESC LIMIT 1"
    ), {"id": TEMPLATE_ID}).mappings().one()
    shipped = connection.execute(text(
        "SELECT indicazioni FROM revisioni_modello_fascicolo WHERE id = :id"
    ), {"id": PREVIOUS_SEED}).scalar_one()
    descriptions = {
        title: DESCRIPTIONS[title] if title in DESCRIPTIONS and value == shipped.get(title)
        else value.removeprefix(LEGACY_PREFIX)
        for title, value in latest["indicazioni"].items()
    }
    connection.execute(text(
        "INSERT INTO revisioni_modello_fascicolo "
        "(id, modello_id, numero, schema_markdown, indicazioni) "
        "VALUES (:id, :template_id, :number, :markdown, CAST(:descriptions AS jsonb))"
    ), {
        "id": REVISION_ID, "template_id": TEMPLATE_ID, "number": latest["numero"] + 1,
        "markdown": latest["schema_markdown"], "descriptions": json.dumps(descriptions),
    })
    cases = connection.execute(text(
        "SELECT i.id, i.revisione_modello_id, i.fascicolo_markdown, r.schema_markdown "
        "FROM incarichi i JOIN revisioni_modello_fascicolo r ON r.id = i.revisione_modello_id "
        "WHERE r.modello_id = :id FOR UPDATE OF i"
    ), {"id": TEMPLATE_ID}).mappings().all()
    for case in cases:
        if case["schema_markdown"] == latest["schema_markdown"]:
            proposed, diff = case["fascicolo_markdown"], ""
        else:
            proposed, diff = migration(case["fascicolo_markdown"], latest["schema_markdown"])
        connection.execute(text(
            "UPDATE migrazioni_fascicolo SET stato = 'superata' "
            "WHERE incarico_id = :id AND stato = 'proposta'"
        ), {"id": case["id"]})
        connection.execute(text(
            "INSERT INTO migrazioni_fascicolo "
            "(id, incarico_id, revisione_origine_id, revisione_destinazione_id, "
            "fascicolo_origine, fascicolo_proposto, diff) "
            "VALUES (:id, :case_id, :source_id, :target_id, :current, :proposed, :diff)"
        ), {
            "id": uuid4(), "case_id": case["id"], "source_id": case["revisione_modello_id"],
            "target_id": REVISION_ID, "current": case["fascicolo_markdown"],
            "proposed": proposed, "diff": diff,
        })


def downgrade() -> None:
    raise RuntimeError("Conservare le revisioni pubblicate; ripristinare tramite una nuova revisione.")
