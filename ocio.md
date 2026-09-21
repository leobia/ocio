# OCIO — assistente AI per la sicurezza sul lavoro

## Visione

OCIO vuole diventare un agente AI per la sicurezza sul lavoro capace di usare più strumenti:

- ricerca affidabile nella normativa e nelle fonti ufficiali;
- analisi di immagini;
- analisi di dati e documenti aziendali;
- supporto alla composizione del DVR e di altri documenti.

Questa è la direzione di lungo periodo, non il perimetro della prima alpha. Il primo sottosistema è un knowledge tool normativo verificabile, che in futuro sarà esposto all'agente come `knowledge_search()`.

## Alpha

### Utenti

L'alpha è uno strumento interno per RSPP e consulenti. Sarà provata da chi sviluppa OCIO e da un RSPP, usando esclusivamente casi fittizi.

### Problema

Ridurre il tempo necessario a trovare e verificare obblighi, articoli e chiarimenti ufficiali sulla sicurezza sul lavoro italiana.

La V1 supporta:

1. ricerca puntuale di atti e articoli;
2. domande concettuali in linguaggio naturale;
3. piccoli casi aziendali fittizi descritti in chat.

Le domande storiche e il confronto automatico tra versioni sono rimandati. Lo storico viene comunque conservato nel modello dati.

### Esperienza utente

L'interfaccia è una chat simile a ChatGPT con un pannello delle fonti. Ogni risposta mostra, quando applicabile:

- risposta breve;
- condizioni, limiti e informazioni mancanti;
- fonte, versione e data di vigenza;
- articolo, comma e passaggio citato;
- link alla fonte ufficiale;
- feedback strutturato.

Il sistema distingue ciò che la fonte stabilisce da ciò che dipende dal caso concreto. Può fornire una risposta condizionata, ma non dichiara autonomamente che un'azienda è conforme e non sostituisce il giudizio professionale.

Se manca un'informazione, risponde per la parte supportata e formula una domanda di chiarimento. Se l'evidenza è insufficiente, mostra ciò che ha trovato e ciò che manca senza completare il vuoto con una risposta probabile.

### Obiettivi iniziali

- recuperare quasi sempre l'evidenza pertinente;
- non produrre risposte normative prive di supporto;
- rendere fonti e limiti verificabili;
- costruire una base sperimentale per imparare e migliorare il RAG.

### Fuori dal perimetro dell'alpha

- generazione del DVR;
- analisi di immagini;
- caricamento di documenti aziendali;
- dati personali, sanitari o casi reali;
- profili aziendali persistenti;
- query storiche e confronto tra versioni;
- discovery automatica di nuove norme;
- GraphRAG;
- retrieval agentico;
- infrastruttura GPU e modelli self-hosted.

## Principi

1. **La fonte ufficiale prevale.** Il feedback umano e le annotazioni LLM non diventano verità normativa.
2. **La risposta deve essere verificabile.** Ogni affermazione normativa importante deve avere una citazione controllata.
3. **Relevance e sufficiency sono problemi diversi.** Un passaggio può essere pertinente ma non sufficiente a rispondere.
4. **Il sistema deve potersi astenere.** In assenza di evidenza ufficiale vigente non produce una risposta assertiva.
5. **Prima la baseline, poi la complessità.** Ogni tecnica entra solo se migliora le evaluation.
6. **Componenti sostituibili.** Modelli e provider sono adapter, non dipendenze del dominio.
7. **Niente microservizi prematuri.** L'alpha è un modular monolith.

## Roadmap

```text
1. Corpus canonico e versionato
2. Benchmark del retrieval
3. Generazione con citazioni e sufficiency
4. Memoria conversazionale
5. UI chat, fonti e feedback
6. Alpha interna con casi fittizi
7. Aggiornamento automatico delle fonti
8. Casi reali e requisiti privacy
9. Immagini e altri tool
10. Supporto alla composizione del DVR
```

Il piano implementativo è descritto in [`docs/implementation-plan.md`](docs/implementation-plan.md).

## Stack e architettura

- Frontend: Vue/Nuxt
- Backend: Python
- Database: PostgreSQL 17 o 18
- Vector search: pgvector
- BM25 sperimentale: `pg_textsearch`
- Embeddings: OpenAI, dietro adapter
- Reranking sperimentale: Cohere, dietro adapter

```text
Nuxt
  ↓ HTTP
Python modular monolith
  ├─ ingestion
  ├─ retrieval
  ├─ generation
  ├─ conversations
  └─ evaluation
  ↓
PostgreSQL
  ├─ dati canonici
  ├─ full-text search
  ├─ pg_textsearch / BM25
  └─ pgvector
```

