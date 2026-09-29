# Sistema di miglioramento dell'agente OCIO

_Verifica delle fonti: 28 settembre 2026. Ambito: agente multimodale che raccoglie evidenze e mantiene un fascicolo di sicurezza Markdown configurabile._

## Decisione consigliata

Non permettere all'agente di modificare autonomamente prompt, tool o regole in produzione. Il ciclo robusto è controllato:

```text
uso reale -> trace + correzioni RSPP -> casi candidati
         -> revisione e anonimizzazione -> dataset versionato
         -> eval offline -> shadow -> canary -> promozione o rollback
```

La prima infrastruttura da costruire non è il fine-tuning, ma:

1. trace applicative riproducibili e rispettose della privacy;
2. feedback granulare sulle estrazioni e sulle sezioni del fascicolo;
3. una tassonomia degli errori;
4. eval separate per estrazione, tool, norme, redazione e comportamento conversazionale;
5. versionamento completo della configurazione che ha prodotto ogni risultato.

OpenAI consiglia eval specifiche per il compito, logging fin dall'inizio, calibrazione con giudizi umani e valutazione continua a ogni cambiamento.[^openai-best-practices] Per gli agenti, le trace rendono osservabili chiamate al modello, tool e guardrail; i dataset servono poi a confrontare versioni in modo ripetibile.[^openai-agent-evals] Anthropic sottolinea inoltre che una prova singola non basta per un sistema non deterministico e propone più trial e più grader per lo stesso caso.[^anthropic-agent-evals]

## Trace e replay posseduti da OCIO

Una `agent_run` deve essere l'unità riproducibile e contenere almeno:

- input dell'operatore e riferimenti alle evidenze, non necessariamente i file grezzi;
- snapshot iniziale dello stato del caso e revisione dello schema del fascicolo;
- piano, turni, tool scelti, argomenti, risultati ed errori;
- osservazioni estratte con pagina, regione dell'immagine o passaggio di origine;
- query e risultati normativi con fingerprint del corpus;
- patch applicate al fascicolo e diff finale;
- domande accodate e motivo per cui bloccano o migliorano il lavoro;
- esito, latenza, costo e feedback successivo;
- versioni di prompt, modelli, tool, orchestratore, schema di output ed evaluator.

Il replay deve avere due modalità:

- **deterministica:** riusa risultati salvati di OCR, documenti, web e retrieval per isolare il comportamento dell'agente;
- **integrazione:** richiama i sistemi reali per rilevare cambiamenti di provider, ricerca e corpus.

Le trace vanno trasformate in casi di eval solo dopo revisione. Un errore di produzione diventa un test di regressione; un caso riuscito può diventare una baseline, ma senza imporre all'agente una sola traiettoria valida. Per agenti capaci di percorsi diversi è più affidabile giudicare il risultato e alcuni vincoli di processo che una sequenza esatta di chiamate.[^anthropic-research-system]

## Eval a strati

| Strato | Cosa misurare | Grader preferito |
|---|---|---|
| Contratti deterministici | JSON valido, tipi, permessi, limiti di turni, idempotenza, patch applicabile | test di codice, sempre bloccanti |
| Scelta dei tool | tool necessari/proibiti, argomenti corretti, chiamate inutili, recupero dagli errori | regole sulla trace + rubrica umana sui casi ambigui |
| Estrazione da testo, immagini e documenti | precisione/recall dei fatti, provenienza, confidenza, astensione e rispetto dell'istruzione dell'utente | gold set RSPP + confronto strutturato |
| Stato del caso | nessuna sovrascrittura di fatti confermati, conflitti esposti, stato `proposto/confermato/da verificare` corretto | invarianti deterministiche |
| Ricerca normativa | recall delle evidenze, autorità e vigenza della fonte, claim supportate, citazioni corrette, astensione | metriche retrieval + claim-to-citation + campione esperto |
| Modifica del fascicolo | sezioni pertinenti compilate, istruzioni dello schema rispettate, provenienza conservata, modifiche manuali non perse, nessun dato inventato | controlli strutturali + confronto pairwise/esperto |
| Chiarimenti raggruppati | lavoro utile completato prima dello stop, domande non deducibili, non duplicate, raggruppate e ordinate per impatto | metriche sulla trace + rubrica RSPP |
| End-to-end | errori critici, omissioni, accettazione delle proposte, entità delle correzioni, tempo risparmiato e utilità percepita | RSPP su caso completo |

