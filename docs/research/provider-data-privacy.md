# Privacy dei provider LLM per OCIO

_Verifica delle fonti ufficiali al 20 settembre 2026. Nota tecnica, non parere legale._

## Decisione sintetica

Per l'alpha italiana, **OpenAI API è oggi la scelta documentabile più prudente tra i due provider**, purché il progetto usi soltanto endpoint e configurazioni compatibili con il livello di conservazione scelto. DeepSeek hosted API non va usata per dati personali di utenti italiani: oltre a garanzie pubbliche meno precise, il Garante ha ordinato la **limitazione definitiva** del trattamento dei dati personali di interessati in Italia nell'ambito del servizio DeepSeek.[^garante]

Questo non rende automaticamente sicuro inviare qualsiasi dato a OpenAI. La prima alpha dovrebbe comunque minimizzare/redigere i dati, evitare dati sanitari e identificativi, separare log applicativi e contenuto, definire cancellazione e consenso, e verificare DPA/configurazione prima di aprire il servizio a casi reali.

## Confronto

| Tema | OpenAI API | DeepSeek hosted API |
|---|---|---|
| Addestramento | Input e output API non sono usati per addestrare/migliorare i modelli per default; la condivisione è opt-in.[^oai-business][^oai-controls] | La policy include gli input tra i dati usabili per addestrare/migliorare la tecnologia; è previsto un opt-out. Una piccola parte dei dati di training di ottimizzazione può derivare dagli input utente.[^ds-privacy][^ds-model] |
| Retention standard | I log anti-abuso, che possono contenere prompt e risposte, sono conservati fino a 30 giorni per default, salvo obblighi legali; alcune API mantengono anche stato applicativo con tempi propri.[^oai-controls] | Non è pubblicato un termine fisso specifico per prompt/log API. La policy conserva dati finché necessari e indica che account, input e pagamenti possono restare finché esiste l'account, oltre ad altre esigenze legali o commerciali.[^ds-privacy] |
| Zero retention | ZDR e Modified Abuse Monitoring esistono per clienti idonei, previa approvazione e requisiti aggiuntivi. Non tutti gli endpoint/funzionalità sono compatibili.[^oai-controls] | Nelle fonti pubbliche esaminate non è documentato un programma ZDR o retention configurabile. Il fatto che la Responses API non conservi oggetti conversazione non prova l'assenza di log o altri trattamenti disciplinati dalla policy.[^ds-responses][^ds-privacy] |
| Residenza/elaborazione | Per organizzazioni idonee, i progetti Europe possono avere storage e processing regionali nell'EEA/Svizzera, usando `eu.api.openai.com`; servono controlli anti-abuso approvati e un emendamento ZDR. I system data e alcuni scenari restano esclusi.[^oai-controls] | La policy dichiara raccolta, trattamento e conservazione diretti nella Repubblica Popolare Cinese; non documenta una regione UE.[^ds-privacy] |
| Contratto e trasferimenti | Il DPA qualifica OpenAI come processor, prevede istruzioni del cliente e SCC/decisioni di adeguatezza per trasferimenti di dati EEA fuori area.[^oai-dpa] | Le condizioni Open Platform pongono sul developer gli obblighi per i dati degli utenti finali; la privacy policy dice che tali trattamenti nelle app downstream non sono coperti dalla stessa policy. Nelle fonti pubbliche esaminate non emerge un DPA/SCC API equivalente.[^ds-platform][^ds-privacy] |
| Controlli enterprise | Sono documentati controlli per progetto/organizzazione, residency, ZDR/MAM ed Enterprise Key Management; disponibilità e compatibilità dipendono dal contratto e dall'endpoint.[^oai-controls] | È documentato `user_id` per isolamento della KV cache, con istruzione di non inserirvi dati personali; non sono emersi controlli pubblici equivalenti a residency/ZDR/EKM.[^ds-isolation] |

## Implicazioni per OCIO

1. **DeepSeek hosted: stop per dati personali italiani.** Il provvedimento del Garante dichiara illecito il trattamento esaminato e ordina la limitazione definitiva, con effetto immediato, dei trattamenti relativi a interessati in Italia.[^garante] La policy DeepSeek aggiunge che il servizio non è progettato per dati sensibili e chiede di non fornirli.[^ds-privacy]
2. **Il trasferimento in Cina richiederebbe comunque un'analisi dedicata.** La Cina non compare tra i paesi coperti da decisione di adeguatezza UE; i trasferimenti verso paesi terzi richiedono salvaguardie specifiche.[^adequacy][^transfers]
3. **OpenAI API è “no training by default”, non “nessun dato conservato”.** Senza ZDR, i log anti-abuso possono trattenere contenuto fino a 30 giorni; inoltre ogni endpoint ha regole proprie.[^oai-controls]
4. **Per l'alpha:** accettare soltanto casi fittizi o redatti; bloccare/avvisare su nomi, dati sanitari, infortuni identificabili e documenti aziendali reali; inviare al modello solo i chunk strettamente necessari; non usare servizi consumer per le evaluation contenenti dati reali.
5. **Prima dei pilot reali:** sottoscrivere e verificare il DPA, decidere se richiedere ZDR + regione Europe, costruire una matrice endpoint/funzionalità/retention, definire tempi di cancellazione locali e valutare con un consulente privacy se serva una DPIA. La configurazione scelta va testata: ZDR non copre automaticamente tutte le funzionalità.[^oai-controls][^oai-dpa]

## Punto aperto

Il provider non dovrebbe essere fissato nell'architettura: usare un adapter e una policy per modello/endpoint. DeepSeek può restare candidato per esecuzione **self-hosted** futura, che è una decisione diversa dall'uso della sua API ospitata e richiede una valutazione separata di licenza, infrastruttura e sicurezza.

## Fonti ufficiali

[^garante]: Garante per la protezione dei dati personali, [Provvedimento del 30 gennaio 2025, doc. web 10098477](https://www.garanteprivacy.it/home/docweb/-/docweb-display/docweb/10098477).
[^adequacy]: Commissione europea, [Adequacy decisions](https://commission.europa.eu/law/law-topic/data-protection/international-dimension-data-protection/adequacy-decisions_en).
[^transfers]: Commissione europea, [Rules on international data transfers](https://commission.europa.eu/law/law-topic/data-protection/international-dimension-data-protection/rules-international-data-transfers_en).
[^oai-business]: OpenAI, [Business data privacy, security, and compliance](https://openai.com/business-data/).
[^oai-controls]: OpenAI API, [Data controls in the OpenAI platform](https://platform.openai.com/docs/models/default-usage-policies-by-endpoint).
[^oai-dpa]: OpenAI, [Data Processing Addendum](https://cdn.openai.com/pdf/openai-data-processing-addendum.pdf).
[^ds-privacy]: DeepSeek, [Privacy Policy, aggiornata il 10 febbraio 2026](https://cdn.deepseek.com/policies/en-US/deepseek-privacy-policy.html).
[^ds-model]: DeepSeek, [Model Mechanism and Training Methods](https://cdn.deepseek.com/policies/en-US/model-algorithm-disclosure.html).
[^ds-platform]: DeepSeek, [Open Platform Terms of Service](https://cdn.deepseek.com/policies/en-US/deepseek-open-platform-terms-of-service.html).
[^ds-responses]: DeepSeek API, [Responses API](https://api-docs.deepseek.com/api/create-response/).
[^ds-isolation]: DeepSeek API, [Rate Limit & Isolation](https://api-docs.deepseek.com/quick_start/rate_limit/).
