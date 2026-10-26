from __future__ import annotations

from datetime import date, timedelta

from fastapi import FastAPI, HTTPException, Query
from sqlalchemy import func, select

from simera import oasa
from simera.db import SessionLocal, init_db
from simera.models import FuelPrice

import os  # noqa: E402

from fastapi.middleware.cors import CORSMiddleware  # noqa: E402

app = FastAPI(title="Κοντά σου API", version="0.2")
# The page may be served from another origin (e.g. GitHub Pages); restrict with ALLOWED_ORIGINS="https://a.b,https://c.d"
app.add_middleware(CORSMiddleware, allow_origins=[o for o in os.environ.get("ALLOWED_ORIGINS", "*").split(",") if o], allow_methods=["GET"], allow_headers=["*"])


@app.on_event("startup")
def _startup() -> None:
    init_db()
    from simera.scheduler import start_if_enabled

    start_if_enabled()


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}


# ---- fuel -----------------------------------------------------------------

@app.get("/api/fuel/latest")
def fuel_latest():
    """Latest available day: every prefecture, every fuel type, plus change vs 7 days earlier."""
    with SessionLocal() as s:
        latest = s.scalar(select(func.max(FuelPrice.price_date)))
        if not latest:
            raise HTTPException(503, "no fuel data collected yet")
        week_ago = s.scalar(select(func.max(FuelPrice.price_date)).where(FuelPrice.price_date <= latest - timedelta(days=7)))
        rows = s.scalars(select(FuelPrice).where(FuelPrice.price_date == latest)).all()
        prev = {}
        if week_ago:
            prev = {(r.prefecture, r.fuel_type): r.price for r in s.scalars(select(FuelPrice).where(FuelPrice.price_date == week_ago))}
    by_pref: dict[str, dict] = {}
    for r in rows:
        p = prev.get((r.prefecture, r.fuel_type))
        by_pref.setdefault(r.prefecture, {})[r.fuel_type] = {
            "price": r.price,
            "change_7d": round(r.price - p, 3) if p is not None else None,
        }
    return {"date": latest.isoformat(), "compared_to": week_ago.isoformat() if week_ago else None, "prefectures": by_pref}


@app.get("/api/fuel/history")
def fuel_history(prefecture: str = "ΝΟΜΟΣ ΑΤΤΙΚΗΣ", fuel: str = "unleaded_95", days: int = Query(90, le=3650)):
    since = date.today() - timedelta(days=days)
    with SessionLocal() as s:
        rows = s.execute(
            select(FuelPrice.price_date, FuelPrice.price)
            .where(FuelPrice.prefecture == prefecture, FuelPrice.fuel_type == fuel, FuelPrice.price_date >= since)
            .order_by(FuelPrice.price_date)
        ).all()
    return {"prefecture": prefecture, "fuel": fuel, "points": [{"date": d.isoformat(), "price": p} for d, p in rows]}


@app.get("/api/fuel/prefectures")
def fuel_prefectures():
    with SessionLocal() as s:
        return sorted(s.scalars(select(FuelPrice.prefecture).distinct()).all())


# ---- transit (Athens) -----------------------------------------------------

@app.get("/api/transit/stops/near")
def stops_near(lat: float, lng: float):
    stops = oasa.closest_stops(lat, lng)
    return [
        {"code": s["StopCode"], "name": s["StopDescr"], "street": s.get("StopStreet"), "lat": float(s["StopLat"]), "lng": float(s["StopLng"]), "distance_km": round(float(s["distance"]), 3)}
        for s in stops
    ]


@app.get("/api/transit/stops/{stop_code}/arrivals")
def stop_arrivals(stop_code: str):
    return {"stop": stop_code, "arrivals": oasa.arrivals_with_lines(stop_code)}


@app.get("/api/transit/stops/{stop_code}/routes")
def stop_routes(stop_code: str):
    return [{"line": r["LineID"], "route_code": r["RouteCode"], "destination": r["RouteDescr"]} for r in oasa.routes_for_stop(stop_code)]




# ---- metro / tram (Athens, GTFS) -------------------------------------------

from simera import rail  # noqa: E402


@app.get("/api/transit/rail/near")
def rail_near(lat: float, lng: float, limit: int = Query(3, le=10)):
    """Nearest metro/tram stations with the next scheduled departures (timetable, not live)."""
    return rail.stations_near(lat, lng, limit=limit)


# ---- pharmacies (Attica) --------------------------------------------------

import math  # noqa: E402
from datetime import datetime  # noqa: E402
from zoneinfo import ZoneInfo  # noqa: E402

from simera.models import Pharmacy, PharmacyDuty  # noqa: E402

ATHENS = ZoneInfo("Europe/Athens")


def _haversine_km(lat1, lng1, lat2, lng2):
    p = math.pi / 180
    a = 0.5 - math.cos((lat2 - lat1) * p) / 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lng2 - lng1) * p)) / 2
    return 12742 * math.asin(math.sqrt(a))