Per contenuti aperti conviene combinare controlli deterministici, grader LLM e giudizio esperto: groundedness, copertura e qualità delle fonti sono dimensioni distinte, e i grader automatici devono essere ricalibrati spesso sul giudizio umano.[^anthropic-agent-evals] Gli LLM risultano più affidabili nel confronto pairwise o nella classificazione contro criteri precisi che nella generazione di un voto generico.[^openai-best-practices]

### Immagini guidate dalla descrizione

La descrizione dell'operatore deve essere un input tipizzato, non solo testo decorativo:

```json
{
  "evidence_id": "foto-17",
  "instruction": "estrai marca, modello e presenza della marcatura CE",
  "expected_fields": ["marca", "modello", "marcatura_ce"]
}
```

Le eval devono verificare due errori opposti:

- l'agente ignora la richiesta e produce una descrizione generica della foto;
- l'agente oltrepassa la richiesta e deduce conformità o assenza di rischi non osservabili.

Nel gold set, ogni valore deve includere esito (`osservato`, `non leggibile`, `non determinabile`) e localizzazione nell'immagine. Servono varianti difficili: targhe inclinate, testo parzialmente coperto, più macchine, foto irrilevante e descrizione ambigua. Le piattaforme di eval moderne supportano valutazioni multimodali anche sugli allegati, ma OCIO può mantenere gli stessi contratti con un runner proprio.[^langsmith-multimodal]

### Schemi dinamici del fascicolo

Lo schema Markdown dell'utente è configurazione versionata:

- `template_id` identifica il modello logico;
- ogni modifica crea una `template_revision` immutabile;
- ogni esecuzione salva la revisione usata;
- una nuova revisione produce una proposta di migrazione con diff, mai una riscrittura silenziosa;
- fonti, fatti e allegati restano separati dal Markdown, così il fascicolo può essere rigenerato senza perdere evidenze;
- testo approvato o scritto dall'operatore è protetto e viene spostato o riscritto solo con una proposta visibile.

Le eval hanno quindi due livelli:

1. **invarianti universali:** niente invenzioni, provenienza, citazioni, rispetto dei contenuti protetti, domande raggruppate;
2. **contratto della revisione:** sezioni obbligatorie, istruzioni di compilazione, elementi ammessi e criteri di completezza definiti dal template.

Il dataset deve includere più template, modifiche a metà incarico, rinomina e riordino di sezioni, aggiunta di una sezione obbligatoria e rimozione di una sezione. Non si misura la somiglianza con un unico Markdown ideale: si misura il rispetto del contratto e l'utilità del risultato.

## Feedback che produce dati utili

Il solo pollice su/giù non identifica il componente difettoso. Conservare azioni già naturali nel lavoro dell'RSPP:

- conferma, correzione o rifiuto di un fatto estratto;
- accettazione, modifica o ripristino di una patch del fascicolo;
- risposta “era già negli allegati” a una domanda superflua;
- segnalazione di citazione errata, omissione, invenzione o tono inadeguato;
- giudizio finale `utilizzabile`, `utilizzabile con modifiche`, `da rifare`.

Ogni segnalazione dovrebbe avere un motivo breve della tassonomia seguente e puntare allo span/tool/patch responsabile. Il passaggio da feedback a gold set richiede revisione di un esperto: una correzione dell'utente è evidenza preziosa, non automaticamente verità.

## Tassonomia minima dei fallimenti

