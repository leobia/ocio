# Provider e modelli per il retrieval di OCIO

_Verifica effettuata il 20 settembre 2026. Solo fonti ufficiali; prezzi in USD e al netto di imposte._

## Sintesi decisionale

Per l'alpha locale non cambierei provider: `text-embedding-3-small` come baseline, `text-embedding-3-large` come unico confronto, PostgreSQL per BM25/vector search e un solo reranker locale. Azure è più completo come **piattaforma**, non come singola API OpenAI: il reranker è Azure AI Search Semantic Ranker oppure un modello Cohere distribuito tramite Foundry. Questa completezza aggiunge però infrastruttura e rende meno trasparente il benchmark.

Per una futura produzione UE rivaluterei due percorsi: OpenAI con controlli/residenza dati UE e retrieval posseduto dall'applicazione, oppure stack Azure in una regione UE se servono networking, identità, governance e search gestita. La decisione va presa su eval italiane di OCIO, non sui benchmark dei vendor.

## OpenAI: small contro large

| Modello | Prezzo API | Dimensioni predefinite | Indicazione ufficiale |
|---|---:|---:|---|
| `text-embedding-3-small` | $0,02 / 1M token | 1.536 | variante efficiente |
| `text-embedding-3-large` | $0,13 / 1M token | 3.072 | modello più capace per inglese e lingue non inglesi |

Il prezzo di `large` è **6,5×** quello di `small`; a dimensione piena produce vettori 2× più larghi. Esempio: incorporare 10 milioni di token costa rispettivamente **$0,20** e **$1,30**. Per un corpus normativo piccolo il costo API assoluto è quasi irrilevante; contano di più qualità misurata, spazio dell'indice e latenza. Entrambi accettano il parametro `dimensions`, quindi si può accorciare il vettore per ridurre storage e calcolo. [Scheda e prezzi OpenAI](https://developers.openai.com/api/docs/models/text-embedding-3-large), [dimensioni e limiti](https://learn.microsoft.com/en-us/azure/ai-services/openai/concepts/models?tabs=global-standard%2Cstandard-chat-completions)

La sola comparazione pubblicata da OpenAI riporta, come medie, MIRACL 44,0 per `small` e 54,9 per `large`; MTEB 62,3 contro 64,6. MIRACL è il segnale più pertinente perché multilingue, ma **non misura italiano giuridico né il corpus OCIO**. Il salto di 10,9 punti non può essere tradotto direttamente in Recall@10 sul progetto. [Annuncio e benchmark OpenAI](https://openai.com/index/new-embedding-models-and-api-updates/)

Decisione pratica: partire con `small`, indicizzare lo stesso corpus con `large` una volta, e mantenere `large` solo se migliora materialmente Recall@10/nDCG sulle query italiane difficili. Non serve ottimizzare il costo embeddings prima di questo test.

## Azure: è più completo, ma sono servizi distinti

La nomenclatura va separata:

- **Azure OpenAI** espone modelli OpenAI per generazione ed embeddings; non aggiunge un modello OpenAI dedicato al reranking.
- **Microsoft Foundry** è il catalogo/deployment layer: oltre ai modelli OpenAI offre modelli Cohere per generazione, Embed e Rerank. Al 20 settembre 2026 il catalogo dichiara italiano per Embed v4, Command A e Cohere Rerank 4 Fast/Pro. [Catalogo Foundry](https://learn.microsoft.com/en-ie/azure/foundry/foundry-models/concepts/models-sold-directly-by-azure?pivots=azure-direct-others&view=foundry-classic)
- **Azure AI Search** è il motore di ricerca gestito. Esegue full-text BM25 e vector search, fonde i risultati con RRF e può applicare **Semantic Ranker** ai primi 50 risultati. Il ranker è multilingue, produce anche caption/answer estrattive e non è un endpoint rerank generico per liste arbitrarie. [Hybrid search](https://learn.microsoft.com/en-us/azure/search/hybrid-search-how-to-query), [Semantic Ranker](https://learn.microsoft.com/en-us/azure/search/semantic-search-overview)

Semantic Ranker include 1.000 richieste gratuite al mese; oltre tale quota è pay-as-you-go. Il prezzo esatto dipende da valuta/regione e dal listino Azure configurato, quindi non è corretto fissare qui un numero globale. Anche AI Search ha un costo di servizio/capacità separato da embeddings e generazione. [Piani Semantic Ranker](https://learn.microsoft.com/en-us/AZURE/search/semantic-search-overview)

Conclusione: Azure può fornire l'intero stack sotto lo stesso cloud e billing, ma non è «un provider/modello unico». Per l'alpha sostituire PostgreSQL con AI Search impedirebbe inoltre di confrontare con la stessa trasparenza FTS, BM25, fusion e reranker.

## Cohere: suite retrieval più coerente

Cohere è realmente più completo sul piano dei modelli: offre **Embed**, **Rerank** e **Command** per generazione; gli stessi tipi sono disponibili anche tramite Foundry. Rerank fattura per search unit, definita come una query con fino a 100 documenti (i documenti oltre 500 token possono contare come più chunk). Il sito pubblico corrente mostra chiaramente prezzi dedicati Model Vault, da $4/ora per Embed 4 e $5/ora per Rerank, ma non espone nel markup consultabile un listino pay-as-you-go completo e stabile per Embed/Rerank: va verificato nel dashboard al momento dell'acquisto. [Prezzi Cohere](https://cohere.com/pricing), [modelli Cohere in Foundry](https://learn.microsoft.com/en-us/azure/machine-learning/concept-models-featured?view=azureml-api-2)

Il vantaggio è avere componenti specializzati e una semantica API coerente. Lo svantaggio, per OCIO oggi, è cambiare contemporaneamente embedding, reranker e generatore: rende meno chiaro quale componente migliori il risultato. I benchmark Cohere e OpenAI non vanno confrontati direttamente se dataset, protocollo e metrica differiscono.

## Reranker locale

L'opzione più semplice da provare è `BAAI/bge-reranker-v2-m3`: cross-encoder multilingue, licenza Apache-2.0, eseguibile con Transformers; i pesi sono circa 2,27 GB. È abbastanza leggero da evitare un altro provider, ma la latenza CPU va misurata. [Model card ufficiale](https://huggingface.co/BAAI/bge-reranker-v2-m3)

`jina-reranker-v2-base-multilingual` è più piccolo (circa 562 MB), ma la model card indica licenza CC-BY-NC-4.0: è adatto a esperimenti, non è la scelta prudente per una futura attività commerciale. [Model card Jina](https://huggingface.co/jinaai/jina-reranker-v2-base-multilingual)

## Architettura consigliata

Alpha locale:

```text
PostgreSQL: BM25/FTS + pgvector
OpenAI: text-embedding-3-small (baseline) / large (un confronto)
Python: RRF + metriche
Locale: bge-reranker-v2-m3 (un esperimento, dopo la fusion)
OpenAI: generazione, solo nella milestone successiva
```

Produzione UE, se e quando serve:

1. mantenere adapter separati per embedding, reranking e generazione;
2. non migrare ad Azure prima che requisiti di governance/operatività lo giustifichino;
3. confrontare il reranker locale con Azure Semantic Ranker o Cohere Rerank sul gold/silver set italiano;
4. verificare in quel momento regione, data residency, listino e termini: disponibilità e prezzi cloud sono variabili nel tempo.

La raccomandazione immediata è quindi **OpenAI embeddings + reranker locale opzionale**, non perché sia universalmente migliore, ma perché isola bene gli esperimenti e minimizza l'infrastruttura dell'alpha.
