"""Events from the City of Athens culture portal, cultureisathens.gr.

The portal (municipal, free events across Athens) publishes its events through the public WordPress REST API
(/wp-json/wp/v2/event) and each event page carries the date, venue, category, price and map coordinates.
We list recently modified events via the API and fetch only the pages we have not seen or that changed,
with a pause between requests and an honest User-Agent. robots.txt allows it.
"""
from __future__ import annotations

import argparse
import html
import logging
import re
import time
from datetime import datetime, timedelta
from typing import Any

import httpx
from sqlalchemy import select

from simera.db import SessionLocal, init_db
from simera.models import Event

log = logging.getLogger(__name__)
SOURCE = "cultureisathens"
BASE = "https://cultureisathens.gr"
USER_AGENT = "simera-collector/0.1 (+https://github.com/chamitro/konta-sou)"
MONTHS = {"ιανουαριου": 1, "φεβρουαριου": 2, "μαρτιου": 3, "απριλιου": 4, "μαιου": 5, "ιουνιου": 6, "ιουλιου": 7, "αυγουστου": 8, "σεπτεμβριου": 9, "οκτωβριου": 10, "νοεμβριου": 11, "δεκεμβριου": 12}
_PAIR = re.compile(r'<div class="gt-title">([^<]*)</div>\s*<div class="gt-inner">(.*?)</div>', re.S)
_LATLNG = re.compile(r'data-lat="([\d.]+)" data-lng="([\d.]+)"')
_PRICE = re.compile(r'<div class="gt-price">(.*?)</div>', re.S)
_OG = re.compile(r'<meta property="og:image" content="([^"]+)"')


def _strip_accents(s: str) -> str:
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn")


def parse_greek_datetime(s: str) -> datetime | None:
    """'6 Νοεμβρίου 2026 21:00' or '6 Νοεμβρίου 2026' -> datetime."""
    m = re.search(r"(\d{1,2})\s+([Α-Ωα-ωΆ-ώ]+)\s+(\d{4})(?:\s+(\d{1,2}):(\d{2}))?", s)
    if not m:
        return None
    mon = MONTHS.get(_strip_accents(m.group(2)).lower())
    if not mon:
        return None
    return datetime(int(m.group(3)), mon, int(m.group(1)), int(m.group(4) or 0), int(m.group(5) or 0))


def _text(fragment: str) -> str:
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", fragment)).split())


def parse_event_page(page: str) -> dict[str, Any]:
    fields = {_text(t): v for t, v in _PAIR.findall(page)}
    out: dict[str, Any] = {"starts_at": None, "ends_at": None, "venue": None, "categories": None, "price": None, "lat": None, "lng": None, "image": None, "status": None}
    for key, raw in fields.items():
        k = _strip_accents(key).lower()
        if k.startswith("ημερομηνια") and "ληξ" not in k and out["starts_at"] is None:
            out["starts_at"] = parse_greek_datetime(_text(raw))
        elif "ληξ" in k or k.startswith("εως"):
            out["ends_at"] = parse_greek_datetime(_text(raw))
        elif k.startswith("χωρος"):
            out["venue"] = _text(raw) or None
        elif k.startswith("κατηγορια"):
            cats = [_text(c) for c in re.findall(r"<a[^>]*>(.*?)</a>", raw, re.S)] or _text(raw).split()
            out["categories"] = " · ".join(dict.fromkeys(c for c in cats if c)) or None
        elif k.startswith("κατασταση"):
            out["status"] = _text(raw)
    m = _LATLNG.search(page)
    if m:
        out["lat"], out["lng"] = float(m.group(1)), float(m.group(2))
    m = _PRICE.search(page)
    if m:
        p = _text(m.group(1))
        out["price"] = "Δωρεάν" if p.lower() in ("free", "δωρεάν", "0", "0€", "0 €") else p or None
    m = _OG.search(page)
    if m and "LOGO" not in m.group(1).upper():
        out["image"] = html.unescape(m.group(1))
    return out


