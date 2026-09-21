# Conversational hybrid RAG e orchestrazione

Verifica delle fonti: 20 settembre 2026. Ambito: alpha italiana per ricerca normativa sulla sicurezza sul lavoro.

## Decisione consigliata

Per l'alpha non scegliere una singola “memoria”. Usare quattro strati separati:

1. log immutabile della conversazione;
2. finestra recente limitata da un budget di token;
3. `case_state` tipizzato, visibile e correggibile;
4. query autonoma e ispezionabile per il retrieval, conservando sempre anche la domanda originale.

Il sommario progressivo può aiutare con narrativa e obiettivi aperti, ma non deve essere la fonte autorevole dei fatti aziendali. La ricerca semantica nella cronologia va aggiunta solo quando conversazioni reali dimostrano che finestra recente e stato strutturato non bastano.

Per la milestone B conviene inoltre un core Python esplicito, con DTO e interfacce posseduti dal progetto. Le librerie specialistiche possono implementare singoli adattatori, ma un framework di orchestrazione completo renderebbe meno trasparente proprio ciò che l'esperimento deve confrontare. Haystack è l'alternativa più naturale se servirà presto una pipeline RAG dichiarativa; LangGraph quando il flusso diventerà realmente stateful; LlamaIndex soprattutto per ingestion e astrazioni documentali; DSPy dopo aver ottenuto metriche affidabili.

Non esiste nelle fonti primarie consultate una base seria per dire quale framework “usa il settore” in senso quantitativo. Le documentazioni dimostrano capacità, non adozione: il confronto seguente evita quindi classifiche di popolarità.

## Memoria e retrieval conversazionale

### 1. Query autonoma: baseline raccomandata

