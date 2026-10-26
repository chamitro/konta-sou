"""Location helpers: distance, nearest fuel-bulletin prefecture, reverse geocoding (Nominatim), opening hours."""
from __future__ import annotations

import json
import math
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx

ATHENS = ZoneInfo("Europe/Athens")
USER_AGENT = "simera/0.1 (near-you app for Greece; contact: project owner)"

# Approximate centroids of the 51 prefectures as named in the fuelprices.gr bulletins.
PREFECTURE_CENTROIDS = {
    "ΝΟΜΟΣ ΑΤΤΙΚΗΣ": (38.00, 23.75), "ΝΟΜΟΣ ΑΙΤΩΛΙΑΣ ΚΑΙ ΑΚΑΡΝΑΝΙΑΣ": (38.60, 21.40), "ΝΟΜΟΣ ΑΡΓΟΛΙΔΟΣ": (37.60, 22.80),
    "ΝΟΜΟΣ ΑΡΚΑΔΙΑΣ": (37.50, 22.35), "ΝΟΜΟΣ ΑΡΤΗΣ": (39.15, 21.00), "ΝΟΜΟΣ ΑΧΑΪΑΣ": (38.15, 21.85), "ΝΟΜΟΣ ΒΟΙΩΤΙΑΣ": (38.40, 23.10),
    "ΝΟΜΟΣ ΓΡΕΒΕΝΩΝ": (40.05, 21.40), "ΝΟΜΟΣ ΔΡΑΜΑΣ": (41.20, 24.20), "ΝΟΜΟΣ ΔΩΔΕΚΑΝΗΣΟΥ": (36.40, 27.50), "ΝΟΜΟΣ ΕΒΡΟΥ": (41.10, 26.10),
    "ΝΟΜΟΣ ΕΥΒΟΙΑΣ": (38.55, 23.90), "ΝΟΜΟΣ ΕΥΡΥΤΑΝΙΑΣ": (38.95, 21.70), "ΝΟΜΟΣ ΖΑΚΥΝΘΟΥ": (37.78, 20.85), "ΝΟΜΟΣ ΗΛΕΙΑΣ": (37.75, 21.50),
    "ΝΟΜΟΣ ΗΜΑΘΙΑΣ": (40.55, 22.20), "ΝΟΜΟΣ ΗΡΑΚΛΕΙΟΥ": (35.20, 25.10), "ΝΟΜΟΣ ΘΕΣΠΡΩΤΙΑΣ": (39.50, 20.40), "ΝΟΜΟΣ ΘΕΣΣΑΛΟΝΙΚΗΣ": (40.65, 23.00),
    "ΝΟΜΟΣ ΙΩΑΝΝΙΝΩΝ": (39.70, 20.80), "ΝΟΜΟΣ ΚΑΒΑΛΑΣ": (41.00, 24.50), "ΝΟΜΟΣ ΚΑΡΔΙΤΣΗΣ": (39.30, 21.90), "ΝΟΜΟΣ ΚΑΣΤΟΡΙΑΣ": (40.50, 21.30),
    "ΝΟΜΟΣ ΚΕΡΚΥΡΑΣ": (39.60, 19.85), "ΝΟΜΟΣ ΚΕΦΑΛΛΗΝΙΑΣ": (38.20, 20.55), "ΝΟΜΟΣ ΚΙΛΚΙΣ": (41.00, 22.90), "ΝΟΜΟΣ ΚΟΖΑΝΗΣ": (40.30, 21.80),
    "ΝΟΜΟΣ ΚΟΡΙΝΘΙΑΣ": (37.90, 22.70), "ΝΟΜΟΣ ΚΥΚΛΑΔΩΝ": (37.10, 25.20), "ΝΟΜΟΣ ΛΑΚΩΝΙΑΣ": (36.90, 22.60), "ΝΟΜΟΣ ΛΑΡΙΣΗΣ": (39.60, 22.40),
    "ΝΟΜΟΣ ΛΑΣΙΘΙΟΥ": (35.15, 25.80), "ΝΟΜΟΣ ΛΕΣΒΟΥ": (39.20, 26.20), "ΝΟΜΟΣ ΛΕΥΚΑΔΟΣ": (38.75, 20.65), "ΝΟΜΟΣ ΜΑΓΝΗΣΙΑΣ": (39.30, 22.95),
    "ΝΟΜΟΣ ΜΕΣΣΗΝΙΑΣ": (37.10, 21.90), "ΝΟΜΟΣ ΞΑΝΘΗΣ": (41.20, 24.90), "ΝΟΜΟΣ ΠΕΛΛΗΣ": (40.85, 22.10), "ΝΟΜΟΣ ΠΙΕΡΙΑΣ": (40.25, 22.45),
    "ΝΟΜΟΣ ΠΡΕΒΕΖΗΣ": (39.10, 20.70), "ΝΟΜΟΣ ΡΕΘΥΜΝΗΣ": (35.30, 24.50), "ΝΟΜΟΣ ΡΟΔΟΠΗΣ": (41.10, 25.50), "ΝΟΜΟΣ ΣΑΜΟΥ": (37.75, 26.80),
    "ΝΟΜΟΣ ΣΕΡΡΩΝ": (41.10, 23.55), "ΝΟΜΟΣ ΤΡΙΚΑΛΩΝ": (39.60, 21.70), "ΝΟΜΟΣ ΦΘΙΩΤΙΔΟΣ": (38.85, 22.50), "ΝΟΜΟΣ ΦΛΩΡΙΝΗΣ": (40.75, 21.40),
    "ΝΟΜΟΣ ΦΩΚΙΔΟΣ": (38.50, 22.40), "ΝΟΜΟΣ ΧΑΛΚΙΔΙΚΗΣ": (40.30, 23.50), "ΝΟΜΟΣ ΧΑΝΙΩΝ": (35.40, 24.00), "ΝΟΜΟΣ ΧΙΟΥ": (38.40, 26.00),
}


