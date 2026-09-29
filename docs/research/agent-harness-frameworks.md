# Harness dell'agente OCIO: framework e pratica di miglioramento

_Fonti verificate il 28 settembre 2026. Le valutazioni nella matrice sono giudizi progettuali riferiti all'attuale monolite Python/FastAPI/PostgreSQL di OCIO, non benchmark dei framework._

## Decisione consigliata

Per il primo fascicolo completo userei **un solo agente coordinatore**, tool OCIO tipizzati e stato applicativo in PostgreSQL. Proverei per primo **OpenAI Agents SDK**, perché riusa la Responses API già adottata e aggiunge il loop, limiti di turni, tool, stato serializzabile, pause e test deterministici senza imporre un grafo. Il framework deve controllare l'esecuzione, non diventare il proprietario dei fatti aziendali, delle evidenze o del fascicolo.

Prima di adottarlo, farei uno spike comparativo piccolo:

1. **Agents SDK, candidato principale:** eseguire `evidenze -> ricerca normativa -> patch del fascicolo -> audit -> domande raggruppate`, con stato OCIO e trace locali.
2. **PydanticAI, sfidante:** implementare esattamente gli stessi tool e output per misurare il vantaggio reale di typing, portabilità tra provider, OpenTelemetry ed eval code-first.

Non prototiperei ora LangGraph né un motore durevole. LangGraph diventa il candidato giusto se il processo evolve in un grafo esplicito con molti rami, checkpoint ispezionabili e ripresa dentro i nodi. DBOS diventa il primo candidato per la durabilità infrastrutturale solo quando un singolo run deve sopravvivere a crash o deploy senza ripetere lavoro costoso. Nel frattempo, una pausa di ore o giorni tra una lista di domande e le risposte dell'RSPP è semplicemente **un run terminato con stato `WAITING_FOR_INPUT`**, seguito da un nuovo run: non richiede un processo vivo.

## Confini che il framework non deve possedere

Distinguere quattro stati evita gran parte del lock-in:

| Stato | Proprietario | Persistenza |
|---|---|---|
| Fatti, provenienza, evidenze e rilievi | dominio OCIO | tabelle applicative PostgreSQL |
| Template e revisioni del fascicolo | dominio OCIO | revisioni immutabili + patch/versioni |
| Cursore del run, turni e tool pendenti | harness | snapshot serializzabile, eliminabile dopo la retention |
| Conversazione | OCIO | messaggi/versioni espliciti; mai unica fonte dei fatti |

Una sessione o un checkpoint del framework non è il modello di dominio. Tutti i tool che producono effetti devono ricevere un `operation_id`, applicare optimistic locking alla revisione attesa ed essere idempotenti. La trace registra input/output e decisioni; il database applicativo decide cosa è vero e quale revisione è corrente.

Per il comportamento “come Codex”, il ciclo non deve chiedere appena incontra il primo vuoto. `request_information` accoda domande; l'agente continua con il lavoro indipendente; un audit finale deduplica e ordina le domande e solo allora produce `WAITING_FOR_INPUT`. Vanno inoltre fissati `max_turns`, budget di costo/tempo, numero massimo di retry per classe d'errore e una condizione di avanzamento per impedire loop.

## Confronto mirato

Legenda: **forte**, **adeguato**, **debole** indicano l'aderenza a OCIO oggi.