1. `INPUT_MISUNDERSTOOD`: intento o istruzione sull'allegato fraintesi.
2. `EXTRACTION_MISSED` / `EXTRACTION_INVENTED`: fatto omesso o non osservabile.
3. `PROVENANCE_LOST`: fatto corretto senza collegamento verificabile alla fonte.
4. `STATE_CONFLICT`: correzione ignorata o dato confermato sovrascritto.
5. `TOOL_SELECTION` / `TOOL_ARGUMENT`: tool o argomento inappropriato.
6. `GROUNDING_MISSING` / `CITATION_WRONG`: claim normativa non sostenuta.
7. `TEMPLATE_VIOLATION`: schema o istruzione di sezione non rispettati.
8. `MANUAL_EDIT_LOST`: contenuto approvato dall'operatore alterato senza consenso.
9. `PREMATURE_STOP`: l'agente chiede prima di esaurire il lavoro possibile.
10. `QUESTION_QUALITY`: domanda deducibile, duplicata, vaga o non raggruppata.
11. `CRITICAL_OMISSION`: mancanza che può rendere il fascicolo fuorviante.
12. `COST_LATENCY_LOOP`: lavoro ripetuto, loop o budget eccessivo.

La tassonomia va mantenuta corta e stabile; dettagli ulteriori possono stare in tag secondari.

## Dataset e gate di regressione

Costruire tre insiemi distinti:

- **fixture sintetiche/fittizie:** numerose, economiche, adatte a CI e casi avversariali;
- **gold set RSPP:** piccolo, accuratamente annotato, con immagini, documenti e fascicoli attesi;
- **replay di produzione anonimizzati:** distribuzione reale, con base giuridica/consenso e revisione prima dell'uso.

Tenere separato un test set che non viene usato per modificare prompt o tool. Per i casi non deterministici eseguire più trial e riportare distribuzione e intervallo, non soltanto una media.[^anthropic-agent-evals]

Gate iniziali consigliati:

- zero violazioni di permessi, perdita di modifiche manuali e invenzioni critiche nel gold set;
- nessuna regressione significativa per estrazione, grounding e completezza rispetto alla versione in produzione;
- miglioramento dichiarato su una categoria senza peggioramento oltre soglia nelle altre;
- budget massimo di turni, costo e latenza;
- revisione manuale di tutti i delta sui casi ad alto rischio.

Le soglie numeriche vanno definite dopo una baseline reale. Benchmark offline, regression test, backtesting di trace storiche e monitoraggio online hanno funzioni differenti e complementari.[^langsmith-evaluation-types]

## Rilascio di una nuova versione

1. **Offline:** replay del dataset con dipendenze registrate; confronto per categoria e caso.
2. **Shadow:** la candidata elabora una copia degli input reali ma non modifica lo stato né mostra risultati all'utente; confrontare patch, domande, costo e fallimenti.
3. **Canary:** abilitarla per pochi incarichi o operatori consenzienti, sempre con rollback alla versione precedente.
4. **Promozione:** aumentare gradualmente il traffico solo se gate offline e segnali online restano sani.

Non usare un unico punteggio aggregato per la promozione: può nascondere un errore critico dietro miglioramenti di stile. Conservare dashboard e gate per strato.

## Privacy delle trace

Fotografie, documenti aziendali e dati sanitari possono comparire sia negli input del modello sia nei risultati dei tool. Le trace devono quindi essere un prodotto con policy propria:

- tracciare per default ID, hash, metadati, decisioni e output strutturati minimizzati; non duplicare file grezzi o immagini in base64;
- tenere gli allegati nel deposito del caso con accesso più ristretto, e risolverli solo quando una revisione autorizzata lo richiede;
- pseudonimizzare azienda e persone nei dataset e rimuovere dati non necessari;
- separare retention operativa, retention delle trace e dataset di eval; supportare cancellazione e revoca;
- limitare gli accessi e registrare chi promuove un caso reale nel dataset;
- usare casi fittizi o redatti nei servizi esterni di evaluation finché non sono state definite base giuridica, DPA e configurazione del provider.

