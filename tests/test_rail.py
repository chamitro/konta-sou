import io
import zipfile
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

ATH = ZoneInfo("Europe/Athens")


def make_feed(path: Path) -> Path:
    files = {
        "agency.txt": "agency_id,agency_name,agency_url,agency_timezone\n1,STASY,https://www.stasy.gr,Europe/Athens\n",
        "routes.txt": "route_id,agency_id,route_short_name,route_long_name,route_type\n3,1,M3,ΓΡΑΜΜΗ 3,1\n",
        "calendar_dates.txt": "service_id,date,exception_type\n1,20260701,1\n2,20260704,1\n",  # Wed, Sat
        "stops.txt": "stop_id,stop_code,stop_name,stop_lat,stop_lon,location_type,wheelchair_boarding\n"
                     "10,SYN1,ΣΥΝΤΑΓΜΑ,37.9755,23.7348,0,1\n11,SYN2,ΣΥΝΤΑΓΜΑ,37.9756,23.7349,0,1\n"
                     "20,MON1,ΜΟΝΑΣΤΗΡΑΚΙ,37.9761,23.7256,0,\n30,AIG1,ΑΙΓΑΛΕΩ,37.9920,23.6818,0,\n",
        "trips.txt": "route_id,service_id,trip_id,trip_headsign,direction_id\n3,1,t1,,0\n3,1,t2,,0\n3,2,t3,,0\n3,1,t4,,1\n",
        "stop_times.txt": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
                          "t1,10:00:00,10:00:00,10,1\nt1,10:03:00,10:03:00,20,2\nt1,10:15:00,10:15:00,30,3\n"
                          "t2,10:10:00,10:10:00,10,1\nt2,10:13:00,10:13:00,20,2\nt2,10:25:00,10:25:00,30,3\n"
                          "t3,11:00:00,11:00:00,10,1\nt3,11:03:00,11:03:00,20,2\nt3,11:15:00,11:15:00,30,3\n"
                          "t4,25:10:00,25:10:00,30,1\nt4,25:22:00,25:22:00,20,2\nt4,25:25:00,25:25:00,11,3\n",
    }
    p = path / "feed.zip"
    with zipfile.ZipFile(p, "w") as z:
        for n, c in files.items():
            z.writestr(n, c)
    return p


@pytest.fixture
def db(monkeypatch, tmp_path):
    import simera.collectors.gtfs as gtfs
    import simera.db as db
    import simera.rail as rail

    engine = create_engine(f"sqlite:///{tmp_path}/t.db", future=True)
    db.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(gtfs, "SessionLocal", Session)
    monkeypatch.setattr(gtfs, "init_db", lambda: None)
    monkeypatch.setattr(rail, "SessionLocal", Session)
    info = gtfs.import_zip(make_feed(tmp_path), "test")
    return info


def test_import_groups_platforms_into_stations(db):
    assert db["stations"] == 3 and db["services"] == 2 and db["first_date"] == "2026-07-01"


def test_departures_exact_day(db):
    from simera.rail import stations_near
    r = stations_near(37.9755, 23.7348, limit=1, now=datetime(2026, 7, 1, 9, 55, tzinfo=ATH))
    assert r["feed"]["exact_day"] is True
    st = r["stations"][0]
    assert st["name"] == "ΣΥΝΤΑΓΜΑ" and st["lines"] == ["M3"] and st["wheelchair"] == "yes"
    assert [(d["line"], d["minutes"], d["destination"]) for d in st["departures"]] == [("M3", 5, "ΑΙΓΑΛΕΩ"), ("M3", 15, "ΑΙΓΑΛΕΩ")]
    # the terminus arrival (t1 at ΑΙΓΑΛΕΩ) is not offered as a departure
    aig = stations_near(37.9920, 23.6818, limit=1, now=datetime(2026, 7, 1, 9, 0, tzinfo=ATH))["stations"][0]
    assert all(d["destination"] != "ΑΙΓΑΛΕΩ" for d in aig["departures"])


def test_representative_day_when_outside_feed(db):
    from simera.rail import stations_near
    r = stations_near(37.9755, 23.7348, limit=1, now=datetime(2026, 10, 28, 9, 55, tzinfo=ATH))  # a Wednesday in October
    assert r["feed"]["exact_day"] is False and "Ενδεικτικά" in r["feed"]["note"]
    assert [d["minutes"] for d in r["stations"][0]["departures"]] == [5, 15]  # weekday pattern (service 1)
    sat = stations_near(37.9755, 23.7348, limit=1, now=datetime(2026, 10, 31, 10, 50, tzinfo=ATH))  # Saturday
    assert [d["minutes"] for d in sat["stations"][0]["departures"]] == [10]


def test_after_midnight_uses_previous_service(db):
    from simera.rail import stations_near
    r = stations_near(37.9761, 23.7256, limit=1, now=datetime(2026, 7, 2, 1, 10, tzinfo=ATH))  # 01:10 on Thu; Wed's 25:22 trip
    assert [(d["minutes"], d["destination"]) for d in r["stations"][0]["departures"]] == [(12, "ΣΥΝΤΑΓΜΑ")]
