\# AI Safety Agent



\## Obiettivo



Costruire un agente AI generalista per la \*\*sicurezza sul lavoro\*\*.



Il primo sottosistema è un motore di knowledge retrieval affidabile sulla normativa e documentazione ufficiale. In futuro il RAG sarà un tool dell'agente insieme, ad esempio, ad analisi immagini e generazione/compilazione documenti.



\## Stack



\- Frontend: Vue / Nuxt

\- Backend AI: Python

\- Database: PostgreSQL

\- Vector search: pgvector



\## Fonti e corpus V1

Principio: **API/dati strutturati > HTML > PDF**. La source of truth normativa principale è Normattiva; Gazzetta Ufficiale viene usata come verifica/fonte autentica.

Non ingerire più copie dello stesso testo solo perché pubblicate da enti diversi. Conservare le diverse fonti come provenance, ma scegliere una rappresentazione primaria per il retrieval.

### Corpus normativo iniziale

Il corpus V1 parte da un insieme noto e controllato:

- **D.Lgs. 81/2008 vigente** — backbone principale; recupero da Normattiva in formato strutturato. Conservare anche lo storico, ma indicizzare inizialmente soprattutto il vigente.
- **Accordo Stato-Regioni 59/CSR del 17/04/2025** — formazione salute e sicurezza.
- **FAQ ufficiali MLPS sull'Accordo 59/2025**.
- **D.M. 388/2003** (+ rettifica) — primo soccorso.
- **D.P.R. 462/2001** — impianti di terra/scariche atmosferiche.
- **D.P.R. 177/2011** — ambienti confinati/sospetti di inquinamento.
- **D.M. 11/04/2011** — verifiche periodiche delle attrezzature.
- **D.M. 1, 2 e 3 settembre 2021** — sicurezza antincendio nei luoghi di lavoro.
- **D.M. 13/09/2024** — modifica del D.M. 1/09/2021.
- **D.I. 30/11/2012** — procedure standardizzate per la valutazione dei rischi.
- **D.M. 132/2024** — patente a crediti nei cantieri.

Il D.Lgs. 81/2008 copre già gran parte dei rischi specifici (chimico, biologico, rumore, vibrazioni, campi elettromagnetici, radiazioni ottiche, ATEX, movimentazione carichi, VDT, DPI, attrezzature, cantieri, ecc.).

Normativa molto specialistica esterna al Testo Unico viene aggiunta dopo, quando si decide di coprire quel verticale. Esempi: REACH/CLP per aspetti avanzati del rischio chimico, D.Lgs. 101/2020 per radiazioni ionizzanti, normativa prodotto/macchine e settori speciali.

### Fonti dinamiche note

Per la V1 **non fare discovery automatica di nuove norme**. Si monitorano solo raccolte già note:

- Ministero del Lavoro — interpelli ex art. 12 D.Lgs. 81/2008.
- INL — circolari/note realmente pertinenti alla salute e sicurezza.
- Vigili del Fuoco — circolari e chiarimenti collegati ai D.M. 1/2/3 settembre 2021.
- Ministero del Lavoro — FAQ/chiarimenti sull'Accordo Stato-Regioni 59/2025.
- Normattiva — nuove versioni consolidate degli atti già tracciati.

Gli URL e le regole di acquisizione sono mantenuti in `ocio_sources.yaml`.

INAIL/UNI restano fuori dal corpus normativo V1: potranno diventare in futuro un corpus tecnico separato.

\## Ingestion

La V1 usa **tracked sources**, non discovery automatica.

```text
source registry
      ↓
scarica/leggi documenti noti
      ↓
preferisci formato strutturato
      ↓
parsing canonico
      ↓
chunking
      ↓
indicizzazione
```

Gli atti originali sono sostanzialmente append-only: una nuova legge/decreto normalmente modifica, integra o abroga atti precedenti. Le **viste consolidate** (es. D.Lgs. 81 vigente su Normattiva) invece cambiano quando vengono recepite modifiche.

Per ogni elemento conservare almeno:

- URL/fonte
- identificatore dell'atto
- versione/data di vigenza
- validità
- hash del contenuto

Aggiornamento:

```text
atto tracciato
   ↓
versione/hash cambiato?
   ├─ no → niente
   └─ sì → parse + reindicizza solo sezioni cambiate
```

Non rigenerare embeddings per contenuto invariato. La discovery automatica di atti completamente nuovi è posticipata a fine progetto.

Il retrieval ordinario usa la normativa vigente. Lo storico viene conservato per audit e future query temporali.

\## Parsing



Due canali principali:



1\. API/dati strutturati

2\. PDF layout-aware, probabilmente Docling



OCR/Vision solo come fallback.



Tutte le fonti vengono convertite in un modello dati canonico.



\## Chunking



Scelta:



\*\*Structural chunking + Parent/Child retrieval\*\*



Esempio:



```text

Titolo

&#x20;└─ Capo

&#x20;   └─ Articolo

&#x20;      └─ Comma

```



Indicizzare unità piccole, mantenendo la possibilità di recuperare il contesto padre.



\## Indicizzazione



Doppio indice:



\- semantic search → embeddings + pgvector

\- lexical search → BM25



\## Metadata filtering



Filtrare prima del retrieval quando opportuno:



\- normativa vigente

\- data

\- fonte

\- tipo di documento

\- giurisdizione

\- altri metadata



\## Hybrid Retrieval



Pipeline scelta:



```text

Query

&#x20;↓

Metadata filtering

&#x20;↓

┌──────── BM25

│

└──────── Vector search

&#x20;      ↓

&#x20;     RRF

&#x20;      ↓

&#x20;  Reranker

&#x20;      ↓

&#x20;  Top chunks

```



\### RRF



Reciprocal Rank Fusion fonde le classifiche BM25 e vector basandosi sul ranking, evitando di confrontare score incompatibili.



\### Reranker



Valuta più accuratamente `query + chunk` sui candidati prodotti dal retrieval e sceglie quelli realmente più pertinenti.



\## Query rewriting



Non viene applicato automaticamente a tutto.



Strategia:



```text

query originale

&#x20;↓

retrieval

&#x20;↓

risultati sufficienti?

&#x20;├─ sì → continua

&#x20;└─ no → rewrite / multi-query → nuova ricerca

```



La query originale viene sempre mantenuta.



Query conversazionali incomplete possono essere rese autonome usando il contesto.



Query precise come riferimenti ad articoli/comma non vanno riscritte inutilmente.



\## Context sufficiency



Dopo il reranker separare **relevance** e **sufficiency**.



```text

reranked chunks

&#x20;↓

Relevance gate

&#x20;↓

parent/context expansion

&#x20;↓

Sufficiency gate

&#x20;├─ ANSWER → risposta

&#x20;├─ RETRY → targeted retrieval / query expansion

&#x20;└─ ABSTAIN → informazioni insufficienti

```



### Relevance gate



Usare soprattutto il reranker score come filtro economico per retrieval chiaramente falliti.



La soglia `tau_relevance` non è scelta a intuito: viene calibrata su un dataset annotato, privilegiando recall molto alta dei risultati realmente rilevanti. Lo score del reranker non viene trattato come probabilità.



Il dataset iniziale può essere costruito con query sintetiche da fonti note + hard negatives e annotato da un LLM forte come teacher. I casi ambigui vengono esclusi o revisionati.



### Sufficiency gate



Valuta se il contesto contiene evidenza sufficiente per rispondere alla domanda, non solo se i chunk sono pertinenti.



Segnali principali:



\- coverage dei diversi aspetti della domanda

\- presenza di fonti ufficiali e vigenti

\- correttezza di data, versione e giurisdizione

\- eventuali conflitti tra fonti

\- LLM judge strutturato



Possibile output:



```json

{

  "decision": "RETRY",

  "missing": ["periodicità aggiornamento"],

  "retry_strategy": "targeted_retrieval"

}

```



Il retry cerca soprattutto le informazioni mancanti, mantenendo sempre anche la query originale. Imporre un numero limitato di retry; se l'evidenza ufficiale vigente resta insufficiente → `ABSTAIN`.



Per domande normative, senza una fonte ufficiale vigente sufficiente il sistema non dovrebbe produrre una risposta assertiva.



### Modelli e costo



Non usare un general-purpose LLM forte per ogni passaggio.



\- metadata filtering, RRF, threshold, parent expansion → codice

\- embeddings → embedding model dedicato

\- reranking → reranker dedicato

\- sufficiency ordinaria → modello LLM economico

\- casi ambigui/complessi → escalation a modello più forte

\- modello forte offline → teacher per dataset, eval e analisi dei failure



La scelta concreta dei modelli deve essere fatta tramite eval di qualità, latenza e costo.



\## Evaluation e continuous improvement



Ogni run deve produrre una trace con query, candidati BM25/vector, RRF, reranking, gate, context, risposta, citazioni, versioni dei componenti, latenza e costo.



Classificare i failure, ad esempio:



\- source/ingestion/parsing/chunking error

\- metadata filter error

\- retrieval miss

\- reranking error

\- sufficiency false positive/negative

\- query rewrite drift

\- unsupported generation

\- outdated/conflicting source



Loop di miglioramento:



```text

production traces

&#x20;↓

automatic evaluators

&#x20;↓

human review dei casi dubbi/critici

&#x20;↓

failure classification

&#x20;↓

nuovo regression case / fix al sistema

&#x20;↓

offline experiments

&#x20;↓

deploy solo se le metriche migliorano

```



Il feedback umano non diventa automaticamente verità normativa: la source of truth resta la documentazione ufficiale. Il write-back può aggiornare eval dataset, regole, retrieval hints, ingestion/parsing o segnalare fonti mancanti.



Separare almeno tre eval set:



1. **Retrieval relevance** — query → chunk rilevanti; largamente automatizzabile con LLM teacher.
2. **Context sufficiency** — query + context → evidenza sufficiente o no.
3. **Legal correctness** — query + context + risposta → correttezza normativa; richiede progressivamente validazione di esperti di dominio.



Le annotazioni generate da LLM sono inizialmente **silver labels**; il gold set cresce tramite review umana e casi reali.



\## Architettura futura



Il knowledge system sarà un tool dell'agente:



```text

Safety Agent

&#x20;  ├─ knowledge\_search()   → questo sistema

&#x20;  ├─ analyze\_image()

&#x20;  ├─ generate\_document()

&#x20;  ├─ inspect\_company\_data()

&#x20;  └─ altri tool

```



\## Principio progettuale



Non assumere che una tecnica migliori il sistema solo perché è una best practice.



Ogni componente dovrà essere verificato tramite \*\*evaluation\*\*, confrontando almeno:



\- baseline LLM puro

\- retrieval semplice

\- hybrid retrieval

\- hybrid + reranker

\- query rewriting on/off

\- strategie diverse di chunking