Ingestion, benchmark ed evaluation iniziano come comandi CLI manuali. Scheduler, code di job e servizi separati vengono introdotti solo quando esiste un requisito concreto.

## Fonti e corpus

Il registry autorevole è `ocio_sources.yaml`. La regola di acquisizione è:

```text
dati strutturati/API > HTML > PDF layout-aware > OCR/vision
```

Normattiva è la fonte tecnica primaria per il testo vigente e multivigente. Gazzetta Ufficiale è usata come fonte autentica e verifica. Fonti duplicate diventano provenance dello stesso contenuto, non copie indipendenti nel retrieval.

### Corpus del benchmark

1. intero D.Lgs. 81/2008 vigente;
2. successiva aggiunta dell'Accordo Stato-Regioni 59/CSR/2025;
3. FAQ ufficiali MLPS relative all'Accordo.

Gli altri atti già elencati nel registry entrano dopo che ingestion e retrieval sono stati validati.

### Aggiornamenti

Gli atti originali sono trattati come append-only; le viste consolidate sono versionate. Per ogni acquisizione conservare almeno:

- provider e URL;
- identificatore dell'atto;
- versione e intervallo di vigenza;
- hash del contenuto;
- data di acquisizione;
- provenance.

Il controllo di nuove versioni sarà automatico, mentre la pubblicazione nell'indice richiederà inizialmente una revisione manuale. Il contenuto invariato non viene rielaborato né re-embedded.

## Modello canonico

```text
Act
└─ ActVersion
   └─ StructuralUnit
      ├─ titolo
      ├─ capo
      ├─ articolo
      ├─ comma
      └─ lettera
```

I chunk sono proiezioni indicizzabili delle unità strutturali, non la source of truth. Una stessa versione può produrre più collezioni di chunk per confrontare strategie differenti senza ripetere il parsing.

## Milestone B — benchmark del retrieval

La prima milestone non genera risposte e non include una UI. Misura soltanto:

```text
query → candidati → ranking → evidenze attese
```

### Dataset

Il silver set iniziale contiene circa 100 query:

- 50% domande concettuali;
- 25% piccoli casi aziendali fittizi;
- 10% domande multi-aspetto;
- 10% termini colloquiali o abbreviati;
- 5% riferimenti espliciti o parziali;
- un gruppo separato di domande non rispondibili con il corpus.

Prompt versionati, eseguiti manualmente in ChatGPT, producono JSON validato automaticamente contro il corpus. Il dataset resta dichiaratamente silver: l'analisi dei fallimenti individuerà il rumore senza introdurre una pipeline di validazione complessa.

Ogni caso specifica documento, articolo e, quando disponibile, comma o lettera attesi, aspetti richiesti, tipo di query, difficoltà e rispondibilità.

### Chunking da confrontare

1. articolo intero;
2. comma child con articolo parent;
3. finestra fissa con overlap;
4. chunk strutturale con accorpamento delle unità troppo brevi.

Si valuta separatamente il recupero del chunk preciso e la copertura complessiva ottenuta tramite parent expansion.

### Candidate retrieval

```text
riferimento esplicito ─→ lookup deterministico ─┐
PostgreSQL FTS ────────────────────────────────┤
pg_textsearch / BM25 ─────────────────────────┼→ fusion → rerank opzionale
OpenAI embeddings + pgvector ─────────────────┘
```

Il lookup deterministico accetta anche riferimenti parziali e aggiunge candidati, senza escludere la ricerca ibrida.

Confronti progressivi:

1. PostgreSQL full-text;
2. BM25;
3. dense retrieval;
4. hybrid con Reciprocal Rank Fusion;
5. hybrid con fusione pesata;
6. miglior hybrid senza reranker contro Cohere Rerank.

RRF è la baseline di fusione perché combina i rank senza confrontare score incompatibili. La fusione pesata viene mantenuta solo se migliora le evaluation.

La baseline embedding è `text-embedding-3-small`; `text-embedding-3-large` è l'unico confronto iniziale. Cohere Rerank è adottato solo se produce un miglioramento materiale. L'implementazione dipende da interfacce interne, così un futuro adapter TEI può servire un reranker open-weight su CPU o GPU senza modificare la pipeline.

Query expansion, multi-query, SPLADE, ColBERT e GraphRAG sono esperimenti differiti. Un glossario versionato di abbreviazioni e sinonimi viene provato solo dopo la baseline senza espansione.

### Metriche e criterio di uscita

- metrica primaria: Recall@10;
- ranking: MRR e nDCG@5/10;
- coverage degli aspetti per query multi-hop;
- latenza e costo;
- analisi dei fallimenti per categoria.

Obiettivo indicativo per passare alla generazione:

