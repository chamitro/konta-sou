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
    assert c.get("/healthz").json() == {"ok": True}
