import os

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite://")  # in-memory for this test module when run alone


def test_nearby_from_db(monkeypatch, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import simera.db as db
    from simera import osm
    from simera.models import Poi

    engine = create_engine(f"sqlite:///{tmp_path}/t.db", future=True)
    db.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(osm, "SessionLocal", Session)

    with Session() as s:
        s.add_all([
            Poi(osm_type="n", osm_id=1, category="fuel", name="BP Omonoia", brand="BP", lat=37.9840, lng=23.7280, opening_hours="24/7"),
            Poi(osm_type="n", osm_id=2, category="fuel", name="Far station", lat=38.05, lng=23.80),
            Poi(osm_type="w", osm_id=3, category="bakery", name="Φούρνος", lat=37.9839, lng=23.7276, opening_hours="Mo-Sa 06:00-21:00"),
        ])
        s.commit()

    items = osm.nearby("fuel", 37.9838, 23.7275, radius=1000)
    assert [i["name"] for i in items] == ["BP Omonoia"]
    assert items[0]["open_now"] is True and items[0]["distance_km"] < 0.1 and items[0]["osm_url"].endswith("/node/1")
    assert osm.nearby("bakery", 37.9838, 23.7275, radius=500)[0]["osm_url"].endswith("/way/3")
    assert osm.nearby("atm", 37.9838, 23.7275, radius=500) == []
    with pytest.raises(KeyError):
        osm.nearby("spaceport", 37.9838, 23.7275)


def test_empty_table_falls_back_to_overpass(monkeypatch, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import simera.db as db
    from simera import osm

    engine = create_engine(f"sqlite:///{tmp_path}/t.db", future=True)
    db.Base.metadata.create_all(engine)
    monkeypatch.setattr(osm, "SessionLocal", sessionmaker(bind=engine, expire_on_commit=False))
    called = {}
    monkeypatch.setattr(osm, "nearby_overpass", lambda *a, **k: called.setdefault("yes", []) )
    assert osm.nearby("fuel", 37.98, 23.72) == []
    assert "yes" in called
