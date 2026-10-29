from __future__ import annotations

from datetime import date, timedelta

from fastapi import FastAPI, HTTPException, Query
from sqlalchemy import func, select

from simera import oasa
from simera.geo import haversine_km
from simera.db import SessionLocal, init_db
from simera.models import FuelPrice

import logging  # noqa: E402
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
    from urllib.parse import urlsplit
    from simera.collectors import hospitals as _h
    from simera import scheduler
    return {"ok": True, "oasa_via": urlsplit(oasa.API_URL).netloc, "moh_via": urlsplit(_h.MOH_BASE_URL).netloc, "scheduler": scheduler.STATUS}


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

LIVE_UNAVAILABLE = "Τα live δεδομένα ΟΑΣΑ δεν είναι διαθέσιμα από αυτόν τον διακομιστή."


def _oasa(fn, *args):
    try:
        return fn(*args)
    except Exception as e:  # network blocked or OASA down: tell the client instead of a bare 500
        logging.getLogger("simera.api").warning("OASA %s via %s failed: %s", getattr(fn, "__name__", fn), oasa.API_URL, e)
        raise HTTPException(503, LIVE_UNAVAILABLE) from e


@app.get("/api/transit/stops/near")
def stops_near(lat: float, lng: float):
    stops = _oasa(oasa.closest_stops, lat, lng)
    return [
        {"code": s["StopCode"], "name": s["StopDescr"], "street": s.get("StopStreet"), "lat": float(s["StopLat"]), "lng": float(s["StopLng"]), "distance_km": round(haversine_km(lat, lng, float(s["StopLat"]), float(s["StopLng"])), 3)}
        for s in sorted(stops, key=lambda s: haversine_km(lat, lng, float(s["StopLat"]), float(s["StopLng"])))
    ]  # OASA's own "distance" is a Euclidean value in degrees, not km


@app.get("/api/transit/stops/{stop_code}/arrivals")
def stop_arrivals(stop_code: str):
    return {"stop": stop_code, "arrivals": _oasa(oasa.arrivals_with_lines, stop_code)}


@app.get("/api/transit/stops/{stop_code}/routes")
def stop_routes(stop_code: str):
    return [{"line": r["LineID"], "route_code": r["RouteCode"], "destination": r["RouteDescr"]} for r in _oasa(oasa.routes_for_stop, stop_code)]




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
from simera.geo import geocode, nearest_prefecture, reverse_geocode  # noqa: E402


@app.get("/api/location")
def location(lat: float, lng: float):
    """What we know about a point: neighbourhood name (OSM Nominatim) and the fuel-bulletin prefecture."""
    return {"prefecture": nearest_prefecture(lat, lng), **reverse_geocode(lat, lng)}


# ---- your day: weather warnings, Attiki Odos, planned power cuts ------------------------------

from simera import alerts as _alerts, traffic as _traffic  # noqa: E402
from simera.collectors import outages as _outages  # noqa: E402


@app.get("/api/alerts")
def weather_alerts(lat: float, lng: float):
    """ΕΜΥ warnings (via MeteoAlarm) for the region around the point, active now or within 24 h."""
    return _alerts.active_for(lat, lng)


@app.get("/api/traffic/near")
def traffic_near(lat: float, lng: float, max_km: float = Query(4.0, ge=0.5, le=15)):
    """Attiki Odos sensors near the point with live speed, plus the motorway-wide picture (ODbL, data.nap.gov.gr)."""
    return _traffic.near(lat, lng, max_km=max_km)


@app.get("/api/outages")
def power_outages(lat: float, lng: float, municipality_id: int | None = None, days: int = Query(3, ge=1, le=14)):
    """Planned ΔΕΔΔΗΕ power cuts for the municipality around the point (or a chosen one), next few days."""
    now = datetime.now(ATHENS).replace(tzinfo=None)
    if municipality_id:
        matched = [m for m in _outages.MUNICIPALITIES if m["id"] == municipality_id]
    else:
        loc = reverse_geocode(lat, lng)
        names = [loc.get(k) for k in ("municipality", "place") if loc.get(k)]
        matched = _outages.match_municipalities(*names) if names else []
    ids = [m["id"] for m in matched]
    return {"municipalities": [{"id": m["id"], "name": m["name"]} for m in matched], "outages": _outages.upcoming(ids, now, days) if ids else [],
            "all_municipalities": [{"id": m["id"], "name": m["name"]} for m in _outages.MUNICIPALITIES]}


