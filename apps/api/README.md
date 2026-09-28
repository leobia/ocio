# OCIO API

Backend Python per OCIO.

## API HTTP

Applica le migrazioni e avvia l'app FastAPI:

```sh
alembic upgrade head
uvicorn ocio.api:create_app --factory
```

Le route versionate sotto `/v1` gestiscono conversazioni, messaggi sincroni,
`case_state`, citazioni e feedback. `/health/live` controlla il processo e
`/health/ready` anche PostgreSQL. Ogni risposta include `X-Request-ID`: il client
può inviare un UUID nello stesso header oppure lasciarlo generare al server. Le
trace persistono lo stesso ID senza includere credenziali o configurazione del
provider. I contratti di successo, l'unione `ANSWER`/`ABSTAIN` e l'envelope di
errore stabile sono consultabili in `/docs` e `/openapi.json`.

Il processo HTTP riceve il backend di chat tramite `create_app`; in assenza di
un backend configurato, le route dati restano disponibili e l'invio di un
messaggio risponde `503 chat_unavailable`.

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

## Retrieval dense

Esporta `OPENAI_API_KEY`, poi genera la cache portabile per un insieme di chunk e
importala nel database:

```sh
export OPENAI_API_KEY="..."
ocio genera-embedding <fingerprint> --model small
ocio genera-embedding <fingerprint> --model large
ocio importa-embedding ../../artifacts/embeddings/text-embedding-3-small-1536.jsonl.gz
ocio importa-embedding ../../artifacts/embeddings/text-embedding-3-large-3072.jsonl.gz
```

`small` usa le 1536 dimensioni native di `text-embedding-3-small`; `large` usa
le 3072 dimensioni native di `text-embedding-3-large`. Le cache non contengono
testo e vengono riutilizzate per contenuti con lo stesso SHA-256 anche fra
insiemi di chunk diversi. L'importazione è offline e può ricostruire la tabella
degli embedding senza chiamare OpenAI.

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
Ogni evidenza rispondibile include `evidence_text`: validazione e metriche
richiedono che l'estratto appartenga alla partizione e sia presente nel chunk.

## Benchmark retrieval

Una configurazione può selezionare `postgres_fts`, `bm25`, `dense_small` o
`dense_large`. Più retriever possono essere composti con fusion RRF o pesata:

```yaml
configurations:
  - name: hybrid
    retrievers: [bm25, dense_large]
    fusion:
      algorithm: rrf
      rank_constant: 60
```

La trace conserva le graduatorie dei singoli retriever e quella fusa. Il report
include anche il costo in caratteri dell'espansione ai parent; impostare
`parent_expansion: true` la applica prima della valutazione e del reranker.

### Reranking Cohere

Confronta i primi 10 risultati della pipeline con Cohere sugli stessi 20 candidati. La
chiave è letta soltanto da `COHERE_API_KEY` e non viene scritta negli artefatti:

```yaml
schema_version: 1
dataset: ../../evaluation/silver-set-v1.jsonl
chunk_set_fingerprint: <sha256>
top_k: 10
candidate_k: 20
output_directory: ../../artifacts/benchmarks
configurations:
  - name: bm25
    retriever: bm25
reranker:
  provider: cohere
  model: rerank-v4.0-pro
  search_unit_price_usd: 0.0025
  price_snapshot_date: "2026-09-27"
  request_interval_seconds: 7.0
```

```sh
COHERE_API_KEY=<trial-key> ocio benchmark-retrieval benchmark.yaml
```

Il comando produce manifest JSON, trace JSONL e report JSON con Evidence
Recall@10, MRR@10, alpha-nDCG@10, delta accoppiati, Recall@20, latenze, search
unit fatturate e costo stimato. Il prezzo registrato è lo snapshot del
2026-09-27: USD 2,50 per 1.000 search unit. Un errore Cohere lascia valida la
baseline, registra il caso fallito e rende la decisione `inconclusive`.
L'intervallo di 7 secondi rispetta il limite della trial key di 10 richieste
al minuto e non viene incluso nella latenza della chiamata Cohere.

Per confrontare Jina `jina-reranker-v3.5` sugli stessi candidati:

```sh
JINA_API_KEY=<api-key> ocio benchmark-retrieval ../../evaluation/benchmark-jina-v1.yaml
```

Jina riporta i token processati. Lo snapshot non assegna un costo USD perché
la tariffa pubblica dipende dal pacchetto di token acquistato. La configurazione
usa 7 secondi tra richieste per restare sotto il limite gratuito di 100.000
token al minuto con 20 candidati.
