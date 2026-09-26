# OCIO API

Backend Python per OCIO.

## Importazione e normalizzazione del corpus

Le fonti vengono lette soltanto dai file locali verificati tramite SHA-256 nel
registro `ocio_sources.yaml`. Esegui i comandi in quest'ordine, con il database
migrato:

```sh
ocio importa-corpus
ocio normalizza-corpus
```

`normalizza-corpus` aggiorna in modo idempotente i documenti e le loro partizioni
correnti. Non modifica il flag `abilitato_per_agente`. Ogni partizione conserva
l'acquisizione di origine; per i PDF il localizzatore include pagina e riquadro.

AKN segue la gerarchia XML, HTML Gazzetta estrae il contenuto dell'atto e PDF usa
il layout conservando pagina e coordinate. Il parsing non usa rete né OCR.

Il comando stampa conteggi, partizioni non classificate e anomalie con la pagina di
origine quando disponibile.

## Chunk per il retrieval

Genera insiemi immutabili di chunk con una delle due strategie iniziali:

```sh
ocio genera-chunk fixed
ocio genera-chunk structural
```

`fixed` crea finestre da 512 token senza overlap. `structural` conserva i confini
delle partizioni, accorpa partizioni sorelle brevi e divide quelle oltre soglia.
Entrambe conservano le partizioni sorgente e un eventuale parent per la successiva
espansione del contesto. Configurazione o corpus diversi producono un nuovo insieme;
rieseguire la stessa configurazione riusa quello esistente.

## Silver set

Esporta le partizioni non vuote dei documenti abilitati in un JSONL compatto da
fornire, insieme al prompt versionato, a ChatGPT:

```sh
ocio esporta-corpus-valutazione ../../evaluation/corpus-for-silver-set.jsonl
```

Valida struttura, invarianti e riferimenti del dataset contro il corpus canonico:

```sh
ocio valida-silver-set ../../evaluation/silver-set-v1.jsonl
```

Il validatore accumula tutti gli errori e termina con exit status `1` quando il
file non è valido. Gli hard negative richiedono comunque revisione: la loro
non-rispondibilità non può essere dimostrata dal solo controllo strutturale.
