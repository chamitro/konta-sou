#!/usr/bin/env bash
# Daily collection for Simera. Run from cron, e.g. at 07:30 Athens time:
#   30 7 * * *  /home/harry/newspaper_validity/scripts/daily.sh >> /home/harry/newspaper_validity/data/daily.log 2>&1
set -u
cd "$(dirname "$0")/.."
PY=.venv/bin/python
echo "== $(date -Is) fuel";       $PY -m simera.collectors.fuel --days 7 --discard-raw
echo "== $(date -Is) pharmacies"; $PY -m simera.collectors.pharmacies --days-ahead 7
echo "== $(date -Is) hospitals";  $PY -m simera.collectors.hospitals --days-back 1
echo "== $(date -Is) done"
# Weekly (e.g. Sunday 04:00): metro/tram timetable and the places table from the OpenStreetMap Greece extract
#   0 3 * * 0  cd /home/harry/newspaper_validity && .venv/bin/python -m simera.collectors.gtfs >> data/daily.log 2>&1
#   0 4 * * 0  cd /home/harry/newspaper_validity && .venv/bin/python -m simera.collectors.osm_pois >> data/daily.log 2>&1
