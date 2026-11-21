#!/usr/bin/env bash
# Trimmed pg_dump of the LOCAL dev database, for shipping to the production server.
# Usage: scripts/deploy/dump_db.sh [out_file]        (default data/snapshots/demo_freeze.dump)
# Env:   LOCAL_DB_CONTAINER (riskminer-db), PGUSER (riskminer), PGDATABASE (riskminer),
#        EXCLUDE_DATA  space separated tables whose DATA is skipped (default none: job and llm_call are FK targets, excluding them breaks pg_restore)
# Reads nothing from .env, prints no secrets. Runs only against the local container.
set -euo pipefail

CONTAINER="${LOCAL_DB_CONTAINER:-riskminer-db}"
PGUSER="${PGUSER:-riskminer}"
PGDATABASE="${PGDATABASE:-riskminer}"
EXCLUDE_DATA="${EXCLUDE_DATA-}"
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="${1:-$ROOT/data/snapshots/demo_freeze.dump}"

mkdir -p "$(dirname "$OUT")"
args=()
for t in $EXCLUDE_DATA; do args+=("--exclude-table-data=$t"); done

echo "dumping $PGDATABASE from container $CONTAINER (excluding data of: ${EXCLUDE_DATA:-none})"
start=$(date +%s)
docker exec "$CONTAINER" pg_dump -U "$PGUSER" -Fc --compress=zstd:3 --no-owner --no-privileges \
  "${args[@]}" "$PGDATABASE" > "$OUT.part"
mv "$OUT.part" "$OUT"
end=$(date +%s)

echo "file:   $OUT"
echo "size:   $(du -h "$OUT" | cut -f1) ($(stat -c %s "$OUT") bytes)"
echo "time:   $((end - start)) s"
echo "sha256: $(sha256sum "$OUT" | cut -d' ' -f1)"
