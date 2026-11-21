#!/usr/bin/env bash
# rsync the shipped data (docs_22 PDFs, data/ref) and the server config to /srv/exante on the server.
# Usage: scripts/deploy/sync_data.sh <ssh-target> [--dry-run] [--force-config] [--config-only]
#   --config-only  send only config/config.yaml (or config.example.yaml); the API reloads it within about a second
# Resumable (--partial); a second run only sends the delta, so run it during the rehearsal and again at 07:30.
# Never shipped: docs_sample, bzp_roads raw, data/archive, data/ocr, materials/bzp_kopia.
set -euo pipefail

TARGET="${1:?usage: $0 <ssh-target> [--dry-run] [--force-config]}"
shift || true
DRY=""; FORCE_CONFIG=0; CONFIG_ONLY=0
for a in "$@"; do
  case "$a" in
    --dry-run) DRY="--dry-run" ;;
    --force-config) FORCE_CONFIG=1 ;;
    --config-only) CONFIG_ONLY=1; FORCE_CONFIG=1 ;;
    *) echo "unknown option $a" >&2; exit 2 ;;
  esac
done

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
BASE="${REMOTE_BASE:-/srv/exante}"
RSH="ssh -o BatchMode=yes -o ServerAliveInterval=30"

[ -d "$ROOT/data/raw/docs_22" ] || { echo "missing data/raw/docs_22" >&2; exit 1; }
[ -d "$ROOT/data/ref" ] || { echo "missing data/ref" >&2; exit 1; }

$RSH "$TARGET" "mkdir -p $BASE/pg $BASE/dump $BASE/data/raw $BASE/data/ref $BASE/exports $BASE/hf $BASE/config"

if [ "$CONFIG_ONLY" != "1" ]; then
# rsync when the server has it (resumable, delta only); otherwise tar over ssh (full copy, no resume).
if $RSH "$TARGET" "command -v rsync >/dev/null"; then
  copy() { rsync -e "$RSH" -a --partial --info=progress2 $DRY "$1/" "$TARGET:$2/"; }
else
  echo "rsync not installed on the server: falling back to tar over ssh (full copy, no resume)"
  copy() {
    if [ -n "$DRY" ]; then echo "would copy $1 -> $2"; return; fi
    tar -C "$1" -cf - . | $RSH "$TARGET" "mkdir -p '$2' && tar -C '$2' -xf -"
  }
fi
echo "== data/ref"
copy "$ROOT/data/ref" "$BASE/data/ref"
echo "== data/raw/docs_22"
copy "$ROOT/data/raw/docs_22" "$BASE/data/raw/docs_22"

# The container user may differ from the ssh user: make the tree readable, and writable for uploads.
[ -n "$DRY" ] || $RSH "$TARGET" "chmod -R a+rX $BASE/data $BASE/config; chmod 777 $BASE/exports $BASE/hf; chmod 775 $BASE/data $BASE/data/raw"
fi

echo "== config"
SRC="$ROOT/config/config.yaml"
[ -f "$SRC" ] || SRC="$ROOT/config/config.example.yaml"
if $RSH "$TARGET" "test -f $BASE/config/config.yaml" && [ "$FORCE_CONFIG" != "1" ]; then
  echo "config.yaml exists on the server, left alone (use --force-config to replace; source would be $SRC)"
else
  if [ -n "$DRY" ]; then echo "would send $SRC"; else $RSH "$TARGET" "cat > $BASE/config/config.yaml" < "$SRC"; fi
  echo "sent $SRC; review feature flags and the WCSS base_url on the server"
fi
echo "done"
