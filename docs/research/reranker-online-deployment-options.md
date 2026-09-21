# Opzioni di deployment online per il reranker di OCIO

_Verifica effettuata il 20 settembre 2026. Solo fonti ufficiali._

## Risposta breve

La macchina di sviluppo non è necessaria in produzione. Il reranker può essere:

1. chiamato come API SaaS (`Cohere Rerank`);
2. eseguito in un container CPU insieme all'app o come sidecar;
3. ospitato su un endpoint ML gestito CPU/GPU;
4. sostituito da un reranker integrato in un motore di ricerca gestito.

Per OCIO sceglierei **Cohere Rerank nell'alpha online**, mantenendo un'interfaccia `Reranker` interna. Se volume, privacy o costo lo giustificano, la migrazione più semplice è un modello open-weight servito con Hugging Face Text Embeddings Inference (TEI), prima su CPU e poi, solo se le misure lo richiedono, su un endpoint GPU gestito.

## Confronto

| Opzione | Topologia e costo | Operazioni | Controllo dati | Fit OCIO |
|---|---|---|---|---|
| Cohere Rerank API | Backend → API; tariffazione per ricerca | Minime | Testo inviato a Cohere; opzioni private enterprise separate | Migliore per alpha e traffico basso |
| Container CPU proprio | Backend → processo/sidecar TEI; costo della VM/container già acceso | Medio-basse | Dati nel proprio ambiente | Ottimo se un modello piccolo rispetta la latenza |
| Hugging Face Inference Endpoint | Endpoint dedicato CPU/GPU, tariffa oraria dell'istanza; scale-to-zero disponibile | Basse | Provider/regione e accesso privato configurabili | Buon ponte verso open weights gestiti |
| Azure ML/Foundry managed compute | Endpoint dedicato e autoscaling; Foundry managed compute è ancora preview | Medio-alte | Buon controllo Azure/VNet/identità | Eccessivo per alpha; utile in un'azienda già Azure |
| Azure AI Search Semantic Ranker | Il reranking è dentro il motore search e viene fatturato a richiesta oltre la quota gratuita | Basse, ma richiede migrare l'indice | Dati e indice in Azure Search | Valido solo se si sceglie Azure Search come intero retrieval stack |
| AWS SageMaker | Container modello su endpoint gestito; modalità serverless/async possono scalare a zero | Alte rispetto alle necessità attuali | Controllo AWS/VPC | Solido ma non è il percorso più semplice per OCIO |

## 1. Cohere: il percorso più semplice

