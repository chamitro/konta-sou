#!/usr/bin/env bash
# Container entrypoint: fetch the prebuilt data snapshot if there is no database yet, then serve.
set -eu
cd "$(dirname "$0")/.."
DB=${DB_PATH:-data/simera.db}
if [ ! -s "$DB" ] && [ -n "${SNAPSHOT_URL:-}" ]; then
  echo "downloading data snapshot from $SNAPSHOT_URL"
  mkdir -p "$(dirname "$DB")"
  curl -fsSL "$SNAPSHOT_URL" | gunzip -c > "$DB.tmp" && mv "$DB.tmp" "$DB"
  echo "snapshot ready: $(du -h "$DB" | cut -f1)"
fi
exec python -m uvicorn simera.api.main:app --host 0.0.0.0 --port "${PORT:-8000}" --workers 1
