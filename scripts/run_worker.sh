#!/usr/bin/env bash
# One shared Risk Miner job worker (job table, FOR UPDATE SKIP LOCKED), kept alive for the dev/demo machine.
#  * restarted when it exits;
#  * restarted when backend code changes (job kinds register at import, handlers are imported once), but only
#    after the files have been quiet for one poll and no job is running, so a job is never cut off mid-run.
# Usage: scripts/run_worker.sh            (logs to stdout; one instance only, RAM is tight)
# Env:   POLL=20  DB_CONTAINER=riskminer-db
set -uo pipefail
cd "$(dirname "$0")/../backend"
POLL="${POLL:-20}"
DB_CONTAINER="${DB_CONTAINER:-riskminer-db}"

sig() { find riskminer -name '*.py' -printf '%T@ %p\n' 2>/dev/null | sort | md5sum | cut -c1-32; }
running_jobs() {
  docker exec "$DB_CONTAINER" psql -U riskminer -d riskminer -tAc "SELECT count(*) FROM job WHERE status = 'running'" 2>/dev/null || echo 1
}

pid=""
started_sig=""
last_sig="$(sig)"
trap '[ -n "$pid" ] && kill "$pid" 2>/dev/null; exit 0' INT TERM

while true; do
  now_sig="$(sig)"
  if [ -z "$pid" ] || ! kill -0 "$pid" 2>/dev/null; then
    .venv/bin/riskminer worker &
    pid=$!
    started_sig="$now_sig"
    echo "$(date -Is) worker started (pid $pid)"
  elif [ "$now_sig" != "$started_sig" ] && [ "$now_sig" = "$last_sig" ] && [ "$(running_jobs)" = "0" ]; then
    echo "$(date -Is) code changed and worker idle: restarting (pid $pid)"
    kill "$pid" 2>/dev/null
    wait "$pid" 2>/dev/null
    pid=""
    continue
  fi
  last_sig="$now_sig"
  sleep "$POLL"
done
