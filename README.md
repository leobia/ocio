# OCIO

Monorepo per OCIO, agente per la sicurezza sul lavoro.

`apps/api` contiene il backend Python. Le immagini e la configurazione
infrastrutturale locale sono in `infra/`.

## Avvio locale

Avvia PostgreSQL 17 con `pgvector` e `pg_textsearch`:

```sh
cp .env.example .env
docker compose up --build -d
```

L’immagine Docker prepara PostgreSQL perché possa usare pgvector e pg_textsearch, ma non le attiva automaticamente nel singolo database.

  Quindi:

  1. `docker compose up` avvia un PostgreSQL capace di caricare quelle estensioni.
  2. `alembic upgrade head` esegue la migrazione che le abilita nel database ocio.
  3. `docker compose down` ferma il database ma conserva i dati nel volume Docker; al successivo up ritrovi database ed estensioni già applicate.


## Backend e migrazioni

Con Python 3.13 o successivo:

```sh
cd apps/api
python -m venv .venv
.venv/bin/pip install -e ".[dev]"
set -a; . ../../.env; set +a
.venv/bin/alembic upgrade head
.venv/bin/ocio importa-corpus
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
docker compose -f ../../compose.yaml exec db psql -U ocio -d ocio -c '\dx'
```
