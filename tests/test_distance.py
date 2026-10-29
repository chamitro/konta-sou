"""Every option answers nearest first and honours the distance the visitor chose."""
import os
from datetime import datetime, timedelta

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite://")

OMONOIA = (37.9838, 23.7275)


@pytest.fixture
def client(monkeypatch, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import simera.db as db
    from simera.api import main
    from simera.collectors import events
    from simera.models import Event, Pharmacy, PharmacyDuty

    engine = create_engine(f"sqlite:///{tmp_path}/t.db", future=True)
    db.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(main, "SessionLocal", Session)
    monkeypatch.setattr(events, "SessionLocal", Session)

    now = datetime.now(main.ATHENS)
    with Session() as s:
        # three pharmacies on duty all day: 300 m, 1.4 km and 6 km away
        for i, (lat, lng) in enumerate([(37.9865, 23.7275), (37.9965, 23.7275), (38.0378, 23.7275)], start=1):
            s.add(Pharmacy(id=i, region="attica", name=f"Φαρμακείο {i}", address="Οδός", area="ΑΘΗΝΑ", phone="210", lat=lat, lng=lng))
            s.add(PharmacyDuty(pharmacy_id=i, duty_date=now.date(), hours_text="8 ΠΡΩΙ - 8 ΠΡΩΙ ΕΠΟΜΕΝΗΣ", intervals="0-1440"))
        # two events: the sooner one is further away
        s.add(Event(source="cia", source_id="1", title="Μακριά αλλά σύντομα", url="u1", starts_at=now.replace(tzinfo=None) + timedelta(hours=2), lat=38.03, lng=23.7275, modified=now.replace(tzinfo=None), fetched_at=now.replace(tzinfo=None)))
        s.add(Event(source="cia", source_id="2", title="Κοντά αλλά αργότερα", url="u2", starts_at=now.replace(tzinfo=None) + timedelta(days=3), lat=37.985, lng=23.7275, modified=now.replace(tzinfo=None), fetched_at=now.replace(tzinfo=None)))
        s.commit()

    from fastapi.testclient import TestClient
    return TestClient(main.app)


def test_pharmacies_nearest_first_within_max_km(client):
    lat, lng = OMONOIA
    r = client.get(f"/api/pharmacies/on-duty?lat={lat}&lng={lng}").json()
    assert [p["name"] for p in r["pharmacies"]] == ["Φαρμακείο 1", "Φαρμακείο 2", "Φαρμακείο 3"]
    assert r["total"] == 3 and r["max_km"] is None

    r = client.get(f"/api/pharmacies/on-duty?lat={lat}&lng={lng}&max_km=2").json()
    assert [p["name"] for p in r["pharmacies"]] == ["Φαρμακείο 1", "Φαρμακείο 2"]
    assert r["total"] == 3 and r["count"] == 2   # the page can say "the nearest of the 3 is further away"

    r = client.get(f"/api/pharmacies/on-duty?lat={lat}&lng={lng}&max_km=0.5").json()
    assert [p["name"] for p in r["pharmacies"]] == ["Φαρμακείο 1"]


def test_events_sorted_by_distance_by_default_or_by_time(client):
    lat, lng = OMONOIA
    by_distance = client.get(f"/api/events?lat={lat}&lng={lng}&radius=10000").json()
    assert by_distance["sort"] == "distance"
    assert [e["title"] for e in by_distance["items"]] == ["Κοντά αλλά αργότερα", "Μακριά αλλά σύντομα"]
    by_time = client.get(f"/api/events?lat={lat}&lng={lng}&radius=10000&sort=time").json()
    assert [e["title"] for e in by_time["items"]] == ["Μακριά αλλά σύντομα", "Κοντά αλλά αργότερα"]
    assert client.get(f"/api/events?lat={lat}&lng={lng}&radius=1000").json()["count"] == 1


def test_places_radius_up_to_15_km(client):
    lat, lng = OMONOIA
    assert client.get(f"/api/nearby?lat={lat}&lng={lng}&category=atm&radius=15000").status_code in (200, 503)
    assert client.get(f"/api/nearby?lat={lat}&lng={lng}&category=atm&radius=16000").status_code == 422
