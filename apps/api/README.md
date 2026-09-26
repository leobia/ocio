# OCIO API

Backend Python per OCIO.

## Importazione e normalizzazione del corpus

Le fonti vengono lette soltanto dai file locali verificati tramite SHA-256 nel
registro `ocio_sources.yaml`. Esegui i comandi in quest'ordine, con il database
migrato:

```sh
ocio importa-corpus
ocio normalizza-corpus
```

`normalizza-corpus` aggiorna in modo idempotente i documenti e le loro partizioni
correnti. Non modifica il flag `abilitato_per_agente`. Ogni partizione conserva
l'acquisizione di origine; per i PDF il localizzatore include pagina e riquadro.

AKN usa la gerarchia XML e gli eId disponibili. HTML Gazzetta estrae il solo testo
dell'atto, ricostruendo articoli e allegati nell'ordine del registro. PDF usa
coordinate, stile tipografico e celle ricostruite per riconoscere sezioni, articoli,
elenchi e tabelle; le FAQ sono divise in categoria, quesito e risposta. Il PDF
coordinato dei D.M. 1, 2 e 3 settembre 2021 produce tre documenti.

Il comando stampa conteggi, unità non classificate e anomalie con la pagina di
origine quando disponibile. Sommari e intestazioni ripetute vengono esclusi; le
tabelle con celle non ricostruite integralmente e le pagine senza testo estraibile
sono segnalate. Il parser non usa la rete né OCR.