def haversine_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p = math.pi / 180
    a = 0.5 - math.cos((lat2 - lat1) * p) / 2 + math.cos(lat1 * p) * math.cos(lat2 * p) * (1 - math.cos((lng2 - lng1) * p)) / 2
    return 12742 * math.asin(math.sqrt(a))


def nearest_prefecture(lat: float, lng: float) -> str:
    """Prefecture (bulletin naming) whose centroid is closest. Good enough for picking a fuel price table."""
    return min(PREFECTURE_CENTROIDS, key=lambda k: haversine_km(lat, lng, *PREFECTURE_CENTROIDS[k]))


# ---- reverse geocoding (Nominatim, OSM) -----------------------------------
_geo_cache: dict[tuple[float, float], tuple[float, dict]] = {}
_last_nominatim = 0.0


def reverse_geocode(lat: float, lng: float) -> dict:
    """{'place': neighbourhood or town, 'municipality': ..., 'display': 'Κυψέλη, Αθήνα'}; cached ~1 day per ~100 m cell.
    Respects Nominatim's 1 request/second policy. Returns {} on failure."""
    global _last_nominatim
    key = (round(lat, 3), round(lng, 3))
    now = time.time()
    if key in _geo_cache and _geo_cache[key][0] > now:
        return _geo_cache[key][1]
    wait = 1.1 - (now - _last_nominatim)
    if wait > 0:
        time.sleep(wait)
    _last_nominatim = time.time()
    try:
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=10) as c:
            r = c.get("https://nominatim.openstreetmap.org/reverse", params={"lat": lat, "lon": lng, "format": "jsonv2", "accept-language": "el", "zoom": 16})
            r.raise_for_status()
            a = r.json().get("address", {})
    except Exception:
        return {}
    place = a.get("neighbourhood") or a.get("suburb") or a.get("quarter") or a.get("village") or a.get("town") or a.get("city") or ""
    town = a.get("city") or a.get("town") or a.get("municipality") or ""
    out = {"place": place, "municipality": a.get("municipality") or town, "display": ", ".join(x for x in dict.fromkeys([place, town]) if x)}
    _geo_cache[key] = (now + 86400, out)
    return out


# ---- OSM opening_hours (minimal) -----------------------------------------------
_DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]
_RULE_RE = re.compile(r"^(?P<days>(?:(?:Mo|Tu|We|Th|Fr|Sa|Su|PH|SH)(?:-(?:Mo|Tu|We|Th|Fr|Sa|Su))?,?)+)?\s*(?P<times>(?:\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2},?\s*)+|off|closed)?$")


def _expand_days(spec: str | None) -> set[int]:
    if not spec:
        return set(range(7))
    out: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if part in ("PH", "SH") or not part:
            continue
        if "-" in part:
            a, b = part.split("-")
            ia, ib = _DAYS.index(a), _DAYS.index(b)
            out |= set(range(ia, ib + 1)) if ia <= ib else set(range(ia, 7)) | set(range(0, ib + 1))
        else:
            out.add(_DAYS.index(part))
    return out


def is_open_now(opening_hours: str | None, at: datetime | None = None) -> bool | None:
    """True/False for common OSM opening_hours strings ('24/7', 'Mo-Fr 08:00-20:00; Sa 09:00-15:00',
    'Mo-Su 07:00-01:00'), None when the string is absent or too complex to judge."""
    if not opening_hours:
        return None
    s = opening_hours.strip()
    if s == "24/7":
        return True
    now = at or datetime.now(ATHENS)
    today, minutes = now.weekday(), now.hour * 60 + now.minute
    result: bool | None = None
    matched_any = False
    for rule in [r.strip() for r in s.split(";") if r.strip()]:
        m = _RULE_RE.match(rule)
        if not m:
            return None
        days = _expand_days(m.group("days"))
        times = (m.group("times") or "").strip()
        if times in ("off", "closed"):
            if today in days:
                result, matched_any = False, True
            continue
        for a, b in re.findall(r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})", times):
            ta = int(a[:a.index(":")]) * 60 + int(a[a.index(":") + 1:])
            tb = int(b[:b.index(":")]) * 60 + int(b[b.index(":") + 1:])
            if tb <= ta:  # past midnight
                if (today in days and minutes >= ta) or ((today - 1) % 7 in days and minutes < tb):
                    return True
                if today in days:
                    matched_any, result = True, (result or False)
            elif today in days:
                matched_any = True
                if ta <= minutes < tb:
                    return True
                result = result or False
    return result if matched_any else False
