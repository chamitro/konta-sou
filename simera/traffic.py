"""Attiki Odos live traffic: 600 vehicle-detection sensors published every minute (ODbL) on data.nap.gov.gr."""
from __future__ import annotations

import json
import logging
import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import httpx

from simera.geo import haversine_km

log = logging.getLogger(__name__)
FEED = "https://nap.imet.gr/attiki-odos/attiki-odos.xml"
USER_AGENT = "simera-collector/0.1 (+https://github.com/chamitro/konta-sou)"
TTL = 60
SENSORS_FILE = Path(__file__).resolve().parent / "data" / "attiki_odos_vds.json"
ATTICA = (37.8, 38.2, 23.3, 24.2)   # drop sensors whose metadata coordinates are broken

_sensors: dict[str, dict] | None = None
_cache: dict = {"at": 0.0, "readings": {}, "stamp": None}
_lock = threading.Lock()


def sensors() -> dict[str, dict]:
    global _sensors
    if _sensors is None:
        rows = json.loads(SENSORS_FILE.read_text(encoding="utf-8"))["sensors"]
        _sensors = {r["id"]: r for r in rows if ATTICA[0] <= r["lat"] <= ATTICA[1] and ATTICA[2] <= r["lng"] <= ATTICA[3]}
    return _sensors


def readings(force: bool = False) -> tuple[dict[str, dict], str | None]:
    with _lock:
        if force or time.time() - _cache["at"] >= TTL:
            try:
                with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20) as c:
                    r = c.get(FEED)
                    r.raise_for_status()
                root = ET.fromstring(r.content)
                data, stamp = {}, None
                for el in root.iter("vdsData"):
                    a = el.attrib
                    stamp = stamp or a.get("timestamp")
                    data[a.get("unitID")] = {"speed": int(float(a.get("speed", 0))), "flow": int(float(a.get("trafficFlow", 0))), "occupancy": int(float(a.get("occupancy", 0))), "status": a.get("status"), "timestamp": a.get("timestamp")}
                _cache.update(at=time.time(), readings=data, stamp=stamp)
            except Exception as e:  # noqa: BLE001
                log.warning("attiki odos feed: %s", e)
                _cache["at"] = time.time() - TTL + 20
        return _cache["readings"], _cache["stamp"]


def level(speed: int, flow: int) -> str:
    """Motorway: ≥70 km/h free, 40–69 slow, <40 jammed; a sensor with no vehicles says nothing."""
    if flow <= 0 or speed <= 0:   # no vehicles, or a sensor reporting 0 km/h with traffic: not a reading we can trust
        return "none"
    return "free" if speed >= 70 else "slow" if speed >= 40 else "jam"


def near(lat: float, lng: float, max_km: float = 4.0, limit: int = 8) -> dict:
    data, stamp = readings()
    rows = []
    for sid, s in sensors().items():
        d = haversine_km(lat, lng, s["lat"], s["lng"])
        if d > max_km:
            continue
        r = data.get(sid)
        if not r or r.get("status") != "1":
            continue
        rows.append({"id": sid, "name": s["name"], "road": s["road"], "lat": s["lat"], "lng": s["lng"], "distance_km": round(d, 2),
                     "speed": r["speed"], "flow": r["flow"], "level": level(r["speed"], r["flow"])})
    rows.sort(key=lambda x: x["distance_km"])
    counted = [x for x in rows if x["level"] != "none"]
    overall = "none" if not counted else "jam" if sum(x["level"] == "jam" for x in counted) >= max(1, len(counted) // 3) else "slow" if any(x["level"] != "free" for x in counted) else "free"
    whole = [level(r["speed"], r["flow"]) for r in data.values() if r.get("status") == "1"]
    whole = [w for w in whole if w != "none"]
    return {"timestamp": stamp, "near": rows[:limit], "overall": overall,
            "avg_speed": round(sum(x["speed"] for x in counted) / len(counted)) if counted else None,
            "motorway": {"sensors": len(whole), "jam": whole.count("jam"), "slow": whole.count("slow"), "free": whole.count("free")}}
