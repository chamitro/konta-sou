"""Next metro/tram departures near a point, from the imported GTFS tables."""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta

from sqlalchemy import select

from simera.db import SessionLocal
from simera.geo import ATHENS, haversine_km
from simera.models import RailDepartures, RailFeed, RailService, RailStation


def pick_service(session, today: date) -> tuple[str | None, bool]:
    """(service_id, exact). Exact when the feed has today's date; otherwise the most recent
    feed day of the same kind (weekday / Saturday / Sunday), flagged as indicative."""
    services = session.execute(select(RailService.service_id, RailService.service_date)).all()
    for sid, d in services:
        if d == today:
            return sid, True
    kind = lambda d: 0 if d.weekday() < 5 else d.weekday() - 4  # 0 weekday, 1 Sat, 2 Sun
    same = [(d, sid) for sid, d in services if kind(d) == kind(today)]
    if not same:
        return None, False
    return max(same)[1], False


def stations_near(lat: float, lng: float, limit: int = 3, max_km: float = 2.0, now: datetime | None = None) -> dict:
    now = now or datetime.now(ATHENS)
    today = now.date()
    secs_now = now.hour * 3600 + now.minute * 60 + now.second
    with SessionLocal() as s:
        feed = s.scalar(select(RailFeed).order_by(RailFeed.imported_at.desc()))
        if not feed:
            return {"stations": [], "feed": None}
        dlat, dlng = max_km / 111, max_km / 85
        cands = s.scalars(select(RailStation).where(RailStation.lat.between(lat - dlat, lat + dlat), RailStation.lng.between(lng - dlng, lng + dlng))).all()
        cands = sorted(((haversine_km(lat, lng, st.lat, st.lng), st) for st in cands), key=lambda x: x[0])[:limit]
        sid, exact = pick_service(s, today)
        # after midnight, yesterday's service may still be running (times > 24:00)
        sid_prev, _ = pick_service(s, today - timedelta(days=1))
        out = []
        for dist, st in cands:
            if dist > max_km:
                continue
            deps = []
            for service, offset in ((sid, 0), (sid_prev, -86400)):  # yesterday's service: trips past 24:00 still running
                if not service:
                    continue
                rows = s.scalars(select(RailDepartures).where(RailDepartures.station_id == st.id, RailDepartures.service_id == service)).all()
                for r in rows:
                    nxt = [t + offset - secs_now for t in json.loads(r.times) if 0 <= t + offset - secs_now <= 3 * 3600]
                    for m in nxt[:3]:
                        deps.append({"line": r.line, "destination": r.destination, "minutes": m // 60, "mode": "tram" if r.route_type == 0 else "metro"})
            deps.sort(key=lambda d: d["minutes"])
            out.append({"name": st.name, "lines": st.lines.split(",") if st.lines else [], "lat": st.lat, "lng": st.lng, "distance_km": round(dist, 2),
                        "wheelchair": st.wheelchair or None, "departures": deps[:8]})
        return {
            "stations": out,
            "feed": {"first_date": feed.first_date.isoformat(), "last_date": feed.last_date.isoformat(), "exact_day": exact,
                     "note": None if exact else f"Ενδεικτικά δρομολόγια: το πρόγραμμα που έχει δημοσιευτεί καλύπτει {feed.first_date:%d/%m}–{feed.last_date:%d/%m/%Y}."},
        }
