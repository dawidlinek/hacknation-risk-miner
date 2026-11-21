#!/usr/bin/env bash
# Copy a dump to the server and restore it into the production db container, replacing the database.
# Usage: scripts/deploy/restore_db.sh <ssh-target> [dump_file]
#        e.g. scripts/deploy/restore_db.sh root@212.127.90.86 data/snapshots/demo_freeze.dump
# Env:   REMOTE_DUMP_DIR (/srv/exante/dump), JOBS (8), POSTGRES_USER (riskminer), POSTGRES_DB (riskminer),
#        DB_CONTAINER  override container name (default: found by label exante.role=db)
#        YES=1         skip the confirmation prompt (the SSH connection itself never prompts)
# The api and worker are stopped during the restore and started again afterwards.
# DESTRUCTIVE: drops and recreates the database on the server.
set -euo pipefail

TARGET="${1:?usage: $0 <ssh-target> [dump_file]}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
DUMP="${2:-$ROOT/data/snapshots/demo_freeze.dump}"
REMOTE_DIR="${REMOTE_DUMP_DIR:-/srv/exante/dump}"
JOBS="${JOBS:-8}"
PGU="${POSTGRES_USER:-riskminer}"
PGD="${POSTGRES_DB:-riskminer}"
SSH=(ssh -o BatchMode=yes -o ServerAliveInterval=30)

[ -f "$DUMP" ] || { echo "dump not found: $DUMP" >&2; exit 1; }
name="$(basename "$DUMP")"
echo "local sha256: $(sha256sum "$DUMP" | cut -d' ' -f1)"

if [ "${YES:-}" != "1" ]; then
  read -r -p "Replace database '$PGD' on $TARGET with $name? [y/N] " a
  [ "$a" = "y" ] || { echo aborted; exit 1; }
fi

echo "== copying dump"
"${SSH[@]}" "$TARGET" "mkdir -p '$REMOTE_DIR'"
rsync -e "ssh -o BatchMode=yes" --partial --info=progress2 "$DUMP" "$TARGET:$REMOTE_DIR/$name"
"${SSH[@]}" "$TARGET" "cd '$REMOTE_DIR' && sha256sum '$name'"

echo "== restoring"
"${SSH[@]}" "$TARGET" bash -s -- "$name" "$JOBS" "$PGU" "$PGD" "${DB_CONTAINER:-}" <<'REMOTE'
set -euo pipefail
name="$1"; jobs="$2"; pgu="$3"; pgd="$4"; db="$5"
if [ -z "$db" ]; then
  db="$(docker ps --filter label=exante.role=db --format '{{.Names}}' | head -n1)"
fi
[ -n "$db" ] || { echo "db container not found (is the Coolify resource deployed?)" >&2; exit 1; }
echo "db container: $db"

# Stop only OUR writers (other stacks on this host also have api-* / worker-* containers).
writers="$(docker ps --filter label=exante.role=api --format '{{.Names}}'; docker ps --filter label=exante.role=worker --format '{{.Names}}')"
[ -z "$writers" ] || docker stop $writers

docker exec "$db" psql -U "$pgu" -d postgres -v ON_ERROR_STOP=1 \
  -c "DROP DATABASE IF EXISTS \"$pgd\" WITH (FORCE)" -c "CREATE DATABASE \"$pgd\""
docker exec "$db" psql -U "$pgu" -d "$pgd" -v ON_ERROR_STOP=1 \
  -c "CREATE EXTENSION IF NOT EXISTS vector" -c "CREATE EXTENSION IF NOT EXISTS pg_trgm" -c "CREATE EXTENSION IF NOT EXISTS unaccent"

start=$(date +%s)
# Extension-already-exists notices are harmless, so no -e / --exit-on-error.
docker exec "$db" pg_restore -U "$pgu" -d "$pgd" -j "$jobs" --no-owner --no-privileges "/dump/$name" || echo "pg_restore reported errors (see above)"
echo "restore took $(( $(date +%s) - start )) s"

docker exec "$db" psql -U "$pgu" -d "$pgd" -c "ANALYZE" -c "SELECT version_num FROM alembic_version" -c "SELECT count(*) AS notices FROM notice"

[ -z "$writers" ] || docker start $writers
REMOTE
echo "== done. Redeploy in Coolify (or wait for the restarted api) and run the smoke test in docs/DEPLOY.md."