| Candidato | Stato e pausa/ripresa | Tool, retry e idempotenza | Trace/eval e privacy | Lock-in e peso operativo | Fit attuale |
|---|---|---|---|---|---|
| **Python + Responses API attuale** | Stato totalmente OCIO; pausa/ripresa e loop da costruire | Massimo controllo, ma dispatcher, limiti, recovery e test sono nostri | Trace già possedute; eval esistenti; minimo invio aggiuntivo | Lock-in API OpenAI ma nessuna astrazione runtime; peso minimo | **forte come baseline**, costoso da estendere |
| **OpenAI Agents SDK** | `RunState` è serializzabile e riprendibile; le sessioni conservano la storia. Non è durabilità crash-safe completa senza integrazione esterna | Function tool validati con Pydantic, guardrail, `max_turns`, approvazioni e test con modello scriptato. Idempotenza degli effetti resta nostra | Trace ricche abilitate per default; exporter sostituibile. Input/output sensibili e invio hosted vanno disabilitati o redatti | Migrazione minima dalla Responses API; supporto non-OpenAI esiste ma gli adapter hanno differenze e alcuni sono beta | **più forte per il primo slice** |
| **PydanticAI** | Storia serializzabile nel DB dell'app; deferred tools per approvazione/esecuzione esterna. Distingue chiaramente persistenza della conversazione e durabilità del run | Tool, dipendenze e output fortemente tipizzati; `TestModel`/`FunctionModel`. Retry/idempotenza degli effetti restano nostre | OpenTelemetry verso un backend scelto; Pydantic Evals valuta output e traiettoria ed è usabile anche indipendentemente dal runtime | Migliore portabilità provider; dipendenza nuova e superficie “Harness/capabilities” in rapida evoluzione | **forte sfidante** |
| **LangGraph** | Checkpoint per thread, interrupt indefiniti, ripresa e time travel; saver PostgreSQL disponibile | Retry per nodo. Alla ripresa il nodo dell'interrupt riparte dall'inizio: gli effetti prima dell'interrupt devono essere idempotenti | Stato e traiettoria molto osservabili; LangSmith è opzionale, ma retention/serializzazione dei checkpoint sono responsabilità nostra | Framework low-level e modello mentale aggiuntivo; rischia di duplicare stato dominio e stato grafo | **adeguato quando il grafo serve davvero** |
| **Temporal / DBOS / Restate** | Durabilità di processo, attese lunghe, retry e recovery dopo crash | Semantiche forti ma impongono confini deterministici tra workflow e I/O | Ottima storia operativa, ulteriore superficie di dati e retention | Temporal/Restate aggiungono runtime; DBOS può usare PostgreSQL ed è il più vicino allo stack | **prematuri oggi** |

L'Agents SDK documenta esplicitamente che la Responses API diretta è preferibile quando l'app vuole possedere loop, dispatch e stato, mentre l'SDK è pensato quando si vogliono delegare turni, tool, guardrail e sessioni.[^agents-overview] Le interruzioni HITL producono un `RunState` serializzabile; la ripresa deve usare in esclusiva la stessa sessione/backend e non deve essere eseguita concorrentemente sullo stesso snapshot.[^agents-hitl][^agents-run-state] Lo SDK offre inoltre un `ScriptedModel` senza chiamate esterne per verificare loop, argomenti, tool, retry e sessioni.[^agents-testing]

PydanticAI è realmente più neutrale sul provider: espone implementazioni native per più famiglie e profili di capacità, oltre a modelli procedurali per i test.[^pydantic-models][^pydantic-testing] La sua documentazione fa una distinzione utile: serializzare la storia in `jsonb` basta per riprendere una conversazione; la durabilità serve solo a sopravvivere a un crash a metà tool-call.[^pydantic-persistence] I deferred tools restituiscono richieste con call ID da approvare o completare in un run successivo, ma l'approvazione non sostituisce autenticazione e autorizzazione server-side.[^pydantic-deferred]

LangGraph offre esattamente checkpoint e interrupt durevoli; tuttavia, alla ripresa riesegue il nodo dall'inizio. La documentazione richiede pertanto side effect idempotenti o separati dall'interrupt.[^langgraph-interrupts] Il saver PostgreSQL è disponibile, con cifratura dei checkpoint e modalità di deserializzazione restrittiva; questo riduce l'infrastruttura aggiuntiva ma non elimina la necessità di policy di retention e accesso.[^langgraph-checkpoints]

## Spike: criteri di scelta, non demo “hello world”

Usare un solo caso fittizio congelato, con:

- template Markdown revisionato una volta a metà incarico;
- due note, due immagini con istruzioni diverse e un PDF;
- un fatto contraddittorio e una citazione normativa insufficiente;
- tre lacune, di cui una non bloccante;
- crash simulato dopo una patch e risposta successiva alle domande raggruppate.

