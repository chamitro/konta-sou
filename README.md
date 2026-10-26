# Κοντά σου / Near you (working name: Simera)

Open the app, it finds where you are, and shows what matters around you right now: pharmacies and hospitals on duty, live bus arrivals, fuel prices for your prefecture with the stations around you, and what else is nearby (ATMs, EV chargers, bakeries, cafés, parking, playgrounds, ΚΕΠ ...). Attica first; places data covers all of Greece.

## Modules

| Module | Status | Source |
|---|---|---|
| Fuel prices per prefecture (incl. heating oil) | working | fuelprices.gr daily PDF bulletins (archive from 2018; 2017 uses an unsupported Excel layout) |
| Live bus arrivals (Athens) | working | OASA telematics API (public, unofficial) |
| Metro and tram: nearest station, next departures (Athens) | working | ΣΤΑΣΥ GTFS feed (data.gov.gr, CC BY 4.0); exact day when the feed covers it, otherwise a representative same-weekday schedule labelled as indicative |
| Electricity tariff of the month | planned | RAAEY monthly tariff tables |
| Pharmacies on duty (Attica) | working | Attica Pharmacists' Association site (fsa-efimeries.gr), fetched daily for the next 7 days |
| Hospitals on duty (Attica) | working | Ministry of Health daily rota (.doc), converted with LibreOffice; hospital coordinates from a curated table (approximate) |
| Open-air market (λαϊκή) schedule | planned | curated table from regional decisions |
| Events near me | planned | narrow slice, municipal culture calendars |
| What's nearby (20 place categories) | working | OpenStreetMap Greece extract imported weekly into the `pois` table; Overpass API only as a fallback |
| Location naming + prefecture detection | working | OSM Nominatim reverse geocoding (1 req/s, cached) + nearest prefecture centroid |

## Data policy

Only openly published data is used. Places come from OpenStreetMap under the ODbL; the page carries the attribution. fuelprices.gr protects its station-level search with a
CAPTCHA intended to block automated collection; we respect that and use the openly published
bulletins (prefecture averages) instead.

## Run

```bash
python3.10 -m venv --without-pip .venv && curl -sS https://bootstrap.pypa.io/get-pip.py | .venv/bin/python
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m simera.collectors.fuel --days 30      # or --all for the full archive, --repair to re-fetch bad parses
.venv/bin/python -m simera.collectors.pharmacies            # next 7 days of Attica duty rotas
.venv/bin/python -m simera.collectors.hospitals             # today's and tomorrow's Attica hospital rota (needs `soffice` on PATH)
.venv/bin/python -m simera.collectors.osm_pois              # weekly: download the Greece OSM extract (~400 MB) and rebuild the places table
.venv/bin/python -m simera.collectors.gtfs                  # weekly: metro/tram timetable (GTFS)
scripts/devserver.sh start                                  # dev server on :8891 with a pid file (stop|restart)
.venv/bin/uvicorn simera.api.main:app --reload
```

Open http://127.0.0.1:8000/ for the page, http://127.0.0.1:8000/docs for the API.

Set `DATABASE_URL` to use PostgreSQL instead of the default SQLite file in `data/`.

## Deploy (Render free tier + GitHub Pages)

1. Push the repo to GitHub. Build a data snapshot here and attach it to a release: `scripts/snapshot.sh --release` (prints the `SNAPSHOT_URL`).
2. In Render: **New → Blueprint**, pick the repo; `render.yaml` defines a free Docker web service. Set the `SNAPSHOT_URL` env var to the release asset URL. First boot downloads the snapshot (~40 MB) and starts collecting the daily data (pharmacies, hospitals, fuel) in the background; from then on once a day at 04:30 UTC.
3. Build the page against the API and publish it: `python scripts/build_docs.py https://konta-sou-api.onrender.com`, commit `docs/`, enable GitHub Pages from the `docs` folder. Set `ALLOWED_ORIGINS` on Render to your Pages origin.
4. The snapshot rebuilds itself every Sunday on GitHub Actions (`.github/workflows/snapshot.yml`) and is uploaded to the `data` release. To have the server restart with it automatically, copy the service's **Deploy Hook** URL from Render (Settings → Deploy Hook) into a repository secret named `RENDER_DEPLOY_HOOK`.
5. Sources that only answer from Greek networks (Ministry of Health hospital rota, OASA live buses) need the API, or a relay, on a Greek-hosted machine; see "Known limits".

The free instance sleeps after 15 minutes without traffic; the first request afterwards takes about a minute.

## Known limits

- The Ministry of Health site and the OASA telematics API refuse connections from hosting networks abroad (observed from Render and GitHub Actions: HTTP 421 and timeouts). Running the API on a server in Greece is the clean fix; until then the public page shows hospital rotas only via the relay file and no live buses.
- About 1.5% of fuel bulletins since 2018 remain partially parsed (second-page column shifts in a few 2019–2020 files).

## Daily run

`scripts/daily.sh` runs all collectors; schedule it with cron (see the comment in the script).

## System dependencies

- LibreOffice (`soffice`) for converting the Ministry of Health .doc rota to HTML.

## Tests

```bash
.venv/bin/python -m pytest -q
```
