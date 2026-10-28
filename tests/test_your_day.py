import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from simera import alerts, traffic
from simera.collectors import outages

FIX = Path(__file__).parent / "fixtures"


def test_meteoalarm_parse_and_region_filter(monkeypatch):
    ws = alerts._parse(json.loads((FIX / "meteoalarm_sample.json").read_text(encoding="utf-8")))
    assert ws and all(w["regions"] and w["level"] in ("yellow", "orange", "red") for w in ws)
    assert any("Ομίχλη" in w["event"] or "Προειδοποίηση" in w["event"] for w in ws)
    monkeypatch.setattr(alerts, "all_warnings", lambda force=False: ws)
    first = ws[0]
    region = first["regions"][0]
    pref = alerts.REGIONS[region][0]
    from simera.geo import PREFECTURE_CENTROIDS
    lat, lng = PREFECTURE_CENTROIDS[pref]
    at = datetime.fromisoformat(first["onset"].replace("Z", "+00:00"))
    r = alerts.active_for(lat, lng, now=at)
    assert r["region"] == region and r["warnings"] and r["warnings"][0]["level"] in ("yellow", "orange")
    assert not alerts.active_for(lat, lng, now=datetime(2030, 1, 1, tzinfo=timezone.utc))["warnings"]


def test_prefecture_region_map_is_complete():
    from simera.geo import PREFECTURE_CENTROIDS
    missing = [p for p in PREFECTURE_CENTROIDS if p not in alerts.PREFECTURE_REGION]
    assert missing == [], missing


def test_attiki_odos_levels_and_near(monkeypatch):
    root = ET.fromstring((FIX / "attiki_odos_sample.xml").read_text(encoding="utf-8"))
    data = {el.attrib["unitID"]: {"speed": int(el.attrib["speed"]), "flow": int(el.attrib["trafficFlow"]), "occupancy": 0, "status": el.attrib["status"], "timestamp": el.attrib["timestamp"]} for el in root.iter("vdsData")}
    assert traffic.level(90, 500) == "free" and traffic.level(55, 500) == "slow" and traffic.level(10, 500) == "jam" and traffic.level(0, 0) == "none"
    monkeypatch.setattr(traffic, "readings", lambda force=False: (data, "2026-10-28T17:48:00"))
    sens = traffic.sensors()
    sid = next(s for s in data if s in sens)
    r = traffic.near(sens[sid]["lat"], sens[sid]["lng"], max_km=2)
    assert r["timestamp"] == "2026-10-28T17:48:00" and r["near"] and r["near"][0]["distance_km"] == 0.0
    assert r["overall"] in ("free", "slow", "jam", "none") and set(r["motorway"]) == {"sensors", "jam", "slow", "free"}


def test_sensor_file_covers_attica():
    s = traffic.sensors()
    assert len(s) > 400 and all(37.8 <= v["lat"] <= 38.2 for v in s.values())


def test_deddie_table_and_datetimes():
    rows, pages = outages.parse_table((FIX / "deddie_athens.html").read_text(encoding="utf-8"))
    assert pages == 3 and len(rows) >= 5
    r = rows[0]
    assert r["municipality"] == "ΑΘΗΝΑΙΩΝ" and r["starts_at"] == datetime(2026, 10, 29, 8, 0) and r["ends_at"] == datetime(2026, 10, 29, 13, 0)
    assert r["note_no"] == "701" and r["purpose"] == "Κατασκευές" and "ΜΗΛΙΑΡΑΚΗ" in r["area"]
    assert outages.parse_dt("29/10/2026 12:30:00 πμ") == datetime(2026, 10, 29, 0, 30)
    assert outages.parse_dt("29/10/2026 12:30:00 μμ") == datetime(2026, 10, 29, 12, 30)


def test_municipality_matching():
    assert outages.match_municipalities("Δήμος Αθηναίων")[0]["id"] == 112
    assert outages.match_municipalities("Δήμος Αγίας Παρασκευής")[0]["name"] == "ΔΗΜΟΣ ΑΓ.ΠΑΡΑΣΚΕΥΗΣ"
    ids = {m["id"] for m in outages.match_municipalities("Δήμος Αχαρνών", "Βαρυμπόμπη")}
    assert 122 in ids and 2090 in ids
    assert outages.match_municipalities("Nowhere") == []
