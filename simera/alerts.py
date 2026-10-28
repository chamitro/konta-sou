"""Official weather warnings (ΕΜΥ) via the European MeteoAlarm feed, matched to the visitor's region.

Feed: https://feeds.meteoalarm.org/api/v1/warnings/feeds-greece (CAP JSON, Greek and English texts).
Regions are MeteoAlarm EMMA areas; each fuel-bulletin prefecture is mapped to one of them.
"""
from __future__ import annotations

import html
import logging
import threading
import time
from datetime import datetime, timezone

import httpx

from simera.geo import nearest_prefecture

log = logging.getLogger(__name__)
FEED = "https://feeds.meteoalarm.org/api/v1/warnings/feeds-greece"
USER_AGENT = "simera-collector/0.1 (+https://github.com/chamitro/konta-sou)"
TTL = 15 * 60

# MeteoAlarm EMMA area -> fuel-bulletin prefectures (names as in simera.geo.PREFECTURE_CENTROIDS)
REGIONS = {
    "GR001": ["ΝΟΜΟΣ ΛΑΡΙΣΗΣ", "ΝΟΜΟΣ ΜΑΓΝΗΣΙΑΣ", "ΝΟΜΟΣ ΤΡΙΚΑΛΩΝ", "ΝΟΜΟΣ ΚΑΡΔΙΤΣΗΣ"],
    "GR002": ["ΝΟΜΟΣ ΑΙΤΩΛΙΑΣ ΚΑΙ ΑΚΑΡΝΑΝΙΑΣ", "ΝΟΜΟΣ ΕΥΡΥΤΑΝΙΑΣ", "ΝΟΜΟΣ ΦΩΚΙΔΟΣ"],
    "GR003": ["ΝΟΜΟΣ ΦΘΙΩΤΙΔΟΣ", "ΝΟΜΟΣ ΒΟΙΩΤΙΑΣ", "ΝΟΜΟΣ ΕΥΒΟΙΑΣ"],
    "GR004": ["ΝΟΜΟΣ ΕΒΡΟΥ", "ΝΟΜΟΣ ΡΟΔΟΠΗΣ", "ΝΟΜΟΣ ΞΑΝΘΗΣ"],
    "GR005": ["ΝΟΜΟΣ ΔΡΑΜΑΣ", "ΝΟΜΟΣ ΚΑΒΑΛΑΣ", "ΝΟΜΟΣ ΣΕΡΡΩΝ"],
    "GR006": ["ΝΟΜΟΣ ΚΟΖΑΝΗΣ", "ΝΟΜΟΣ ΓΡΕΒΕΝΩΝ", "ΝΟΜΟΣ ΚΑΣΤΟΡΙΑΣ", "ΝΟΜΟΣ ΦΛΩΡΙΝΗΣ"],
    "GR007": ["ΝΟΜΟΣ ΘΕΣΣΑΛΟΝΙΚΗΣ", "ΝΟΜΟΣ ΧΑΛΚΙΔΙΚΗΣ", "ΝΟΜΟΣ ΚΙΛΚΙΣ", "ΝΟΜΟΣ ΠΕΛΛΗΣ", "ΝΟΜΟΣ ΗΜΑΘΙΑΣ", "ΝΟΜΟΣ ΠΙΕΡΙΑΣ"],
    "GR008": ["ΝΟΜΟΣ ΙΩΑΝΝΙΝΩΝ", "ΝΟΜΟΣ ΑΡΤΗΣ", "ΝΟΜΟΣ ΠΡΕΒΕΖΗΣ", "ΝΟΜΟΣ ΘΕΣΠΡΩΤΙΑΣ"],
    "GR009": ["ΝΟΜΟΣ ΑΧΑΪΑΣ", "ΝΟΜΟΣ ΗΛΕΙΑΣ", "ΝΟΜΟΣ ΜΕΣΣΗΝΙΑΣ"],
    "GR010": ["ΝΟΜΟΣ ΚΕΡΚΥΡΑΣ", "ΝΟΜΟΣ ΛΕΥΚΑΔΟΣ", "ΝΟΜΟΣ ΚΕΦΑΛΛΗΝΙΑΣ", "ΝΟΜΟΣ ΖΑΚΥΝΘΟΥ"],
    "GR011": ["ΝΟΜΟΣ ΑΤΤΙΚΗΣ"],
    "GR012": ["ΝΟΜΟΣ ΚΥΚΛΑΔΩΝ"],
    "GR013": ["ΝΟΜΟΣ ΔΩΔΕΚΑΝΗΣΟΥ"],
    "GR014": ["ΝΟΜΟΣ ΛΕΣΒΟΥ", "ΝΟΜΟΣ ΧΙΟΥ", "ΝΟΜΟΣ ΣΑΜΟΥ"],
    "GR015": ["ΝΟΜΟΣ ΚΟΡΙΝΘΙΑΣ", "ΝΟΜΟΣ ΑΡΓΟΛΙΔΟΣ", "ΝΟΜΟΣ ΑΡΚΑΔΙΑΣ", "ΝΟΜΟΣ ΛΑΚΩΝΙΑΣ"],
    "GR016": ["ΝΟΜΟΣ ΗΡΑΚΛΕΙΟΥ", "ΝΟΜΟΣ ΧΑΝΙΩΝ", "ΝΟΜΟΣ ΡΕΘΥΜΝΗΣ", "ΝΟΜΟΣ ΛΑΣΙΘΙΟΥ"],
}
PREFECTURE_REGION = {p: code for code, ps in REGIONS.items() for p in ps}
LEVELS = {"2": "yellow", "3": "orange", "4": "red"}