def list_recent(client: httpx.Client, max_pages: int = 8, per_page: int = 50) -> list[dict]:
    items = []
    for page in range(1, max_pages + 1):
        r = client.get(f"{BASE}/wp-json/wp/v2/event", params={"per_page": per_page, "page": page, "orderby": "modified", "order": "desc", "_fields": "id,date,modified,link,title,status"})
        if r.status_code == 400:   # past the last page
            break
        r.raise_for_status()
        batch = r.json()
        items.extend(batch)
        if len(batch) < per_page:
            break
        time.sleep(0.5)
    return items


def collect(delay: float = 1.0, max_pages: int = 8, lookback_days: int | None = 120) -> dict:
    """Store new or changed events; skip pages we already have at the same modified stamp.
    lookback_days=None walks the whole catalogue (one-off backfill: future events may have been posted months ago)."""
    init_db()
    fetched_at = datetime.utcnow().replace(microsecond=0)
    cutoff = datetime.utcnow() - timedelta(days=lookback_days) if lookback_days else datetime(1970, 1, 1)
    with httpx.Client(headers={"User-Agent": USER_AGENT, "Accept-Language": "el"}, timeout=30, follow_redirects=True) as client:
        listed = list_recent(client, max_pages=max_pages)
        with SessionLocal() as s:
            known = {e.source_id: e for e in s.execute(select(Event).where(Event.source == SOURCE)).scalars()}
            new = changed = skipped = 0
            stale = datetime.utcnow() - timedelta(days=540)   # posted 18+ months ago and never touched since: surely over
            for n, it in enumerate(listed, 1):
                if it.get("status") != "publish":
                    continue
                sid, modified = str(it["id"]), datetime.fromisoformat(it["modified"])
                if modified < cutoff or modified < stale:
                    continue
                if n % 20 == 0:
                    s.commit()   # keep progress if the run is cut short
                ex = known.get(sid)
                if ex and ex.modified >= modified:
                    skipped += 1
                    continue
                try:
                    r = client.get(it["link"])
                    r.raise_for_status()
                    p = parse_event_page(r.text)
                except Exception as e:  # noqa: BLE001
                    log.warning("event %s: %s", sid, e)
                    continue
                time.sleep(delay)
                if not p["starts_at"]:
                    continue
                title = _text(it["title"]["rendered"])
                if ex:
                    for k in ("starts_at", "ends_at", "venue", "lat", "lng", "categories", "price", "image"):
                        setattr(ex, k, p[k])
                    ex.title, ex.url, ex.modified, ex.fetched_at = title, it["link"], modified, fetched_at
                    changed += 1
                else:
                    s.add(Event(source=SOURCE, source_id=sid, title=title, url=it["link"], modified=modified, fetched_at=fetched_at,
                                **{k: p[k] for k in ("starts_at", "ends_at", "venue", "lat", "lng", "categories", "price", "image")}))
                    new += 1
            s.commit()
    return {"listed": len(listed), "new": new, "changed": changed, "unchanged": skipped}


def upcoming_near(lat: float, lng: float, now: datetime, days: int = 14, radius_km: float = 3.0, limit: int = 20) -> list[dict]:
    from simera.geo import haversine_km
    with SessionLocal() as s:
        rows = s.execute(select(Event).where(Event.starts_at >= now - timedelta(hours=3), Event.starts_at <= now + timedelta(days=days), Event.lat.isnot(None)).order_by(Event.starts_at)).scalars().all()
    out = []
    for e in rows:
        d = haversine_km(lat, lng, e.lat, e.lng)
        if d <= radius_km:
            out.append({"title": e.title, "url": e.url, "starts_at": e.starts_at.isoformat(), "ends_at": e.ends_at.isoformat() if e.ends_at else None, "venue": e.venue,
                        "lat": e.lat, "lng": e.lng, "distance_km": round(d, 2), "categories": e.categories, "price": e.price, "image": e.image,
                        "maps_url": f"https://www.google.com/maps/search/?api=1&query={e.lat}%2C{e.lng}"})
    return out[:limit]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--delay", type=float, default=1.0)
    p.add_argument("--pages", type=int, default=8)
    p.add_argument("--all", action="store_true", help="walk the whole catalogue once (backfill)")
    a = p.parse_args()
    print(collect(delay=a.delay, max_pages=a.pages, lookback_days=None if a.all else 120))
