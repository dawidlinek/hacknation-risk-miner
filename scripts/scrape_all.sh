#!/usr/bin/env bash
# Re-run the P0+P1 connectors (idempotent: fresh manifest entries are served from data/raw) and load them.
# Usage: scripts/scrape_all.sh [extra args passed to every scraper, e.g. --since 2026-11-20]
set -uo pipefail
cd "$(dirname "$0")/../backend"
for s in bzp_api vat_whitelist teryt geo mapa_dotacji ted kio nik cru docs_22; do
  echo "=== $s"; uv run riskminer scrape "$s" "$@" || echo "!!! $s failed (see ingestion_run)"
done
uv run riskminer derive-bzp && uv run riskminer link-pilot && uv run riskminer derive-events && uv run riskminer report
