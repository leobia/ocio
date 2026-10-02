# OCIO

Monorepo per OCIO, agente per la sicurezza sul lavoro.

`apps/api` contiene il backend Python. Le immagini e la configurazione
infrastrutturale locale sono in `infra/`.

## Avvio locale

Prepara `.env`, Python 3.13 e le dipendenze di `apps/api` e `apps/web` come
descritto sotto. Poi, dalla radice del repository, avvia lo stack:

```sh
./scripts/dev.sh
```

Lo script sceglie Podman se disponibile, altrimenti Docker Compose; applica le
migrazioni e avvia web e API. `Ctrl+C` ferma i due processi; PostgreSQL resta
attivo nel container. Il profilo chat predefinito è `alpha`: richiede
`OPENAI_API_KEY` e `COHERE_API_KEY` in `.env`. Per avviare l'interfaccia senza
provider, lascia `OCIO_CHAT_PROFILE=` vuoto in `.env`; l'invio dei messaggi
restituisce `503 chat_unavailable`.

### Windows, Ubuntu/WSL e Podman Desktop

Esegui i comandi nella shell Ubuntu/WSL. Podman Desktop installa la CLI Windows;
in questa configurazione `podman` può non essere nel `PATH` di Ubuntu. Avvia la
macchina Podman prima dello script:

```sh
PODMAN='/mnt/c/Program Files/RedHat/Podman/podman.exe'
"$PODMAN" machine start
```

Se Ubuntu ha solo Python 3.12, prepara Python 3.13 e l'API con `uv`:

```sh
python3 -m venv /tmp/ocio-uv
/tmp/ocio-uv/bin/pip install uv
/tmp/ocio-uv/bin/uv python install 3.13
/tmp/ocio-uv/bin/uv venv --python 3.13 apps/api/.venv
/tmp/ocio-uv/bin/uv pip install --python apps/api/.venv/bin/python -e 'apps/api[dev]'
```

Con Node.js 22 e npm disponibili nella shell Ubuntu (se usi `nvm`, esegui
prima `nvm use 22`):

```sh
cd apps/web
npm ci
cd ../..
cp .env.example .env
```

Inserisci le chiavi provider in `.env` oppure svuota `OCIO_CHAT_PROFILE` per
provare web e API senza chat. Poi avvia:

```sh
./scripts/dev.sh
```

Lo script trova anche la CLI di Podman Desktop nel percorso Windows mostrato
sopra. Per lanciare Compose manualmente da WSL, passa il percorso del file in
formato Windows:

```sh
"$PODMAN" compose -f "$(wslpath -w "$PWD/compose.yaml")" up --build -d --wait db
"$PODMAN" compose -f "$(wslpath -w "$PWD/compose.yaml")" exec db psql -U ocio -d ocio -c '\dx'
```

Se `.env` proviene da un checkout Windows con terminatori CRLF, `dev.sh` li
rimuove durante il caricamento. Gli script Bash sono mantenuti con terminatori
LF tramite `.gitattributes`. Su `/mnt/c` la prima compilazione Nuxt può
richiedere diversi minuti; le richieste successive sono rapide.

### Linux/macOS con Docker Compose

```sh
cp .env.example .env
docker compose up --build -d --wait db
```

L'immagine prepara PostgreSQL 17 con `pgvector` e `pg_textsearch`. Le estensioni
vengono attivate nel database dalla migrazione `alembic upgrade head`, eseguita
anche da `dev.sh`. `compose down` ferma PostgreSQL e conserva i dati nel volume.


## Backend e migrazioni

Con Python 3.13 o successivo:

```sh
cd apps/api
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
set -a; source <(sed 's/\r$//' ../../.env); set +a
.venv/bin/alembic upgrade head
.venv/bin/ocio importa-corpus
.venv/bin/ocio normalizza-corpus
```

`POSTGRES_DB`, `POSTGRES_USER` e `POSTGRES_PASSWORD` configurano sia il
container sia la connessione dell'applicazione. `DB_HOST` e `DB_PORT` indicano
dove l'applicazione raggiunge PostgreSQL.

Alembic è l'unica fonte di verità per le evoluzioni dello schema. La migrazione
iniziale abilita in modo idempotente le due estensioni predisposte dall'immagine
locale.

## Corpus fonti

