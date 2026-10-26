"""Import places of interest for Greece from the OpenStreetMap extract (Geofabrik, ODbL).

Downloads greece-latest.osm.pbf (~400 MB) when newer than the last import, streams it once with
pyosmium, keeps nodes/ways/relations matching our categories (ways and relations reduced to a
centroid), and replaces the `pois` table. Run weekly.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx
import osmium
from sqlalchemy import delete, select

from simera.categories import categorize
from simera.db import SessionLocal, init_db
from simera.models import Poi, PoiImport

log = logging.getLogger(__name__)

PBF_URL = "https://download.geofabrik.de/europe/greece-latest.osm.pbf"
PBF_PATH = Path("data/osm/greece-latest.osm.pbf")
USER_AGENT = "simera-collector/0.1 (+contact: project owner)"
EXTRA_TAGS = ("wheelchair", "operator", "fee", "capacity", "dispensing", "internet_access", "outdoor_seating", "takeaway", "blue_flag")


class _Pass1(osmium.SimpleHandler):
    """Tagged nodes that match a category become rows; matching ways remember their node refs."""

    def __init__(self):
        super().__init__()
        self.rows: list[dict] = []
        self.ways: list[tuple[int, dict, list[int]]] = []
        self.needed: set[int] = set()
        self.seen = 0

    def node(self, n):
        self.seen += 1
        if n.tags and n.location.valid():
            t = dict(n.tags)
            if categorize(t):
                self.rows.append(make_row("n", n.id, t, n.location.lat, n.location.lon))

    def way(self, w):
        if not w.tags:
            return
        t = dict(w.tags)
        if categorize(t):
            refs = [nd.ref for nd in w.nodes]
            self.ways.append((w.id, t, refs))
            self.needed.update(refs)


class _Pass2(osmium.SimpleHandler):
    """Locations of just the nodes referenced by matching ways (a few hundred thousand at most)."""

    def __init__(self, needed: set[int]):
        super().__init__()
        self.needed = needed
        self.loc: dict[int, tuple[float, float]] = {}

    def node(self, n):
        if n.id in self.needed and n.location.valid():
            self.loc[n.id] = (n.location.lat, n.location.lon)


def make_row(otype: str, oid: int, t: dict, lat: float, lng: float) -> dict:
    cat = categorize(t)
    addr = " ".join(x for x in [t.get("addr:street"), t.get("addr:housenumber")] if x) or t.get("addr:city", "")
    return dict(
        osm_type=otype, osm_id=oid, category=cat,
        name=(t.get("name") or t.get("name:el") or "")[:200], brand=(t.get("brand") or "")[:100],
        lat=round(lat, 6), lng=round(lng, 6), address=addr[:200],
        opening_hours=(t.get("opening_hours") or "")[:200], phone=(t.get("phone") or t.get("contact:phone") or "")[:60],
        website=(t.get("website") or t.get("contact:website") or "")[:200], cuisine=(t.get("cuisine") or "")[:100],
        extra=json.dumps({k: t[k] for k in EXTRA_TAGS if k in t}, ensure_ascii=False)[:400],
    )


def download(force: bool = False) -> tuple[Path, str]:
    PBF_PATH.parent.mkdir(parents=True, exist_ok=True)
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True) as c:
        head = c.head(PBF_URL)
        remote_mod = head.headers.get("last-modified", "")
        size = int(head.headers.get("content-length", "0"))
        if PBF_PATH.exists() and not force and (size == 0 or PBF_PATH.stat().st_size == size):
            log.info("extract already downloaded (%d MB)", size // 1_000_000)
            return PBF_PATH, remote_mod
        log.info("downloading %s (%d MB)", PBF_URL, size // 1_000_000)
        tmp = PBF_PATH.with_suffix(".part")
        with c.stream("GET", PBF_URL) as r, tmp.open("wb") as f:
            r.raise_for_status()
            for chunk in r.iter_bytes(1 << 20):
                f.write(chunk)
        tmp.replace(PBF_PATH)
    return PBF_PATH, remote_mod


def import_pbf(path: Path, source_modified: str = "") -> int:
    init_db()
    t0 = time.time()
    p1 = _Pass1()
    p1.apply_file(str(path))
    log.info("pass 1: %d nodes scanned in %.0fs; %d node POIs, %d way POIs", p1.seen, time.time() - t0, len(p1.rows), len(p1.ways))
    rows = p1.rows
    if p1.ways:
        p2 = _Pass2(p1.needed)
        p2.apply_file(str(path))
        for wid, t, refs in p1.ways:
            pts = [p2.loc[r] for r in refs if r in p2.loc]
            if pts:
                rows.append(make_row("w", wid, t, sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)))
        log.info("pass 2 done in %.0fs total", time.time() - t0)
    with SessionLocal() as s:
        s.execute(delete(Poi))
        for i in range(0, len(rows), 5000):
            s.bulk_insert_mappings(Poi, rows[i:i + 5000])
        s.add(PoiImport(source=PBF_URL, source_modified=source_modified, count=len(rows)))
        s.commit()
    return len(rows)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Import Greek POIs from the OSM extract")
    p.add_argument("--force-download", action="store_true")
    p.add_argument("--pbf", type=Path, help="use an existing .osm.pbf instead of downloading")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    path, mod = (a.pbf, "") if a.pbf else download(a.force_download)
    n = import_pbf(path, mod)
    print(f"imported {n} POIs")
    return 0


if __name__ == "__main__":
    sys.exit(main())
