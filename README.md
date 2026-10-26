# Κοντά σου / Near you (working name: Simera)

Open the app, it finds where you are, and shows what matters around you right now: pharmacies and hospitals on duty, live bus arrivals, fuel prices for your prefecture with the stations around you, and what else is nearby (ATMs, EV chargers, bakeries, cafés, parking, playgrounds, ΚΕΠ ...). Attica first; places data covers all of Greece.

## Modules

| Module | Status | Source |
|---|---|---|
| Fuel prices per prefecture (incl. heating oil) | working | fuelprices.gr daily PDF bulletins (archive from 2018; 2017 uses an unsupported Excel layout) |
| Live bus arrivals (Athens) | working | OASA telematics API (public, unofficial) |
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
.venv/bin/uvicorn simera.api.main:app --reload
```

Open http://127.0.0.1:8000/ for the page, http://127.0.0.1:8000/docs for the API.

Set `DATABASE_URL` to use PostgreSQL instead of the default SQLite file in `data/`.

## Daily run

`scripts/daily.sh` runs all collectors; schedule it with cron (see the comment in the script).

## System dependencies

- LibreOffice (`soffice`) for converting the Ministry of Health .doc rota to HTML.

## Tests

```bash
.venv/bin/python -m pytest -q
```
