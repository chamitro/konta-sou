"""Nearby places from OpenStreetMap via the Overpass API, cached in the database.

Overpass public servers are shared and rate limited; results are cached per ~100 m cell,
category and radius for several hours. For production, point OVERPASS_URL at a mirror or
your own instance.
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta

import math

import httpx
from sqlalchemy import func, select

from simera.db import SessionLocal
from simera.geo import USER_AGENT, haversine_km, is_open_now
from simera.categories import CATEGORIES
from simera.models import OsmCache, Poi

log = logging.getLogger(__name__)

DEFAULT_MIRRORS = ",".join([
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
])
OVERPASS_URLS = [u for u in os.environ.get("OVERPASS_URL", DEFAULT_MIRRORS).split(",") if u]
REQUEST_TIMEOUT = float(os.environ.get("OVERPASS_TIMEOUT", "30"))
CACHE_TTL = timedelta(hours=6)

def _query(category: str, lat: float, lng: float, radius: int) -> str:
    f = CATEGORIES[category]["filter"]
    return f"[out:json][timeout:20];nwr{f}(around:{radius},{lat:.5f},{lng:.5f});out center tags;"


def _fetch(q: str) -> list[dict]:
    last_err: Exception | None = None
    for url in OVERPASS_URLS:
        try:
            with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=REQUEST_TIMEOUT) as c:
                r = c.post(url, data={"data": q})
                if r.status_code == 200:
                    return r.json().get("elements", [])
                last_err = RuntimeError(f"{url}: HTTP {r.status_code}")
                log.warning("overpass %s: HTTP %s", url, r.status_code)
        except Exception as e:  # noqa: BLE001
            last_err = e
            log.warning("overpass %s: %s", url, e)
    raise RuntimeError(f"Overpass unavailable: {last_err}")


def _poi_to_item(p: Poi, lat: float, lng: float, category: str) -> dict:
    extra = json.loads(p.extra) if p.extra else {}
    return {
        "id": f"{p.osm_type}{p.osm_id}", "name": p.name or p.brand or CATEGORIES[category]["label"], "brand": p.brand or None,
        "address": p.address or None, "lat": p.lat, "lng": p.lng, "distance_km": round(haversine_km(lat, lng, p.lat, p.lng), 2),
        "opening_hours": p.opening_hours or None, "open_now": is_open_now(p.opening_hours or None),
        "phone": p.phone or None, "website": p.website or None, "cuisine": p.cuisine or None, "wheelchair": extra.get("wheelchair"),
        "maps_url": f"https://www.google.com/maps/search/?api=1&query={p.lat}%2C{p.lng}",
        "osm_url": f"https://www.openstreetmap.org/{ {'n': 'node', 'w': 'way', 'r': 'relation'}[p.osm_type] }/{p.osm_id}",
    }


def nearby_from_db(category: str, lat: float, lng: float, radius: int) -> list[dict] | None:
    """None when no POIs have been imported yet (caller falls back to Overpass)."""
    dlat = radius / 111_000
    dlng = radius / (111_000 * max(0.2, math.cos(math.radians(lat))))
    with SessionLocal() as s:
        if s.scalar(select(func.count(Poi.id))) == 0:
            return None
        rows = s.scalars(
            select(Poi).where(Poi.category == category, Poi.lat.between(lat - dlat, lat + dlat), Poi.lng.between(lng - dlng, lng + dlng))
        ).all()
    items = [_poi_to_item(p, lat, lng, category) for p in rows]
    items = [i for i in items if i["distance_km"] * 1000 <= radius]
    items.sort(key=lambda x: x["distance_km"])
    return items


def nearby(category: str, lat: float, lng: float, radius: int = 1000) -> list[dict]:
    if category not in CATEGORIES:
        raise KeyError(category)
    items = nearby_from_db(category, lat, lng, radius)
    if items is not None:
        return items
    return nearby_overpass(category, lat, lng, radius)


def nearby_overpass(category: str, lat: float, lng: float, radius: int = 1000) -> list[dict]:
    key = f"{category}|{round(lat, 3)}|{round(lng, 3)}|{radius}"
    with SessionLocal() as s:
        row = s.scalar(select(OsmCache).where(OsmCache.key == key))
        if row and row.fetched_at > datetime.utcnow() - CACHE_TTL:
            elements = json.loads(row.payload)
        else:
            elements = _fetch(_query(category, lat, lng, radius))
            if row:
                row.payload, row.fetched_at = json.dumps(elements), datetime.utcnow()
            else:
                s.add(OsmCache(key=key, payload=json.dumps(elements), fetched_at=datetime.utcnow()))
            s.commit()
    out = []
    for e in elements:
        t = e.get("tags", {})
        plat, plng = (e.get("lat"), e.get("lon")) if "lat" in e else (e.get("center", {}).get("lat"), e.get("center", {}).get("lon"))
        if plat is None:
            continue
        name = t.get("name") or t.get("brand") or t.get("operator") or CATEGORIES[category]["label"][:-1]
        addr = " ".join(x for x in [t.get("addr:street"), t.get("addr:housenumber")] if x)
        out.append(
            {
                "id": f"{e['type'][0]}{e['id']}", "name": name, "brand": t.get("brand"), "address": addr or None,
                "lat": plat, "lng": plng, "distance_km": round(haversine_km(lat, lng, plat, plng), 2),
                "opening_hours": t.get("opening_hours"), "open_now": is_open_now(t.get("opening_hours")),
                "phone": t.get("phone") or t.get("contact:phone"), "website": t.get("website") or t.get("contact:website"),
                "cuisine": t.get("cuisine"), "wheelchair": t.get("wheelchair"),
                "maps_url": f"https://www.google.com/maps/search/?api=1&query={plat}%2C{plng}",
                "osm_url": f"https://www.openstreetmap.org/{e['type']}/{e['id']}",
            }
        )
    out.sort(key=lambda x: x["distance_km"])
    return out