Il *standalone query rewriting* trasforma il turno corrente e il contesto necessario in una domanda autosufficiente. CONQRR mostra il vantaggio architetturale centrale: il rewriter può lavorare davanti a retriever esistenti trattati come black box ed essere ottimizzato per il risultato del retrieval, non soltanto per una riscrittura linguisticamente plausibile ([Wu et al., EMNLP 2022](https://aclanthology.org/2022.emnlp-main.679/)).

Per l'alpha:

```text
domanda originale + ultimi turni + case_state
                    ↓
            standalone_query
                    ↓
     lexical + dense → fusion → rerank
```

Conservare sia `original_query` sia `standalone_query`. Come esperimento, recuperare candidati anche con l'originale e fondere i risultati: limita il danno di una riscrittura che perde un termine esatto. Se il rewriter deve scegliere tra interpretazioni incompatibili, il comportamento corretto è chiedere chiarimento, non nascondere la scelta.

### 2. Alternative

| Alternativa | Vantaggio | Costo/rischio | Decisione |
|---|---|---|---|
| Query autonoma | Ispezionabile, testabile, compatibile con retrieval ibrido standard | Una chiamata/modello in più; possibile deriva semantica | Baseline |
| Embedding contestuale di query + storia | Integra il contesto direttamente nel retriever e può evitare una pipeline separata | Richiede un retriever adattato; è meno facile capire che cosa sia stato cercato | Esperimento futuro ([Lin et al., EMNLP 2021](https://aclanthology.org/2021.emnlp-main.77/)) |
| Rewrite + contextual retrieval | Le due tecniche possono essere complementari | Più componenti, training e diagnosi | Fuori dall'alpha ([Qian & Dou, EMNLP 2022](https://aclanthology.org/2022.emnlp-main.311/)) |
| Multi-query/expansion | Può coprire richieste con più aspetti | Aumenta costo e può introdurre termini non detti | Ramo sperimentale per domande composte ([ConvGQR](https://aclanthology.org/2023.acl-long.274/), [MQ4CS](https://aclanthology.org/2026.eacl-long.383/)) |
| Domanda di chiarimento | Evita una disambiguazione arbitraria | Aggiunge un turno | Necessaria nei casi realmente ambigui; studi di conversational search mostrano benefici del chiarimento rispetto alla sola riformulazione ([Aliannejadi et al.](https://arxiv.org/abs/2307.08803)) |

Non passare l'intera conversazione come query di ricerca: mescola intenzioni vecchie e nuove e impedisce di attribuire un errore al rewriter o al retriever.

### 3. Stato conversazionale a strati

**Finestra recente.** È il meccanismo più semplice per anafore ed ellissi locali. Deve essere limitata per token, non solo per numero di messaggi, preservando messaggio di sistema e coppie tool-call/risultato; Semantic Kernel documenta strategie distinte di troncamento, sommario e soglia token proprio per questo scopo ([documentazione Semantic Kernel](https://learn.microsoft.com/en-us/semantic-kernel/concepts/ai-services/chat-completion/chat-history)).

**Sommario progressivo.** Estende l'orizzonte comprimendo i turni vecchi, ma è una trasformazione lossy prodotta da un modello. LangMem, per esempio, conserva un `RunningSummary` e sostituisce i messaggi oltre soglia con il sommario ([documentazione LangMem](https://langchain-ai.github.io/langmem/reference/short_term/)). Usarlo per obiettivi e filo narrativo, non per numeri, date o condizioni da cui dipende una risposta normativa.

**Stato strutturato del caso.** Per fatti noti a schema — settore, dipendenti, turni, sedi, attrezzature, data di riferimento — un oggetto tipizzato è più controllabile di un sommario. La guida LangGraph raccomanda di conservare stato grezzo e formattarlo solo quando si costruisce il prompt ([Thinking in LangGraph](https://docs.langchain.com/oss/javascript/langgraph/thinking-in-langgraph)). Un campo dovrebbe contenere almeno:

```json
{
  "value": "12",
  "source_turn_id": "turn_7",
  "status": "confirmed",
  "updated_at": "..."
}
```

Gli stati utili sono `confirmed`, `inferred` e `unknown`. Una correzione aggiorna lo stato operativo senza cancellare il log, e l'utente deve poter vedere e correggere i fatti estratti.

**Retrieval sulla conversazione.** Checkpointer e store sono meccanismi distinti in LangGraph: il primo conserva lo stato di un thread, il secondo dati applicativi ricercabili anche tra thread ([documentazione persistence](https://langchain-ai.github.io/langgraphjs/how-tos/cross-thread-persistence-functional/)). La ricerca semantica dei messaggi è utile per conversazioni molto lunghe o cross-session, ma per un singolo caso alpha crea un secondo corpus con rischio di recuperi spurii. Conservarne i dati, ma non introdurla finché una evaluation non mostra una perdita reale di fatti.

Configurazione iniziale proposta: ultimi 4–8 turni, con limite effettivo per token; `case_state`; breve sommario degli obiettivi aperti; domanda originale e riscritta. Il numero di turni è un'ipotesi da misurare, non una best practice universale.

## Citazioni, trace ed evaluation

Ogni affermazione normativa deve puntare a un citation ID fornito dal backend. Il modello non dovrebbe inventare URL o riferimenti: il server risolve l'ID in atto, versione/vigenza, articolo, comma, chunk e possibilmente span esatto.

La trace minima per turno deve contenere:

- query originale, snapshot dello stato e contesto dato al rewriter;
- query riscritta ed eventuali query alternative;
- candidati lexical e dense con score e rank;
- graduatoria dopo fusion e rerank;
- chunk finali con versione;
- prompt, modello, parametri e versioni dei componenti;
- risposta, mapping claim→citation, sufficiency/abstention;
- latenza, costo e feedback.

La valutazione va separata per componente. Haystack supporta evaluation di componenti e pipeline end-to-end e metriche con e senza ground truth ([documentazione Haystack](https://docs.haystack.deepset.ai/docs/evaluation)); LangSmith distingue benchmark, unit test, regression test e valutazioni online ([documentazione LangSmith](https://docs.langchain.com/langsmith/evaluation-types)). RAGAS formalizza dimensioni distinte come precision/recall del contesto, faithfulness e answer relevance ([Es et al., EACL 2024](https://aclanthology.org/2024.eacl-demo.16/)). Per questo dominio i giudizi LLM devono integrare, non sostituire, document IDs attesi e campioni umani.

La suite conversazionale deve includere almeno: anafora, ellissi, aggiunta progressiva di fatti, correzione, contraddizione, cambio argomento, ritorno a un tema vecchio, domanda autosufficiente che non deve ereditare contesto e ambiguità che richiede chiarimento. Misurare `Recall@k`, MRR/nDCG, fedeltà del rewrite, supporto delle citazioni, astensione corretta, aggiornamento dei fatti e contaminazione da contesto obsoleto.

## Orchestrazione: alternative

### Core Python esplicito — scelta per la milestone B

Definire interfacce piccole (`LexicalRetriever`, `DenseRetriever`, `Fusion`, `Reranker`, `QueryRewriter`) e record serializzabili di input/output. Questo massimizza visibilità e test unitari e mantiene confrontabili strategie diverse. Il costo è scrivere configurazione, lifecycle e tracing; per ridurlo si possono usare librerie specialistiche dietro adapter e una strumentazione indipendente dal framework.

Questa è una scelta progettuale per l'esperimento, non una pretesa che il Python custom sia sempre superiore.

### Haystack

Haystack modella pipeline come multigrafi diretti con rami e loop e controlla la compatibilità degli input/output dei componenti prima dell'esecuzione ([pipeline](https://docs.haystack.deepset.ai/docs/pipelines)). Offre componenti custom ([componenti](https://docs.haystack.deepset.ai/docs/custom-components)), serializzazione ([serializzazione](https://docs.haystack.deepset.ai/docs/serialization)), evaluation di componenti/end-to-end ([evaluation](https://docs.haystack.deepset.ai/docs/evaluation)) e tracing OpenTelemetry/custom ([tracing](https://docs.haystack.deepset.ai/docs/tracing)). È quindi la migliore alternativa immediata per rappresentare esplicitamente retrieve→fuse→rerank. Il lock-in è medio: i passaggi assumono i contratti `@component` e la serializzazione Haystack.

### LangChain / LangGraph

LangChain offre interfacce e integrazioni standard; la documentazione indica LangGraph come livello per maggiore controllo, workflow stateful, persistenza e human-in-the-loop ([overview](https://docs.langchain.com/oss/python/learn), [reference LangGraph](https://langchain-ai.github.io/langgraph/reference/)). È troppo per un benchmark lineare, ma diventa appropriato quando serviranno stato conversazionale durevole, correzioni, pause/approvazioni e ripresa dopo errori. I checkpoint supportano backend in-memory, SQLite e PostgreSQL ([checkpointing](https://langchain-ai.github.io/langgraph/reference/checkpoints/)). LangSmith può tracciare anche codice non LangChain e permette feedback su singoli child run, utile per distinguere errori di retrieval e generazione ([feedback](https://docs.langchain.com/langsmith/attach-user-feedback)).

### LlamaIndex

LlamaIndex è interessante se ingestion, connector, indici e query engine diventano il collo di bottiglia; offre anche valutatori di retrieval e risposta ([evaluation](https://docs.llamaindex.ai/en/v0.10.19/understanding/evaluating/evaluating.html)). Va adottato dietro adapter se vogliamo continuare a vedere le meccaniche del retrieval. La sua vecchia `QueryPipeline` è esplicitamente in feature-freeze/deprecazione a favore dei Workflows, un esempio concreto del costo di legarsi alle astrazioni di orchestrazione ([documentazione QueryPipeline](https://docs.llamaindex.ai/en/stable/module_guides/querying/pipeline/)).

### DSPy

DSPy non sostituisce l'orchestratore operativo: definisce programmi LM dichiarativi e ottimizza prompt/esempi/parametri rispetto a una metrica e a esempi di training ([paper DSPy, ICLR 2024](https://openreview.net/pdf?id=sY5N0zY5Od), [documentazione optimizer](https://github.com/stanfordnlp/dspy/blob/main/docs/docs/learn/optimization/optimizers.md)). Ha valore dopo che silver/gold set e metrica sono abbastanza affidabili; prima rischia di ottimizzare il rumore del dataset sintetico.

## Sequenza suggerita

1. Benchmark Python con output JSONL e contratti stabili.
2. Confronto tra lexical, dense, fusion RRF/pesata e reranker con metriche deterministiche.
3. Aggiunta di tracing indipendente senza cambiare i contratti del dominio.
4. Haystack solo se configurazione e riuso della pipeline iniziano a compensare l'astrazione.
5. LangGraph solo quando il flusso conversazionale richiede davvero stato durevole e branching.
6. DSPy solo dopo esempi revisionati e una metrica credibile.

La cosa più formativa per arrivare a un risultato robusto è implementare direttamente il primo benchmark: rende osservabili chunking, query rewrite, candidate generation, fusion, reranking e metriche. In seguito i framework saranno scelte informate, non scorciatoie opache.
