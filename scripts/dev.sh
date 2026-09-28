#!/usr/bin/env bash

set -Eeuo pipefail

repository=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
environment="$repository/.env"

if [[ ! -f "$environment" ]]; then
  echo "Configurazione mancante: copia .env.example in .env." >&2
  exit 1
fi
if [[ ! -x "$repository/apps/api/.venv/bin/uvicorn" ]]; then
  echo "Ambiente API mancante: installa apps/api con le dipendenze dev." >&2
  exit 1
fi
if [[ ! -d "$repository/apps/web/node_modules" ]]; then
  echo "Dipendenze web mancanti: esegui npm install in apps/web." >&2
  exit 1
fi

set -a
source "$environment"
set +a
export OCIO_CHAT_PROFILE="${OCIO_CHAT_PROFILE:-alpha}"
export NUXT_API_BASE="${NUXT_API_BASE:-http://127.0.0.1:8000}"

cd "$repository"
docker compose up --build -d --wait db

cd "$repository/apps/api"
.venv/bin/alembic upgrade head
.venv/bin/uvicorn ocio.api:create_app --factory --host 127.0.0.1 --port 8000 &
api_pid=$!

cd "$repository/apps/web"
npm run dev -- --host 127.0.0.1 --port 3000 &
web_pid=$!

cleanup() {
  trap - EXIT INT TERM
  kill "$api_pid" "$web_pid" 2>/dev/null || true
  wait "$api_pid" "$web_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "OCIO avviato:"
echo "  Web: http://127.0.0.1:3000"
echo "  API: http://127.0.0.1:8000"
echo "  Profilo chat: $OCIO_CHAT_PROFILE"
echo "Premi Ctrl+C per fermare API e web; PostgreSQL resta attivo."

wait -n "$api_pid" "$web_pid"
