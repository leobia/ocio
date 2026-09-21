# BM25 in PostgreSQL per l'alpha OCIO

Ricerca aggiornata al 20 settembre 2026. Sono state usate solo fonti ufficiali.

## Raccomandazione

Per il benchmark usare **Tiger Data `pg_textsearch` insieme a `pgvector` su PostgreSQL 17 o 18**.

È la scelta più piccola che soddisfa il requisito: aggiunge un indice BM25 e la relativa operazione di ranking, senza introdurre un secondo servizio né le funzionalità più ampie di un motore di ricerca. Il progetto è sotto licenza PostgreSQL, offre pacchetti Linux amd64/arm64, supporta PostgreSQL 17 e 18 e richiede `shared_preload_libraries` più un riavvio prima di `CREATE EXTENSION`. Tiger Data dichiara la versione 1.0 production-ready da marzo 2026. [Repository e installazione ufficiale](https://github.com/timescale/pg_textsearch) · [Documentazione Tiger Data](https://github.com/timescale/docs/blob/latest/use-timescale/extensions/pg-textsearch.md)

Non considererei però definitiva questa scelta prima del benchmark: conserveremo anche PostgreSQL FTS come baseline e confronteremo la qualità, non solo la tecnologia.

## Come funziona, in breve

L'estensione crea un access method `bm25` su una colonna testuale. BM25 usa statistiche dell'intero corpus: favorisce termini rari, limita il vantaggio dato dalla ripetizione di una parola e normalizza rispetto alla lunghezza del documento. `k1` e `b` sono configurabili. L'indice accelera le query top-k con Block-Max WAND. [Documentazione dell'indice e del ranking](https://github.com/timescale/pg_textsearch#readme)

```sql
CREATE EXTENSION vector;
CREATE EXTENSION pg_textsearch;

CREATE INDEX chunks_bm25_idx
ON chunks USING bm25(content)
WITH (text_config = 'italian');

SELECT id, content,
       content <@> to_bm25query('addetti antincendio', 'chunks_bm25_idx') AS score
FROM chunks
ORDER BY score
LIMIT 20;
```

L'operatore restituisce score negativi per consentire l'ordinamento crescente: un valore più negativo indica un risultato migliore. Dense retrieval (`pgvector`) e BM25 producono due classifiche separate; il codice Python le unisce con RRF o fusione pesata. La documentazione mostra esplicitamente l'uso ibrido con `pgvector`. [Query `pg_textsearch`](https://github.com/timescale/pg_textsearch#querying) · [Esempio hybrid ufficiale](https://github.com/timescale/docs/blob/latest/use-timescale/extensions/pg-textsearch.md#build-hybrid-search-with-semantic-and-keyword-search)

Per l'alpha containerizzata basta una piccola immagine PostgreSQL 17/18 che installi sia `pgvector` sia il pacchetto/binario `pg_textsearch`, configuri `shared_preload_libraries = 'pg_textsearch'`, riavvii e crei le due estensioni. Non occorre un servizio di ricerca separato.

Limite utile da sapere: l'indice BM25 è principalmente su una colonna; per combinare titolo, riferimenti e testo possiamo usare un'expression index che concatena i campi, oppure indicizzare una colonna `search_text` derivata. L'estensione supporta expression index. [Documentazione degli expression index](https://github.com/timescale/pg_textsearch#expression-indexes)

## Confronto essenziale

| Opzione | Cosa offre | Maturità e deployment | Licenza | Valutazione OCIO |
|---|---|---|---|---|
| `pg_textsearch` | BM25 focalizzato, configurazioni linguistiche PostgreSQL, top-k | v1.x; PG 17/18; pacchetti Linux; richiede preload e restart | PostgreSQL | **Prima scelta:** minimo necessario e compatibile con `pgvector` |
| ParadeDB `pg_search` | BM25 più filtri, facet, aggregazioni, join, highlighting e ricerca ibrida | Progetto attivo; Docker/install script; estensione basata su Tantivy; `pgvector` è usato oggi per i vettori | AGPL-3.0 Community, commerciale disponibile | Credibile ma più ampio del bisogno attuale; rivalutare se servono filtri/facet/search analytics avanzati |
| PostgreSQL FTS | `tsvector`/`tsquery`, `ts_rank`, `ts_rank_cd`, GIN/GiST | Built-in, nessuna estensione | PostgreSQL | Baseline obbligatoria, ma **non BM25** |

ParadeDB mantiene dati e ricerca nello stesso PostgreSQL e usa Tantivy per il search; il progetto dichiara esplicitamente BM25, vector retrieval e hybrid search. La Community Edition è AGPL-3.0. [Repository ufficiale ParadeDB](https://github.com/paradedb/paradedb) · [metadati dell'estensione](https://github.com/paradedb/paradedb/blob/main/META.json.in)

La scelta di `pg_textsearch` non dipende dall'idea che ParadeDB sia immaturo: dipende dal principio di non aggiungere ora facet, analytics e altre capacità che il benchmark non usa.

## PostgreSQL FTS è BM25?

No. Il ranking built-in usa `ts_rank` (frequenza dei lessemi) o `ts_rank_cd` (cover density, quindi anche prossimità). La documentazione PostgreSQL precisa inoltre che queste funzioni non usano informazioni globali del corpus; BM25 invece usa, tra le altre cose, inverse document frequency e lunghezza media del corpus. [Documentazione ufficiale PostgreSQL sul ranking](https://www.postgresql.org/docs/17/textsearch-controls.html#TEXTSEARCH-RANKING)

PostgreSQL FTS resta comunque una baseline valida: è quasi gratuito da predisporre, supporta stemming/dizionari e ci dirà se BM25 porta un miglioramento misurabile sul corpus normativo italiano.

## Decisione pratica

1. Partire con PostgreSQL 17 o 18, `pgvector`, FTS built-in e `pg_textsearch` nello stesso container.
2. Eseguire gli stessi casi contro `ts_rank_cd` e BM25.
3. Tenere gli score separati e fondere per posizione con RRF; non confrontare direttamente score BM25 negativi e distanze vettoriali.
4. Provare ParadeDB solo se emergerà un bisogno concreto di filtri/facet/aggregazioni avanzate o se `pg_textsearch` mostra limiti nel benchmark.