- Recall@10 almeno 90% complessivo;
- nessuna categoria importante sotto 80%;
- analisi manuale di ogni fallimento;
- miglioramento verificabile rispetto a lexical-only e dense-only.

Ogni run produce trace JSONL, metriche aggregate, report degli errori e un manifest con snapshot del corpus, dataset, chunking, configurazioni, modelli e versioni dei componenti.

## Generazione e sufficiency

Dopo il benchmark, la pipeline iniziale sarà deterministica:

```text
query e contesto conversazionale
        ↓
hybrid retrieval
        ↓
reranker opzionale
        ↓
relevance threshold
        ↓
LLM sufficiency judge
   ├─ ANSWER
   └─ ABSTAIN
```

Non sono previsti retry automatici iniziali. Verranno aggiunti solo se le trace mostrano failure recuperabili con una seconda ricerca.

Il modello generativo OpenAI è configurabile: un modello economico sarà il default, con eventuale escalation a un modello più forte decisa tramite evaluation.

### Contratto della risposta

Il backend assegna citation ID ai passaggi recuperati. Il modello può utilizzare soltanto questi ID; URL e riferimenti completi vengono risolti dal backend.

```text
Risposta breve

Condizioni e limiti
- dati mancanti
- aspetti dipendenti dal caso concreto

Riferimenti
- atto, versione, articolo e comma
- passaggio
- data di vigenza
- link ufficiale
```

Ogni affermazione normativa importante deve essere collegata ad almeno una citation ID.

## Conversazione

La memoria non coincide con l'intera chat. È composta da:

1. log completo e immutabile;
2. finestra recente limitata da un budget di token;
3. `case_state` tipizzato, visibile e correggibile;
4. breve sommario degli obiettivi aperti;
5. query autonoma per il retrieval, conservando sempre anche la query originale.

I fatti del caso hanno stato `confirmed`, `inferred` o `unknown` e mantengono il riferimento al turno di origine. Il sommario non è autorevole per numeri, date e condizioni aziendali. La ricerca semantica nella cronologia viene aggiunta solo se le evaluation mostrano che finestra e stato strutturato non bastano.

## Tracing e feedback

Per ogni turno conservare:

- query originale e riscritta;
- snapshot del `case_state`;
- candidati lexical e dense con rank e score;
- risultati di fusion e reranking;
- chunk finali e relative versioni;
- decisione di sufficiency;
- modello, prompt, parametri e versioni;
- risposta e mapping claim-citation;
- latenza, costo e feedback.

Il feedback nell'alpha include:

- utile/non utile;
- fonte corretta/non corretta;
- risposta corretta/incompleta/errata;
- commento opzionale;
- fonte mancante opzionale.

Per l'alpha con casi fittizi vengono conservate trace complete. Prima di accettare dati reali sarà necessario definire minimizzazione, retention, DPA, data residency e valutare Zero Data Retention. DeepSeek hosted non è un provider ammesso per dati personali italiani; può essere rivalutato soltanto come modello self-hosted.

## Evaluation continua

Mantenere separati almeno:

1. retrieval relevance;
2. context sufficiency;
3. correttezza e supporto delle risposte.

Le label generate da LLM sono silver. Un gold set crescerà lentamente dai casi reali e dai feedback revisionati. Il primo RSPP coinvolto fornirà feedback dall'applicazione, non è assunto come annotatore sistematico prima del rilascio.

Categorie di failure:

- ingestion, parsing o chunking;
- filtro metadata;
- retrieval miss;
- fusione o reranking;
- rewrite drift;
- sufficiency false positive/negative;
- citazione o generazione non supportata;
- fonte obsoleta o conflittuale.

## Decisioni sperimentali ancora aperte

Questi punti devono essere risolti dai benchmark, non tramite preferenze:

- strategia di chunking;
- PostgreSQL FTS contro BM25;
- embedding OpenAI small contro large;
- RRF contro fusione pesata;
- valore effettivo di Cohere Rerank;
- soglie di relevance e sufficiency;
- modello OpenAI per generation/judging;
- dimensione della finestra conversazionale.

## Approfondimenti

- [`docs/research/conversational-hybrid-rag-and-orchestration.md`](docs/research/conversational-hybrid-rag-and-orchestration.md)
- [`docs/research/postgresql-bm25-extensions.md`](docs/research/postgresql-bm25-extensions.md)
- [`docs/research/provider-data-privacy.md`](docs/research/provider-data-privacy.md)
- [`docs/research/reranker-online-deployment-options.md`](docs/research/reranker-online-deployment-options.md)
- [`docs/research/retrieval-model-providers.md`](docs/research/retrieval-model-providers.md)