@app.get("/api/pharmacies/on-duty")
def pharmacies_on_duty(lat: float, lng: float, at: datetime | None = None, limit: int = Query(10, le=50)):
    """Pharmacies on duty near a point at a given moment (default: now, Athens time).

    Checks today's and yesterday's rota, because night duties run past midnight.
    """
    now = (at or datetime.now(ATHENS)).astimezone(ATHENS) if (at is None or at.tzinfo) else at.replace(tzinfo=ATHENS)
    today = now.date()
    candidates = []
    with SessionLocal() as s:
        for day in (today, today - timedelta(days=1)):
            minutes = (now - datetime.combine(day, datetime.min.time(), tzinfo=ATHENS)).total_seconds() / 60
            duties = s.execute(select(PharmacyDuty, Pharmacy).join(Pharmacy, Pharmacy.id == PharmacyDuty.pharmacy_id).where(PharmacyDuty.duty_date == day)).all()
            for duty, ph in duties:
                open_now = False
                next_open = None
                for iv in duty.intervals.split(";"):
                    if not iv:
                        continue
                    a, b = map(int, iv.split("-"))
                    if a <= minutes < b:
                        open_now = True
                    elif minutes < a and (next_open is None or a < next_open):
                        next_open = a
                if not open_now and (day != today or next_open is None):
                    continue
                candidates.append(
                    {
                        "id": ph.id, "name": ph.name, "address": ph.address, "area": ph.area, "phone": ph.phone,
                        "lat": ph.lat, "lng": ph.lng, "distance_km": round(_haversine_km(lat, lng, ph.lat, ph.lng), 2),
                        "hours": duty.hours_text, "open_now": open_now,
                        "opens_in_min": None if open_now or next_open is None else int(next_open - minutes),
                        "duty_date": day.isoformat(),
                        "maps_url": f"https://www.google.com/maps/search/?api=1&query={ph.lat}%2C{ph.lng}",
                    }
                )
        latest = s.scalar(select(func.max(PharmacyDuty.duty_date)))
    candidates.sort(key=lambda c: (not c["open_now"], c["distance_km"]))
    return {"at": now.isoformat(), "data_until": latest.isoformat() if latest else None, "pharmacies": candidates[:limit]}



# ---- hospitals (Attica) ---------------------------------------------------

from simera.collectors.hospitals import hospital_info  # noqa: E402
from simera.models import HealthCenterDuty, HospitalDuty, HospitalRota  # noqa: E402


@app.get("/api/hospitals/on-duty")
def hospitals_on_duty(day: date | None = None, lat: float | None = None, lng: float | None = None, specialty: str | None = None):
    """Attica hospital duty rota for a day (default: today, Athens time), optionally one specialty,
    with distance from (lat, lng) when the hospital is in our directory."""
    day = day or datetime.now(ATHENS).date()
    with SessionLocal() as s:
        rota = s.scalar(select(HospitalRota).where(HospitalRota.duty_date == day))
        if not rota:
            latest = s.scalar(select(func.max(HospitalRota.duty_date)))
            raise HTTPException(404, f"no rota for {day}; latest available: {latest}")
        q = select(HospitalDuty).where(HospitalDuty.duty_date == day)
        if specialty:
            q = q.where(HospitalDuty.specialty == specialty)
        duties = s.scalars(q).all()
        specialties = sorted(s.scalars(select(HospitalDuty.specialty).where(HospitalDuty.duty_date == day).distinct()).all(), key=lambda x: x.lower())
        hcs = s.scalars(select(HealthCenterDuty).where(HealthCenterDuty.duty_date == day)).all()

    def enrich(key: str) -> dict:
        info = hospital_info(key) if key else None
        if not info:
            return {"name": None, "address": None, "lat": None, "lng": None, "distance_km": None, "maps_url": None}
        dist = round(_haversine_km(lat, lng, info["lat"], info["lng"]), 1) if lat is not None and lng is not None else None
        return {"name": info["name"], "address": info.get("address"), "lat": info["lat"], "lng": info["lng"], "distance_km": dist,
                "maps_url": f"https://www.google.com/maps/search/?api=1&query={info['lat']}%2C{info['lng']}"}

    entries = [{"specialty": d.specialty, "shift": d.shift, "hospital": d.hospital, "region": d.region, "note": d.note, "key": d.hospital_key, **enrich(d.hospital_key)} for d in duties]
    entries.sort(key=lambda e: (e["specialty"].lower(), e["shift"], e["distance_km"] if e["distance_km"] is not None else 999))
    return {
        "date": day.isoformat(),
        "specialties": specialties,
        "health_centers": [{"name": h.name, "hours": h.hours, **enrich(h.hospital_key)} for h in hcs],
        "entries": entries,
        "coordinates_note": "Hospital coordinates are approximate.",
    }



# ---- location & nearby places --------------------------------------------------

from simera import osm  # noqa: E402
from simera.geo import nearest_prefecture, reverse_geocode  # noqa: E402


@app.get("/api/location")
def location(lat: float, lng: float):
    """What we know about a point: neighbourhood name (OSM Nominatim) and the fuel-bulletin prefecture."""
    return {"prefecture": nearest_prefecture(lat, lng), **reverse_geocode(lat, lng)}


@app.get("/api/nearby/categories")
def nearby_categories():
    return [{"key": k, "label": v["label"]} for k, v in osm.CATEGORIES.items()]


@app.get("/api/nearby")
def nearby(lat: float, lng: float, category: str = "fuel", radius: int = Query(1000, ge=100, le=5000), limit: int = Query(20, le=100), accessible: bool = False):
    """Places of one category around a point, nearest first, from OpenStreetMap.
    accessible=true keeps only places tagged wheelchair=yes (or limited)."""
    if category not in osm.CATEGORIES:
        raise HTTPException(404, f"unknown category; see /api/nearby/categories")
    try:
        items = osm.nearby(category, lat, lng, radius)
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    if accessible:
        items = [i for i in items if i.get("wheelchair") in ("yes", "limited")]
    return {"category": category, "label": osm.CATEGORIES[category]["label"], "radius_m": radius, "accessible_only": accessible, "count": len(items), "items": items[:limit],
            "attribution": "© OpenStreetMap contributors (ODbL)"}


# ---- web ------------------------------------------------------------------

from pathlib import Path  # noqa: E402

from fastapi.responses import FileResponse  # noqa: E402

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB_DIR / "index.html")
