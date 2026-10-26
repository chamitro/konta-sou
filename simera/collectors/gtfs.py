"""Metro and tram timetables for Athens from the ΣΤΑΣΥ GTFS feed (open data, CC BY 4.0).

Stops are grouped into stations by name; for every station, service day, line and
destination we store the sorted list of departure times. Feeds published so far are
per-day timetables for a limited period (e.g. the summer timetable, one service per
calendar date), so the API also knows how to pick a representative day when today is
outside the feed's range.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import logging
import re
import sys
import zipfile
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import httpx
from sqlalchemy import delete

from simera.db import SessionLocal, init_db
from simera.models import RailDepartures, RailFeed, RailService, RailStation

log = logging.getLogger(__name__)

FEED_URLS = [
    # newest first; the transport authority catalogue is updated more often than data.gov.gr
    "https://catalog.hcapdata.gr/dataset/a7d0a0e8-2880-46c6-b85b-b4da482bd89e/resource/30a0e61c-c7a7-463b-a446-3fceca65726f/download/-.zip",
    "https://data.gov.gr/dataset/4e897a75-975a-4ce7-af65-f32ea01f93b9/resource/5e3858ee-d9ba-48c2-9015-744ea160976d/download/stasy_gtfs.zip",
]
USER_AGENT = "simera-collector/0.1 (+contact: project owner)"
ZIP_PATH = Path("data/gtfs/stasy_gtfs.zip")


def _read(z: zipfile.ZipFile, name: str) -> list[dict]:
    with z.open(name) as f:
        return list(csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig", newline="")))


def _secs(hms: str) -> int:
    h, m, s = hms.split(":")
    return int(h) * 3600 + int(m) * 60 + int(s)


def _station_key(name: str) -> str:
    return re.sub(r"\s+", " ", name.upper().replace("(ΚΕΝΤΡΟ)", "").strip())


def download(dest: Path = ZIP_PATH) -> tuple[Path, str]:
    dest.parent.mkdir(parents=True, exist_ok=True)
    last = None
    for url in FEED_URLS:
        try:
            with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=120, follow_redirects=True) as c:
                r = c.get(url)
            if r.status_code == 200 and r.content[:2] == b"PK":
                dest.write_bytes(r.content)
                return dest, url
            last = f"{url}: HTTP {r.status_code}"
        except Exception as e:  # noqa: BLE001
            last = f"{url}: {e}"
        log.warning("feed download failed: %s", last)
    raise RuntimeError(f"no GTFS feed could be downloaded ({last})")


def import_zip(path: Path, source: str = "") -> dict:
    init_db()
    with zipfile.ZipFile(path) as z:
        stops = _read(z, "stops.txt")
        routes = {r["route_id"]: r for r in _read(z, "routes.txt")}
        trips = {t["trip_id"]: t for t in _read(z, "trips.txt")}
        cal = _read(z, "calendar_dates.txt") if "calendar_dates.txt" in z.namelist() else []
        services: dict[str, date] = {}
        for c in cal:
            if c.get("exception_type", "1") == "1":
                services[c["service_id"]] = datetime.strptime(c["date"], "%Y%m%d").date()
        # stations = stops grouped by normalised name
        groups: dict[str, list[dict]] = defaultdict(list)
        for s in stops:
            if s.get("location_type", "0") in ("", "0"):
                groups[_station_key(s["stop_name"])].append(s)
        stop_to_station: dict[str, int] = {}
        stations: list[RailStation] = []
        for i, (key, ss) in enumerate(sorted(groups.items()), start=1):
            lat = sum(float(s["stop_lat"]) for s in ss) / len(ss)
            lng = sum(float(s["stop_lon"]) for s in ss) / len(ss)
            wc = {s.get("wheelchair_boarding", "") for s in ss}
            stations.append(RailStation(id=i, name=ss[0]["stop_name"].replace("(Κέντρο)", "").strip(), lat=round(lat, 6), lng=round(lng, 6),
                                        stop_ids=",".join(s["stop_id"] for s in ss), wheelchair="yes" if "1" in wc else ("no" if "2" in wc else "")))
            for s in ss:
                stop_to_station[s["stop_id"]] = i
        # pass over stop_times: departures per (station, service, line, destination); destination = last stop of the trip
        trip_last: dict[str, tuple[int, str]] = {}
        per_trip_rows: dict[str, list[tuple[int, int]]] = defaultdict(list)  # trip -> [(seq, secs@station)]
        with z.open("stop_times.txt") as f:
            for row in csv.DictReader(io.TextIOWrapper(f, encoding="utf-8-sig", newline="")):
                tid, sid, seq = row["trip_id"], row["stop_id"], int(row["stop_sequence"])
                if tid not in trips:
                    continue
                if tid not in trip_last or seq > trip_last[tid][0]:
                    trip_last[tid] = (seq, sid)
                per_trip_rows[tid].append((seq, stop_to_station.get(sid, 0), _secs(row["departure_time"] or row["arrival_time"])))
        station_name = {st.id: st.name for st in stations}
        deps: dict[tuple[int, str, str, str, int], list[int]] = defaultdict(list)
        station_lines: dict[int, set[str]] = defaultdict(set)
        for tid, rows in per_trip_rows.items():
            t = trips[tid]
            r = routes[t["route_id"]]
            dest = station_name.get(stop_to_station.get(trip_last[tid][1], 0), t.get("trip_headsign") or "")
            last_seq = trip_last[tid][0]
            for seq, st_id, secs in rows:
                if not st_id or seq == last_seq:
                    continue  # terminus arrival is not a departure
                deps[(st_id, t["service_id"], r["route_short_name"], dest, int(r["route_type"]))].append(secs)
                station_lines[st_id].add(r["route_short_name"])
        for st in stations:
            st.lines = ",".join(sorted(station_lines.get(st.id, [])))
    with SessionLocal() as s:
        for model in (RailDepartures, RailStation, RailService, RailFeed):
            s.execute(delete(model))
        s.add_all(stations)
        s.add_all([RailService(service_id=k, service_date=v) for k, v in services.items()])
        s.bulk_insert_mappings(RailDepartures, [
            dict(station_id=k[0], service_id=k[1], line=k[2], destination=k[3], route_type=k[4], times=json.dumps(sorted(v))) for k, v in deps.items()
        ])
        first, last = (min(services.values()), max(services.values())) if services else (date.today(), date.today())
        s.add(RailFeed(source=source, first_date=first, last_date=last, stops=len(stations)))
        s.commit()
    info = {"stations": len(stations), "services": len(services), "departure_rows": len(deps), "first_date": str(first), "last_date": str(last)}
    log.info("imported %s", info)
    return info


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Import the ΣΤΑΣΥ metro/tram GTFS feed")
    p.add_argument("--zip", type=Path, help="use a local GTFS zip instead of downloading")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    path, src = (a.zip, str(a.zip)) if a.zip else download()
    print(import_zip(path, src))
    return 0


if __name__ == "__main__":
    sys.exit(main())
