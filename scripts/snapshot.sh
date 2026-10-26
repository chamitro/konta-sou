#!/usr/bin/env bash
# Build a compressed copy of the database for the server to download at startup.
# Usage: scripts/snapshot.sh            -> data/snapshot/simera-YYYYMMDD.db.gz
#        scripts/snapshot.sh --release  -> also upload it to a GitHub release named "data" (needs gh auth)
set -eu
cd "$(dirname "$0")/.."
mkdir -p data/snapshot
OUT=data/snapshot/simera-$(date +%Y%m%d).db
rm -f "$OUT" "$OUT.gz"
.venv/bin/python - "$OUT" <<'PY'
import sqlite3, sys
src = sqlite3.connect("data/simera.db")
src.execute("DELETE FROM osm_cache")
src.commit()
src.execute(f"VACUUM INTO '{sys.argv[1]}'")
print("snapshot written")
PY
gzip -9 "$OUT"
ls -la "$OUT.gz"
if [ "${1:-}" = "--release" ]; then
  gh release view data >/dev/null 2>&1 || gh release create data --title "Data snapshots" --notes "Prebuilt SQLite snapshots for the server (places, timetables, fuel history)."
  gh release upload data "$OUT.gz" --clobber
  cp "$OUT.gz" data/snapshot/simera-latest.db.gz && gh release upload data data/snapshot/simera-latest.db.gz --clobber
  echo "SNAPSHOT_URL: https://github.com/$(gh repo view --json nameWithOwner -q .nameWithOwner)/releases/download/data/simera-latest.db.gz"
fi
