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

AKN segue la gerarchia XML, HTML Gazzetta estrae il contenuto dell'atto e PDF usa
il layout conservando pagina e coordinate. Il parsing non usa rete né OCR.

Il comando stampa conteggi, partizioni non classificate e anomalie con la pagina di
origine quando disponibile.