`rerank-v4.0-fast` e `rerank-v4.0-pro` sono modelli multilingue e accettano una query più una lista di documenti. `fast` privilegia latenza/throughput, `pro` qualità e casi complessi. La piattaforma pubblica è completamente gestita e fattura Rerank per numero di ricerche, quindi non esiste un server da mantenere né capacità idle da pagare. [Modelli Rerank](https://docs.cohere.com/docs/rerank), [modello di prezzo](https://docs.cohere.com/docs/how-does-cohere-pricing-work)

Cohere offre anche deployment dedicati, VPC e on-premise, ma sono percorsi enterprise: il VPC aumenta il controllo e anche l'onere operativo. [Opzioni di deployment](https://docs.cohere.com/docs/deployment-options-overview)

Per l'alpha con dati fittizi è l'opzione pragmatica. Prima di casi reali vanno rivalutati termini, localizzazione e conservazione dei dati.

## 2. Self-hosting senza GPU: container CPU

TEI è un server di inferenza open source che espone `/rerank`, supporta cross-encoder multilingue e distribuisce immagini Docker sia CPU sia GPU. Include batching, metriche Prometheus e tracing OpenTelemetry. Quindi lo stesso container provato localmente può essere distribuito su una normale VM o piattaforma container; non deve risiedere sulla workstation dello sviluppatore. [TEI e reranker](https://github.com/huggingface/text-embeddings-inference)

Topologie semplici:

```text
un solo servizio                 due servizi
┌────────────────────┐          ┌─────────┐ HTTP ┌─────────┐
│ API + modello CPU  │          │ API     │─────▶│ TEI CPU │
└────────────────────┘          └─────────┘      └─────────┘
```

Il primo schema costa meno e semplifica il deploy, ma il modello consuma RAM e CPU dell'app. Il sidecar/servizio separato isola risorse e scaling. La fattibilità non dipende dall'etichetta “CPU”: dipende da modello, top-K, lunghezza chunk e latenza richiesta. Va benchmarkato un modello più piccolo su una CPU cloud reale prima di acquistare GPU.

## 3. Open weights su endpoint gestito

### Hugging Face Inference Endpoints

Hugging Face avvia un container gestito con modello e inference engine su AWS, Azure o GCP, con scelta di regione, CPU/GPU e accesso privato. Gestisce ciclo di vita, health e autoscaling. [Configurazione](https://huggingface.co/docs/inference-endpoints/guides/configuration), [funzionamento](https://huggingface.co/docs/inference-endpoints/about)

Può scalare a zero dopo inattività, ma il primo request subisce cold start; durante l'avvio può restituire `502` e la documentazione raccomanda retry/queue lato client. Il costo segue l'istanza mentre è attiva. [Autoscaling e scale-to-zero](https://huggingface.co/docs/inference-endpoints/autoscaling)

È la scelta gestita più diretta se vogliamo mantenere un reranker open-weight senza costruire infrastruttura ML.

### Azure

Azure ML managed online endpoints gestisce serving, scaling, sicurezza e monitoraggio su CPU/GPU, con autoscaling configurato tramite Azure Monitor. È più flessibile ma richiede workspace, deployment, immagini, regole di scaling e osservabilità Azure. [Managed online endpoints](https://learn.microsoft.com/en-gb/azure/machine-learning/concept-endpoints-online?view=azureml-api-2), [autoscaling](https://learn.microsoft.com/en-us/azure/machine-learning/how-to-autoscale-endpoints?view=azureml-api-2)

Microsoft Foundry offre anche Cohere Rerank 4 Fast/Pro, incluso l'italiano, come modelli venduti direttamente da Azure. Tuttavia il managed compute per open/custom weights è attualmente in preview e senza SLA, quindi non lo sceglierei come prima produzione. [Catalogo Cohere](https://learn.microsoft.com/en-ie/azure/ai-foundry/foundry-models/concepts/models-sold-directly-by-azure?pivots=azure-direct-others&view=foundry-classic), [deployment Foundry](https://learn.microsoft.com/en-us/azure/foundry/concepts/deployments-overview)

### AWS SageMaker

SageMaker può ospitare un container custom con inferenza real-time, serverless o asincrona. Serverless e async possono scalare a zero; l'asincrono accoda le richieste ed è più adatto a near-real-time che a una chat immediata. È una piattaforma completa, ma per un singolo reranker introduce più configurazione di Cohere o Hugging Face Endpoints. [FAQ hosting](https://docs.aws.amazon.com/sagemaker/latest/dg/hosting-faqs.html), [inferenza asincrona](https://docs.aws.amazon.com/sagemaker/latest/dg/async-inference.html)

## 4. Reranking dentro il motore di ricerca

Azure AI Search Semantic Ranker riordina una lista iniziale prodotta da BM25 o RRF tramite modelli Microsoft multilingue. Ha una quota mensile gratuita e poi fatturazione pay-as-you-go. Non è però un endpoint generico da applicare ai candidati di PostgreSQL: è una fase della pipeline Azure AI Search. [Semantic Ranker](https://learn.microsoft.com/en-us/azure/search/semantic-search-overview)

Di conseguenza ha senso solo se si decide di spostare anche indice lexical/vector e hybrid retrieval da PostgreSQL ad Azure AI Search. Non migrerei l'intero stack soltanto per ottenere un reranker.

Non ho trovato nelle fonti ufficiali esaminate un'estensione PostgreSQL che esegua un cross-encoder semantic reranking comparabile: PostgreSQL resta il candidate retriever, mentre il reranker vive nel processo applicativo o dietro un endpoint.

## Percorso raccomandato

```text
benchmark
  nessun reranker vs Cohere Fast/Pro
              ↓ valore misurabile?
alpha online
  Cohere API + adapter interno
              ↓ volume/privacy/costo lo richiedono?
produzione open-weight
  TEI CPU container
              ↓ latenza insufficiente?
  HF endpoint CPU/GPU o cloud ML già adottato dall'azienda
```

Il contratto applicativo deve restare piccolo:

```python
class Reranker(Protocol):
    def rank(self, query: str, candidates: list[Candidate], top_n: int) -> list[Candidate]: ...
```

Trace da conservare: provider/modello, input candidate IDs, score, ordine, latenza e costo stimato. In questo modo passare da Cohere a TEI cambia un adapter, non la pipeline retrieval.

