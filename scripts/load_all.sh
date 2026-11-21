#!/usr/bin/env bash
# One command: Postgres up -> schema -> catalogue -> organizer XLSX -> national BZP copy -> live BZP delta ->
# derive case base -> link the 22 pilot projects -> deterministic events -> scraped sources -> test report.
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose -f infra/docker-compose.yml up -d db
until docker exec riskminer-db pg_isready -U riskminer >/dev/null 2>&1; do sleep 1; done
cd backend
uv sync --quiet
uv run alembic upgrade head
uv run riskminer load-all "$@"
