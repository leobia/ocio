# Generazione del silver set OCIO v1

Sei un curatore di un dataset per valutare un motore di ricerca nella normativa
italiana sulla sicurezza sul lavoro.

Il file allegato contiene il corpus disponibile. Ogni riga riporta
`document_code`, `partition_identifier`, `document_title`, `partition_type`,
`rubric` e `partition_text`.

Genera 20 casi con questa distribuzione:

- 8 domande dirette (`grounded`);
- 5 parafrasi in linguaggio naturale (`paraphrase`);
- 5 piccoli casi aziendali inventati (`fictional_case`);
- 2 domande non rispondibili dal corpus (`hard_negative`).

Regole:

1. Usa esclusivamente il corpus allegato.
2. Non inventare documenti o identificatori.
3. Copia `document_code` e `partition_identifier` esattamente dal corpus.
4. Per ogni domanda rispondibile indica tutte e sole le partizioni necessarie,
   preferendo quelle più specifiche.
5. La domanda deve essere comprensibile senza vedere il testo sorgente.
6. Le parafrasi non devono copiare le parole principali del passaggio.
7. I casi aziendali devono essere completamente fittizi e non devono contenere
   nomi di persone, aziende reali, dati sanitari o incidenti identificabili.
8. Un `hard_negative` deve essere pertinente alla sicurezza sul lavoro ma non
   rispondibile dal corpus completo; `expected_evidence` deve essere vuoto.
9. Non generare la risposta alla domanda.
10. Evita casi duplicati o quasi duplicati.
11. Controlla che ogni riferimento positivo esista nel file prima dell’output.

Restituisci esclusivamente JSONL: un oggetto JSON completo per riga, senza
Markdown, commenti o testo introduttivo.

Formato:

```json
{"schema_version":1,"id":"silver-0001","kind":"grounded","query":"...","difficulty":"easy","answerable":true,"expected_evidence":[{"document_code":"...","partition_identifier":"..."}]}
```

Valori ammessi:

- `kind`: `grounded`, `paraphrase`, `fictional_case`, `hard_negative`;
- `difficulty`: `easy`, `medium`, `hard`;
- `answerable`: `true` per i primi tre tipi, `false` per `hard_negative`.

Gli ID partono da `silver-0001` e sono progressivi.