Gli adapter dei tool devono essere identici nei due spike. Misurare:

1. righe e concetti specifici del framework necessari fuori dagli adapter;
2. capacità di non duplicare una patch dopo retry/ripresa;
3. serializzazione e migrazione dello stato dopo un cambio di versione;
4. facilità di ricostruire “perché questa frase è qui?” dalla provenienza;
5. test deterministici di tool selection, stop e resume senza modello reale;
6. trace redatta localmente, costo e token per run;
7. sostituzione del modello senza modificare i contratti OCIO.

Promuovere Agents SDK se rende il loop e i test sensibilmente più piccoli senza duplicare il dominio. Promuovere PydanticAI se la portabilità e l'OTel/eval code-first producono un vantaggio concreto sufficiente a giustificare la migrazione. Mantenere il runtime esplicito se nessuno dei due riduce complessità netta.

## Miglioramento continuo: cosa copiare dall'idea SylloTips

Il sito SylloTips descrive un ciclo **Detect -> Route -> Review -> Write back**, con attribuzione dei fallimenti, task indirizzati agli esperti, memoria governata, gestione dei conflitti e backtesting.[^syllotips] È un buon modello di processo, non una prova tecnica: architettura, metriche percentuali e benefici riportati sono affermazioni commerciali del fornitore e non sono stati verificati indipendentemente. OCIO non deve dipendere dal prodotto.

La versione adatta a OCIO è:

```text
trace locale + correzione RSPP
    -> rilevazione e classificazione del fallimento
    -> coda di revisione con evidenza minima necessaria
    -> decisione dell'esperto: scarta / correggi / promuovi
    -> destinazione governata
    -> replay ed eval prima del rilascio
```

“Write back” non significa inserire automaticamente la correzione nel prompt o nel corpus normativo. Ogni contributo approvato ha una destinazione esplicita:

- **stato del singolo incarico**, se vale solo per quell'azienda;
- **caso di regressione anonimizzato**, se rivela un errore generalizzabile;
- **regola operativa/playbook**, con ambito, autore, data, revisione e scadenza;
- **fonte normativa**, solo attraverso la pipeline autorevole di acquisizione/versionamento, mai come memoria informale.

La priorità non è un ottimizzatore automatico dei prompt. È una piccola “inbox qualità” che raccoglie correzioni già naturali (`fatto rifiutato`, `patch modificata`, `domanda superflua`, `citazione errata`), le raggruppa per causa e permette all'RSPP di promuovere solo gli esempi utili. Dataset, rubriche, risultati e versioni restano file/tabelle OCIO; un runner come Pydantic Evals può essere adottato in seguito senza cedere la proprietà dei dati. Pydantic Evals è code-first, serializzabile e valuta sia output sia traiettoria, mentre gli evaluator basati su span richiedono Logfire: per questo userei dapprima evaluator OCIO deterministici e solo opzionalmente quell'integrazione.[^pydantic-evals]

## Non raccomandazioni esplicite

