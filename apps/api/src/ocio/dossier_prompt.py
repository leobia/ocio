"""Application-owned writing instructions, separate from editable dossier templates.

The dossier agent (#27) consumes this context; the normative chat has its own prompt.
"""

import json
from collections.abc import Mapping
from dataclasses import dataclass

from ocio.dossier import validate_instructions

PROMPT_VERSION = "dossier-writing-v1"
WRITING_INSTRUCTIONS = """Aiuta l’RSPP a redigere il fascicolo a partire dal materiale dell’incarico.
Segui lo schema del modello e le descrizioni delle sezioni forniti nel contesto.
Le descrizioni specificano i contenuti attesi; queste regole generali valgono per tutto il fascicolo.

Sviluppa gli appunti in paragrafi professionali, concreti e coerenti. Organizza le
informazioni, collega le osservazioni e spiega gli aspetti tecnici pertinenti con
il supporto necessario. Conserva i dettagli utili; evita formule generiche,
ripetizioni e ampliamenti che aggiungono solo lunghezza. Usa sottotitoli, elenchi
e tabelle quando rendono il contenuto più leggibile.

Ancora ogni affermazione sul caso al materiale disponibile. Conserva incertezze
e contraddizioni; non inventare condizioni aziendali, documenti, misurazioni,
valutazioni, punteggi, scadenze o misure già attuate. Distingui ciò che è stato
osservato, ciò che è stato riferito e le raccomandazioni. L’assenza di un allegato
non dimostra l’assenza di una misura. Collega le affermazioni alle evidenze e le
indicazioni normative alle fonti ufficiali effettivamente consultate.

Usa settore e attività effettive per scegliere il lessico e gli approfondimenti.
Il solo settore o codice ATECO non dimostra macchinari, mansioni, esposizioni o
rischi presenti. Considera separatamente le attività miste quando documentate.
Non dichiarare autonomamente la conformità e non formulare giudizi di idoneità
sanitaria. Non riportare diagnosi, referti o dati sanitari individuali.

Rispetta il testo già scritto o revisionato dal consulente. Lascia esplicite nel
contenuto le informazioni mancanti rilevanti; la revisione avviene nel fascicolo,
senza chiedere conferme per ogni dato. Il fascicolo può raccogliere più elaborati
e allegati: non identificarlo automaticamente con un DVR completo.
"""


@dataclass(frozen=True)
class DossierWritingContext:
    version: str
    instructions: str
    template: str


def writing_context(schema: str, section_descriptions: Mapping[str, str]) -> DossierWritingContext:
    """Build context from the *adopted* template revision supplied by the caller.

    Keep editable template content out of the application instructions. The agent
    supplies case material separately; this function does not call a provider.
    """
    descriptions = dict(section_descriptions)
    validate_instructions(schema, descriptions)
    return DossierWritingContext(
        version=PROMPT_VERSION,
        instructions=WRITING_INSTRUCTIONS,
        template=json.dumps(
            {"schema": schema, "section_descriptions": descriptions}, ensure_ascii=False,
        ),
    )
