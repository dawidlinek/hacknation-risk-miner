#!/usr/bin/env bash
# Demo baseline / reset / status on the SERVER, via the CLI inside the api container (no login needed).
# Usage: scripts/deploy/demo_reset.sh <ssh-target> baseline|status|reset [--yes]
#   baseline  record the current state as the demo baseline (do this once, after the final restore)
#   status    show decisions made since the baseline
#   reset     revert review decisions made since the baseline (compensating rows; audit stays append-only)
# `reset` asks for confirmation unless --yes. Never run `baseline` against your local main DB.
# Not covered by reset: analyses and questions made by visitors, monitoring watches, uploads.
set -euo pipefail

TARGET="${1:?usage: $0 <ssh-target> baseline|status|reset [--yes]}"
ACTION="${2:?usage: $0 <ssh-target> baseline|status|reset [--yes]}"
case "$ACTION" in baseline|status|reset) ;; *) echo "unknown action $ACTION" >&2; exit 2 ;; esac

if [ "$ACTION" = "reset" ] && [ "${3:-}" != "--yes" ]; then
  read -r -p "Revert all demo decisions made since the baseline on $TARGET? [y/N] " a
  [ "$a" = "y" ] || { echo aborted; exit 1; }
fi

ssh -o BatchMode=yes "$TARGET" bash -s -- "$ACTION" <<'REMOTE'
set -euo pipefail
c="$(docker ps --filter label=exante.role=api --format '{{.Names}}' | head -n1)"
[ -n "$c" ] || { echo "api container not found" >&2; exit 1; }
docker exec "$c" uv run --no-sync python -m riskminer.review.demo "$1"
REMOTE