- **Niente auto-modifica in produzione** di prompt, tool, template o memoria dopo un feedback: ogni promozione passa da revisione, eval offline, shadow/canary e rollback, come dettagliato in [Sistema di miglioramento dell'agente](agent-improvement-system.md).
- **Niente multi-agent iniziale:** extraction, drafting e audit sono responsabilità o fasi del singolo coordinatore; si separano solo quando eval e costi dimostrano un vantaggio.
- **Niente LangSmith/Logfire/OpenAI hosted tracing come fonte primaria:** foto, documenti e dati aziendali richiedono trace locali minimizzate. Nell'Agents SDK il tracing è attivo per default, può includere dati sensibili e non è disponibile con ZDR; va sostituito con un exporter locale o disabilitato finché la policy non è definita.[^agents-tracing]
- **Niente Temporal ora:** risolve affidabilità e recovery distribuito che il primo vertical slice non ha ancora dimostrato di richiedere.[^temporal-ai]
- **Niente Restate ora:** il runtime separato e i suoi workflow interattivi sono utili, ma ampliano inutilmente il perimetro operativo iniziale.[^restate-services]
- **Niente DBOS ora, ma rivalutarlo per primo:** è incrementale, Python e PostgreSQL; diventa utile quando servono recovery a metà run, code durevoli o elaborazioni documentali lunghe. I suoi step sono at-least-once finché non completati, quindi gli effetti esterni devono comunque essere progettati con idempotenza.[^dbos-integration][^dbos-guarantees]
- **Niente memoria globale di “risposte approvate” senza scope:** una soluzione valida per una specifica azienda, mansione, data o revisione normativa non può diventare automaticamente una regola generale.

## Sequenza pratica

1. Congelare contratti dominio e tool (`inspect_evidence`, `knowledge_search`, `update_dossier`, `audit_dossier`, `request_information`) indipendenti dal framework.
2. Implementare idempotency key, revision check e audit log prima del loop autonomo.
3. Eseguire gli spike Agents SDK/PydanticAI sullo stesso fixture e pubblicare il confronto come ADR.
4. Estendere la suite esistente con replay del fixture, invarianti e almeno tre run reali per candidato.
5. Costruire la “inbox qualità” e il passaggio feedback -> caso candidato -> gold set; non serve una piattaforma esterna.
6. Aggiungere durabilità infrastrutturale solo dopo aver osservato run abbastanza lunghi o costosi da rendere inaccettabile il riavvio da un checkpoint applicativo.

## Fonti

[^agents-overview]: OpenAI, [Agents SDK overview e confronto con Responses API](https://openai.github.io/openai-agents-python/).
[^agents-hitl]: OpenAI, [Agents SDK — Human-in-the-loop](https://openai.github.io/openai-agents-python/human_in_the_loop/).
[^agents-run-state]: OpenAI, [Agents SDK — RunState](https://openai.github.io/openai-agents-python/ref/run_state/).
[^agents-testing]: OpenAI, [Agents SDK — Testing](https://openai.github.io/openai-agents-python/testing/).
[^agents-tracing]: OpenAI, [Agents SDK — Tracing](https://openai.github.io/openai-agents-python/tracing/).
[^pydantic-models]: Pydantic, [PydanticAI — Model providers](https://pydantic.dev/docs/ai/models/overview/).
[^pydantic-testing]: Pydantic, [PydanticAI — Unit testing](https://pydantic.dev/docs/ai/guides/testing/).
[^pydantic-persistence]: Pydantic, [PydanticAI — Persistence](https://pydantic.dev/docs/ai/core-concepts/persistence/).
[^pydantic-deferred]: Pydantic, [PydanticAI — Deferred tools e HITL](https://pydantic.dev/docs/ai/tools-toolsets/deferred-tools/).
[^pydantic-evals]: Pydantic, [Pydantic Evals](https://pydantic.dev/docs/ai/evals/evals/) e [span-based evaluation](https://github.com/pydantic/pydantic-ai/blob/main/docs/evals/evaluators/span-based.md).
[^langgraph-interrupts]: LangChain, [LangGraph — Interrupts](https://langchain-ai.github.io/langgraph/concepts/breakpoints/).
[^langgraph-checkpoints]: LangChain, [LangGraph — Checkpointing](https://langchain-ai.github.io/langgraph/reference/checkpoints/) e [PostgreSQL saver](https://github.com/langchain-ai/langgraph/blob/main/libs/checkpoint-postgres/README.md).
[^temporal-ai]: Temporal, [Durable AI](https://docs.temporal.io/ai).
[^restate-services]: Restate, [Services e workflow](https://docs.restate.dev/concepts/services/).
[^dbos-integration]: DBOS, [Integrare DBOS in un'applicazione](https://docs.dbos.dev/python/integrating-dbos).
[^dbos-guarantees]: DBOS, [Workflow e garanzie di esecuzione](https://docs.dbos.dev/python/tutorials/workflow-tutorial).
[^syllotips]: SylloTips, [Continuous improvement for AI agents](https://syllotips.com/). Fonte primaria del fornitore; le capacità e metriche riportate sono dichiarazioni commerciali.
