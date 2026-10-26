from fastapi.testclient import TestClient

from simera import oasa
from simera.api import main


def test_bus_endpoints_fail_gracefully_when_oasa_unreachable(monkeypatch):
    def boom(*a, **k):
        raise ConnectionError("blocked")
    monkeypatch.setattr(oasa, "closest_stops", boom)
    monkeypatch.setattr(oasa, "arrivals_with_lines", boom)
    c = TestClient(main.app)
    r = c.get("/api/transit/stops/near?lat=37.98&lng=23.72")
    assert r.status_code == 503 and "ΟΑΣΑ" in r.json()["detail"]
    assert c.get("/api/transit/stops/60134/arrivals").status_code == 503
    assert c.get("/healthz").json()["ok"] is True


def test_geocode_endpoint(monkeypatch):
    from simera import geo
    monkeypatch.setattr(geo, "geocode", lambda q, limit=5: [{"name": "Κυψέλη, Αθήνα", "lat": 37.99, "lng": 23.74}])
    monkeypatch.setattr(main, "geocode", geo.geocode)
    c = TestClient(main.app)
    r = c.get("/api/geocode?q=Κυψέλη")
    assert r.status_code == 200 and r.json()["results"][0]["name"].startswith("Κυψέλη")
    assert c.get("/api/geocode?q=a").status_code == 422
