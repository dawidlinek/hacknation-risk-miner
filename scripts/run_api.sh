#!/usr/bin/env bash
# Risk Miner API on http://127.0.0.1:8000 (docs: /docs, contract: /openapi.json)
set -euo pipefail
cd "$(dirname "$0")/../backend"
exec uv run uvicorn riskminer.api.main:app --host "${HOST:-127.0.0.1}" --port "${PORT:-8000}" "$@"