_cache: dict = {"at": 0.0, "warnings": []}
_lock = threading.Lock()


def _parse(feed: dict) -> list[dict]:
    out = []
    for w in feed.get("warnings", []):
        alert = w.get("alert", {})
        info = next((i for i in alert.get("info", []) if i.get("language") == "el-GR"), None) or next(iter(alert.get("info", [])), None)
        if not info:
            continue
        level = next((p["value"].split(";")[0].strip() for p in info.get("parameter", []) if p.get("valueName") == "awareness_level"), "2")
        kind = next((p["value"].split(";")[-1].strip() for p in info.get("parameter", []) if p.get("valueName") == "awareness_type"), "")
        codes = [g["value"] for a in info.get("area", []) for g in a.get("geocode", [])]
        out.append({
            "id": w.get("uuid"), "regions": codes, "area": html.unescape(info["area"][0]["areaDesc"]) if info.get("area") else "",
            "event": html.unescape(info.get("event", "")), "kind": kind, "level": LEVELS.get(level, "yellow"), "severity": info.get("severity"),
            "headline": html.unescape(info.get("headline", "")), "description": html.unescape(info.get("description", "")).strip(),
            "onset": info.get("onset"), "expires": info.get("expires"), "msg_type": alert.get("msgType"), "references": alert.get("references"),
        })
    return out


def all_warnings(force: bool = False) -> list[dict]:
    with _lock:
        if not force and time.time() - _cache["at"] < TTL:
            return _cache["warnings"]
        try:
            with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=20) as c:
                r = c.get(FEED)
                r.raise_for_status()
                _cache.update(at=time.time(), warnings=_parse(r.json()))
        except Exception as e:  # noqa: BLE001
            log.warning("meteoalarm: %s", e)
            _cache["at"] = time.time() - TTL + 120  # retry in two minutes, keep what we had
        return _cache["warnings"]


def active_for(lat: float, lng: float, now: datetime | None = None) -> dict:
    """Warnings for the region around a point that are active now or start within 24 h."""
    now = now or datetime.now(timezone.utc)
    pref = nearest_prefecture(lat, lng)
    region = PREFECTURE_REGION.get(pref)
    ws = all_warnings()
    superseded = {w["references"].split(",")[-1] for w in ws if w.get("references")}
    out = []
    for w in ws:
        if region not in w["regions"] or w["id"] in superseded:
            continue
        try:
            exp = datetime.fromisoformat(w["expires"].replace("Z", "+00:00"))
            onset = datetime.fromisoformat(w["onset"].replace("Z", "+00:00"))
        except Exception:  # noqa: BLE001
            continue
        if exp < now or (onset - now).total_seconds() > 86400:
            continue
        out.append({k: w[k] for k in ("event", "kind", "level", "headline", "description", "onset", "expires", "area")})
    out.sort(key=lambda w: ({"red": 0, "orange": 1, "yellow": 2}[w["level"]], w["onset"]))
    return {"region": region, "prefecture": pref, "warnings": out, "fetched_at": _cache["at"]}
