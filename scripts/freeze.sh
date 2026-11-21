#!/usr/bin/env bash
# 07:00 feature freeze (owner S0, docs/impl/api_contract.md §9, verification.md §6.2).
#   scripts/freeze.sh            check only: alembic heads, flags on/off vs smoke coverage, full non-mutating suite
#   scripts/freeze.sh --apply    also: merge alembic heads into one revision (0015_freeze) and upgrade the DB to it
#   scripts/freeze.sh --frontend also: typecheck + vitest in frontend/ (read-only)
# Never runs mutating tests (pytest addopts skip `mutates`, `live`, `live_llm`). Commits nothing.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APPLY=0; FRONTEND=0
for a in "$@"; do case "$a" in --apply) APPLY=1 ;; --frontend) FRONTEND=1 ;; *) echo "unknown arg $a" >&2; exit 2 ;; esac; done
cd "$ROOT/backend"
step() { printf '\n== %s\n' "$*"; }

step "1. Alembic heads"
HEADS=$(uv run --no-sync alembic heads 2>/dev/null | grep -c "head)" || true)   # real + "effective" (labelled branches)
uv run --no-sync alembic heads 2>/dev/null
echo "real heads: $HEADS"
if [ "$HEADS" -gt 1 ]; then
  if [ "$APPLY" = 1 ]; then
    # merge every head incl. labelled branches only reached via depends_on (alembic's `merge heads` skips those)
    ALL=$(uv run --no-sync alembic heads 2>/dev/null | awk '{print $1}' | paste -sd' ')
    uv run --no-sync alembic merge -m freeze --rev-id 0015_freeze $ALL
    # no-SQL merge: stamp (alembic_version may omit branches applied only through depends_on)
    uv run --no-sync alembic stamp --purge 0015_freeze
    uv run --no-sync alembic heads
  else
    echo "-> would run: alembic merge -m freeze --rev-id 0015_freeze heads && alembic upgrade head (use --apply)"
  fi
fi
uv run --no-sync alembic current 2>/dev/null | tail -3

step "2. Feature flags (config/config.example.yaml is the live config when config.yaml is absent)"
uv run --no-sync python - <<'PY'
from riskminer.config import app_config, _config_path
f = app_config().get("features") or {}
print("config:", _config_path())
print("ON :", " ".join(sorted(k for k, v in f.items() if v)))
print("OFF:", " ".join(sorted(k for k, v in f.items() if not v)))
PY

step "3. Contract + freeze guards (RISKMINER_FREEZE=1: no route may still serve a fixture)"
RISKMINER_FREEZE=1 uv run --no-sync pytest -q -p no:cacheprovider tests/contract tests/api/test_flag_smoke.py tests/api/test_write_access.py

step "4. Full non-mutating suite"
RISKMINER_FREEZE=1 uv run --no-sync pytest -q -p no:cacheprovider tests

if [ "$FRONTEND" = 1 ]; then
  step "5. Frontend typecheck + unit tests"
  cd "$ROOT/frontend"
  npx tsc -b --pretty false
  npx vitest run --reporter=dot
fi
step "done (nothing committed)"
