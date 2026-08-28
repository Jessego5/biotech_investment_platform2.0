#!/usr/bin/env bash
# Bring the whole thing up locally: Postgres, the API, and the frontend.
#
#   ./run-local.sh          start everything and print where it is
#   ./run-local.sh stop     stop the containers and the frontend server
#
# The database keeps its data in a Docker volume, so this is safe to run
# repeatedly — it does not re-fetch anything. Populating an empty database is a
# separate job and takes hours; see "if the database is empty" at the end.
set -euo pipefail

cd "$(dirname "$0")"
FRONTEND_PORT=5501
API_PORT=8000
PIDFILE=".frontend.pid"

stop() {
  echo "stopping the frontend..."
  [ -f "$PIDFILE" ] && kill "$(cat "$PIDFILE")" 2>/dev/null || true
  rm -f "$PIDFILE"
  echo "stopping containers..."
  docker compose down
  echo "done. The database volume is kept; nothing was re-fetched."
}

if [ "${1:-}" = "stop" ]; then stop; exit 0; fi

# Keys come from backend/.env rather than the shell, because that is where they
# already live for the scripts. Compose reads them from the environment, so they
# have to be exported here or the API starts without them and the chat is simply
# off — which looks like a broken chat rather than a missing key.
# parsed rather than sourced. Values in this file are unquoted and contain
# spaces ("biotech-agent you@example.com"), so `. backend/.env` tries to run the
# second word as a command and the script dies before it starts anything.
read_env() {
  [ -f backend/.env ] || return 0
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in ''|'#'*) continue;; esac
    key=${line%%=*}
    val=${line#*=}
    case "$key" in OPENAI_API_KEY|SEC_USER_AGENT) export "$key=$val";; esac
  done < backend/.env
}
read_env
: "${OPENAI_API_KEY:=}"
: "${SEC_USER_AGENT:=}"
export OPENAI_API_KEY SEC_USER_AGENT

if ! docker info >/dev/null 2>&1; then
  echo "Docker is not running. Start Docker (or 'colima start') and try again." >&2
  exit 1
fi

echo "starting Postgres and the API..."
docker compose up -d db api

printf "waiting for the API to answer"
for _ in $(seq 1 60); do
  if [ "$(docker inspect -f '{{.State.Health.Status}}' biotech_agent_20-api-1 2>/dev/null)" = "healthy" ]; then
    echo " ok"; break
  fi
  printf "."; sleep 2
done

# the frontend is static, so any server will do; devserve.py just disables
# caching so an edit shows up on refresh
if lsof -nP -iTCP:"$FRONTEND_PORT" -sTCP:LISTEN >/dev/null 2>&1; then
  echo "something is already serving port $FRONTEND_PORT; leaving it alone"
else
  echo "serving the frontend..."
  ( cd frontend && python3 devserve.py >/dev/null 2>&1 & echo $! > "../$PIDFILE" )
fi

STATS=$(curl -s --max-time 5 "http://localhost:$API_PORT/stats" || true)
echo
echo "  app       http://127.0.0.1:$FRONTEND_PORT/index.html"
echo "  API       http://localhost:$API_PORT   (try /stats, /companies, /company/ABBV)"
echo
if [ -n "$STATS" ]; then
  echo "  holding   $STATS"
else
  echo "  the API is up but /stats did not answer yet; give it a few seconds"
fi
if [ -z "$OPENAI_API_KEY" ]; then
  echo
  echo "  note: OPENAI_API_KEY is not set, so the chat is off. Everything else works;"
  echo "        the company narrative falls back to a fixed template."
fi
echo
echo "  stop with ./run-local.sh stop"
echo
echo "  if the database is empty (companies: 0), populate it with:"
echo "    docker compose run --rm ingest python migrate_to_postgres.py   # if a SQLite copy exists"
echo "    docker compose run --rm ingest python ingest.py                # otherwise: hours, hits live APIs"