Ogni `seed_document` di `ocio_sources.yaml` punta a una o più acquisizioni
immutabili in `corpus/fonti/<id>/`. Le pagine ufficiali divise in articoli o
allegati sono registrate come file distinti. Il registro conserva URL ufficiale,
formato, data di acquisizione, SHA-256 e vigenza quando applicabile. Le nuove
acquisizioni si aggiungono come nuovi file datati; non si sostituiscono quelle
già versionate.
`.gitattributes` mantiene XML e HTML del corpus con terminatori LF anche nei
checkout Windows, perché la conversione CRLF ne cambierebbe l'hash.
Per registrare un nuovo file, aggiungilo sotto la cartella del documento e copia
nel registro il digest prodotto da `sha256sum`.

```sh
sha256sum corpus/fonti/<id>/<data>.<estensione>
```

`ocio importa-corpus` legge solo i file locali, verifica hash e formato e importa
contenuto e metadati nel database. Non contatta le fonti remote. Un file mancante,
un hash diverso o un formato inatteso interrompono l'importazione con un errore
che identifica il documento.

## Verifica

```sh
.venv/bin/ruff check .
.venv/bin/mypy
.venv/bin/pytest
docker compose -f ../../compose.yaml exec db psql -U ocio -d ocio -c '\dx' # Docker
```

## Interfaccia web

Con l'API avviata su `http://127.0.0.1:8000`:

```sh
cd apps/web
npm install
npm run dev
```

Apri `http://127.0.0.1:3000`. In ambienti diversi imposta `NUXT_API_BASE`
all'indirizzo interno della API: il browser comunica soltanto con il proxy Nuxt.

- `/`: assistente con cronologia, fonti e dati del caso.
- `/incarichi`: elenco, creazione e fascicoli con cronologia delle versioni.
- Nel fascicolo, **Chat e materiali** conserva appunti e fino a cinque allegati per
  messaggio (JPEG, PNG, WebP, PDF o testo, massimo 10 MB ciascuno). Le osservazioni
  possono essere collegate alle sezioni; un'analisi fallita conserva l'originale.
  L'analisi di foto e documenti richiede `OPENAI_API_KEY` e usa
  `OCIO_EVIDENCE_MODEL` (predefinito `gpt-4.1-mini`).
- Nel fascicolo, **Revisione e approvazione** protegge il testo manuale e approvato,
  conserva le decisioni sulle proposte e permette di esportare una revisione immutabile.
- **Dati aziendali pubblici** ricerca l’impresa dopo conferma dell’identità; ogni dato
  richiede revisione. Usa `OPENAI_API_KEY` e `OCIO_COMPANY_RESEARCH_MODEL`
  (predefinito `gpt-4.1`). Gli errori non impediscono il lavoro sul fascicolo.
- `/modelli`: sezioni, contenuto iniziale e indicazioni per l’agente. Ogni modifica
  salvata crea una revisione; gli incarichi esistenti la adottano solo applicando
  la proposta di migrazione dopo il confronto.

```sh
npm run typecheck
npm run test:e2e
npm run build
```

## Valutazione del fascicolo

`ocio valuta-fascicolo evaluation/dossier/cases-v1.yaml --output /tmp/fascicolo.json`
esegue il modello configurato e l’analisi degli allegati su incarichi fittizi nuovi,
conservati nel database per ispezione. Richiede migrazioni aggiornate e chiavi provider.
`--baseline /percorso/report.json` confronta risultati sullo stesso dataset.
Gli invarianti producono errori leggibili; riferimenti e rubrica editoriale restano
separati. `reviewed_by: null` indica esempi ancora da validare con un RSPP.
Le verifiche automatiche non attestano la correttezza professionale del fascicolo.

L’inbox `/qualita` raccoglie decisioni e segnalazioni; il responsabile può scartare,
correggere solo l’incarico o promuovere un caso riscritto con dati fittizi.
La riapertura revoca la promozione e conserva l’audit. Le fonti normative nuove
continuano a passare dal registro e dalla pipeline del corpus.

`valuta-fascicolo` include le regressioni attualmente promosse. Prima di rilasciare
modifiche all’agente, esegui `ocio verifica-rilascio-fascicolo <dataset> <report>`:
il controllo richiede invarianti superati, versioni correnti e valutazioni RSPP
registrate nel report. L’autore è dichiarato dall’operatore nell’alpha locale;
autenticazione e controllo degli accessi restano nella #21.