L'Agents SDK OpenAI traccia per default generazioni e input/output dei tool; `trace_include_sensitive_data` può escluderli, ma il default documentato è `True`. Inoltre il tracing ospitato non è disponibile con Zero Data Retention. Se la redazione è un requisito, OpenAI raccomanda un exporter posseduto dall'applicazione che scarti l'intero batch se la redazione fallisce.[^openai-tracing] Per OCIO la scelta prudente è quindi una trace locale applicativa come fonte primaria, con eventuale export esterno esplicito e redatto. Questo completa, senza sostituire, l'analisi privacy già raccolta in [Privacy dei provider LLM](provider-data-privacy.md).

## Versioni da registrare sempre

```text
agent_version          commit/release dell'orchestratore
prompt_versions        planner, extraction, audit, drafting, questions
model_versions         provider e snapshot/modello effettivo
tool_contract_versions nomi, descrizioni, JSON Schema e implementazione
template_revision      schema fascicolo e istruzioni dell'utente
corpus_fingerprint     norme e metadati di vigenza
evidence_parser        OCR/parser/versione vision
evaluator_versions     codice, rubriche e modello giudice
privacy_profile        cosa è stato conservato/esportato
```

OCIO registra già versioni di prompt, schema e fingerprint del retrieval: conviene estendere questo approccio invece di introdurre subito una piattaforma esterna.

## Sequenza pratica

1. Definire contratti di trace e tassonomia prima del nuovo agent loop.
2. Preparare 15–30 incarichi fittizi piccoli, inclusi 5–10 casi immagine guidati dalla descrizione.
3. Far annotare a un RSPP fatti, provenienza, sezioni attese e domande veramente necessarie.
4. Implementare evaluator deterministici; aggiungere grader LLM solo per forma, copertura e confronto pairwise.
5. Creare UI di conferma/correzione per fatto e di diff per sezione: è contemporaneamente controllo operativo e raccolta feedback.
6. Eseguire il benchmark a ogni modifica di prompt, modello, tool o template compiler.
7. Aggiungere replay da trace, shadow e canary solo quando esiste un primo pilot reale.
8. Valutare ottimizzazione automatica o fine-tuning soltanto dopo aver accumulato un gold set stabile; l'ottimizzazione senza metrica affidabile amplifica il rumore.

Questa infrastruttura non richiede di scegliere ora Agents SDK, LangGraph o LangSmith. I contratti di dominio, i dataset e i gate devono restare posseduti da OCIO; un framework può implementare tracing o runner dietro adapter. L'Agents SDK offre anche utility deterministiche per testare tool execution, guardrail, retry e sessioni senza chiamare modelli reali, utile se verrà adottato.[^openai-agents-testing]

Non costruire il sistema intorno alla piattaforma OpenAI Evals legacy: la documentazione ne annuncia il passaggio in sola lettura il 31 ottobre 2026 e la chiusura il 30 novembre 2026.[^openai-deprecations] Le API e dashboard esterne possono essere adapter sostituibili; casi, rubriche, risultati e confronti restano dati OCIO.

## Fonti

[^openai-best-practices]: OpenAI, [Evaluation best practices](https://developers.openai.com/api/docs/guides/evaluation-best-practices).
[^openai-agent-evals]: OpenAI, [Evaluate agent workflows](https://developers.openai.com/api/docs/guides/agent-evals) e [Trace grading](https://developers.openai.com/api/docs/guides/trace-grading).
[^openai-tracing]: OpenAI Agents SDK, [Tracing](https://openai.github.io/openai-agents-python/tracing/).
[^openai-agents-testing]: OpenAI Agents SDK, [Testing](https://openai.github.io/openai-agents-python/testing/).
[^openai-deprecations]: OpenAI, [Deprecations](https://developers.openai.com/api/docs/deprecations).
[^anthropic-agent-evals]: Anthropic, [Demystifying evals for AI agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents).
[^anthropic-research-system]: Anthropic, [How we built our multi-agent research system](https://www.anthropic.com/engineering/multi-agent-research-system).
[^langsmith-evaluation-types]: LangChain, [LangSmith evaluation types](https://docs.langchain.com/langsmith/evaluation-types).
[^langsmith-multimodal]: LangChain, [Set up LLM-as-a-judge online evaluators](https://docs.langchain.com/langsmith/online-evaluations-llm-as-judge).
