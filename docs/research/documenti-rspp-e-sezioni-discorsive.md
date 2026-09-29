# Documenti RSPP e sezioni discorsive

Ricerca del 29 settembre 2026 per il prototipo dell’issue #25. Gli esempi
riguardano soprattutto il DVR: non definiscono uno schema universale per il
fascicolo di OCIO. Sono riferimenti di struttura editoriale, non una verifica
normativa di completezza o aggiornamento dei documenti esaminati.

## Evidenze

- Il Ministero descrive il DVR come una relazione sulla valutazione dei rischi
  e sui criteri adottati, comprendente misure, procedure e ruoli. Il contenuto
  non è limitato all’anagrafica.
  [Ministero del Lavoro — Salute e sicurezza](https://www.lavoro.gov.it/en/node/5658).
- La procedura standardizzata distingue descrizione di azienda, ciclo e mansioni,
  identificazione dei pericoli, valutazione e misure, programma di miglioramento.
  Il modulo 1.2 descrive le fasi e le associa ad aree, attrezzature, materiali e
  mansioni; sono previsti più moduli per cicli diversi. Le istruzioni ammettono
  colonne aggiuntive e una planimetria allegata. È un esempio di contenuto misto,
  descrittivo e tabellare, con documentazione di supporto.
  [Procedura standardizzata, PDF pp. 6–11, 13–14](https://www.lavoro.gov.it/temi-e-priorita/salute-e-sicurezza/focus-on/commissione-consultiva-permanente/Documents/Procedura-standardizzata.pdf).
- Il DVR dell’I.P.S.E.O.A. “F. Martini”, pubblicato dall’istituto e redatto da un
  consulente, conta 186 pagine nella revisione 2021. Comprende anagrafica,
  descrizione delle attività, relazione introduttiva, metodologia, valutazioni
  per mansione e allegati. La relazione discorsiva illustra il metodo e rimanda
  a schede e documenti specifici; altre parti contengono elenchi di macchinari
  e schede delle attività.
  [DVR Via Garibaldi, PDF pp. 8–17, 123–128, 136](https://www.alberghieromontecatini.edu.it/attachments/article/86/1558_20210923-DVR_VIA%20GARIBALDI.pdf).
- Il DVR del Liceo “Ciardo Pellegrino” presenta scopi e contesto in prosa,
  descrive una metodologia basata su segnalazioni e rilevazioni con il SPP,
  quindi alterna testo, matrici probabilità/danno e conclusioni legate ai
  sopralluoghi. Dimostra che la relazione e gli strumenti tabellari convivono
  nello stesso elaborato.
  [DVR, PDF pp. 7–13, 18–21, 37](https://www.liceociardopellegrinolecce.edu.it/sites/default/files/page/2020/valutazione_dei_rischi_ciardo_0.pdf).

## Scelte di prodotto

Le seguenti sono scelte per OCIO, informate dagli esempi e dalla conversazione
con l’utente; non prescrizioni delle fonti.

- Conservare l’indice del modello adottato e offrire un editor ampio per sezione.
  Supportare paragrafi, sottotitoli, elenchi e tabelle; non obbligare ogni
  sezione a una sequenza di campi brevi.
- Usare campi per l’anagrafica e tabelle dove aiutano a confrontare elementi
  ripetuti. Attività, ambienti, criteri e misure richiedono anche testo esteso.
- Tenere appunti, foto e documenti come materiale consultabile a lato e
  collegabile al testo. Il fascicolo può raccogliere più elaborati e allegati:
  non coincide necessariamente con un singolo DVR.
- La bozza conserva incertezze e informazioni mancanti senza inventare dettagli.
  L’RSPP rivede e corregge il fascicolo; niente conferme obbligatorie per dato.
- Le generazioni successive devono rispettare testo manuale e revisioni.
  La checklist del sopralluogo è esclusa per decisione di prodotto.

La #25 riguarda l’editing; la #26 acquisizione e analisi del materiale; la #27
compilazione assistita; la #28 revisione complessiva ed esportazione. Il prototipo A approvato è conservato sul ramo
`prototype/issue-25-document-editor`. La #25 adotta un editor Tiptap per sezioni
con persistenza Markdown; acquisizione degli allegati e generazione restano nelle
issue successive.