@app.get("/api/events")
def events_near(lat: float, lng: float, days: int = Query(14, ge=1, le=60), radius: int = Query(3000, ge=200, le=20000), limit: int = Query(20, le=100)):
    """Upcoming cultural events near the point, from the City of Athens portal cultureisathens.gr."""
    from simera.collectors import events as _events
    now = datetime.now(ATHENS).replace(tzinfo=None)
    items = _events.upcoming_near(lat, lng, now, days=days, radius_km=radius / 1000, limit=limit)
    return {"radius_m": radius, "days": days, "count": len(items), "items": items, "source": "Culture is Athens (Δήμος Αθηναίων)"}


@app.get("/api/today")
def today(d: date | None = None):
    """Name days today and tomorrow (indicative list of common names, Orthodox calendar)."""
    from simera.namedays import holiday, names_for, next_nameday
    day = d or datetime.now(ATHENS).date()
    nxt = next_nameday(day + timedelta(days=1))
    return {"date": day.isoformat(), "namedays": names_for(day), "tomorrow": names_for(day + timedelta(days=1)),
            "holiday": holiday(day), "next": {"date": nxt[0].isoformat(), "names": nxt[1]} if nxt else None}


@app.get("/api/geocode")
def geocode_endpoint(q: str = Query(..., min_length=2, max_length=120)):
    """Address or area search (Greece only), for browsers that cannot share the device location."""
    return {"results": geocode(q)}


@app.get("/api/nearby/categories")
def nearby_categories():
    return [{"key": k, "label": v["label"]} for k, v in osm.CATEGORIES.items()]


@app.get("/api/nearby")
def nearby(lat: float, lng: float, category: str = "fuel", radius: int = Query(1000, ge=100, le=5000), limit: int = Query(20, le=100), accessible: bool = False,
           open: str | None = Query(None, pattern="^(24h|now)$")):
    """Places of one category around a point, nearest first, from OpenStreetMap.
    accessible=true keeps only places tagged wheelchair=yes (or limited); open=24h keeps places tagged 24/7,
    open=now those whose known hours say they are open right now. Hours are known only for a share of places,
    reported in `with_hours` so the page can say so."""
    if category not in osm.CATEGORIES:
        raise HTTPException(404, f"unknown category; see /api/nearby/categories")
    try:
        items = osm.nearby(category, lat, lng, radius)
    except RuntimeError as e:
        raise HTTPException(503, str(e))
    if accessible:
        items = [i for i in items if i.get("wheelchair") in ("yes", "limited")]
    total, with_hours = len(items), sum(1 for i in items if i.get("opening_hours"))
    if open == "24h":
        items = [i for i in items if "24/7" in (i.get("opening_hours") or "")]
    elif open == "now":
        items = [i for i in items if i.get("open_now") is True]
    for i in items:
        i["all_day"] = "24/7" in (i.get("opening_hours") or "")
    return {"category": category, "label": osm.CATEGORIES[category]["label"], "radius_m": radius, "accessible_only": accessible, "open": open,
            "total": total, "with_hours": with_hours, "count": len(items), "items": items[:limit], "attribution": "© OpenStreetMap contributors (ODbL)"}


# ---- web ------------------------------------------------------------------

from pathlib import Path  # noqa: E402

from fastapi.responses import FileResponse  # noqa: E402

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(WEB_DIR / "index.html")


@app.get("/manifest.webmanifest", include_in_schema=False)
def manifest():
    return FileResponse(WEB_DIR / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
def service_worker():
    return FileResponse(WEB_DIR / "sw.js", media_type="application/javascript")


@app.get("/icons/{name}", include_in_schema=False)
def icon(name: str):
    path = (WEB_DIR / "icons" / name).resolve()
    if path.parent != (WEB_DIR / "icons").resolve() or not path.is_file():
        raise HTTPException(404)
    return FileResponse(path)
