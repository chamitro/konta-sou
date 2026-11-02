"""OASA announcements: feed parsing, line and municipality extraction, relevance to a visitor."""
import os
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

os.environ.setdefault("DATABASE_URL", "sqlite://")
FIX = Path(__file__).parent / "fixtures"


def test_parse_feed_items():
    from simera.collectors.oasa_notices import parse_feed

    items = parse_feed((FIX / "oasa_feed.xml").read_text(encoding="utf-8"))
    assert len(items) == 10
    assert items[2]["title"] == "Μερική προσωρινή τροποποίηση της λεωφορειακής γραμμής 823 στον Δήμο Περιστερίου"
    assert items[2]["guid"] == "https://www.oasa.gr/?p=14907"
    assert items[2]["published"] == datetime(2026, 11, 2, 5, 37, 32)
    assert "Alerts" in items[2]["categories"]


def test_parse_post_body_and_dates():
    from simera.collectors.oasa_notices import extract_dates, parse_post

    body = parse_post((FIX / "oasa_post.html").read_text(encoding="utf-8"))
    assert body.startswith("Με στόχο την ενημέρωση")
    assert "Διοικητική Δομή" not in body          # the site menu is not the announcement
    assert "Από Δωδεκανήσου" in body
    starts, ends, when = extract_dates(body, date(2026, 11, 2))
    assert (starts, ends) == (date(2026, 11, 3), date(2026, 11, 3))
    assert when == "3/11 · 07:00–09:00"


@pytest.mark.parametrize("text,published,expected", [
    ("ανακοινώνει την παράταση έως 30/11/2026 της μερικής τροποποίησης", date(2026, 10, 31), (date(2026, 10, 31), date(2026, 11, 30), "έως 30/11")),
    ("για κάθε Σάββατο από 31/10/2026 έως 30/04/2027, από 08:00 έως 16:00", date(2026, 10, 30), (date(2026, 10, 31), date(2027, 4, 30), "31/10–30/4 · 08:00–16:00 · κάθε Σάββατο")),
    ("στις 31.10.2026 και τη 1.11.2026", date(2026, 10, 30), (date(2026, 10, 31), date(2026, 11, 1), "31/10–1/11")),
    ("καμία ημερομηνία εδώ", date(2026, 10, 30), (None, None, None)),
])
def test_extract_dates_kinds(text, published, expected):
    from simera.collectors.oasa_notices import extract_dates

    assert extract_dates(text, published) == expected


@pytest.mark.parametrize("title,lines", [
    ("Μερική προσωρινή τροποποίηση της λεωφορειακής γραμμής 823 στον Δήμο Περιστερίου", ["823"]),
    ("Μερική προσωρινή τροποποίηση των λεωφορειακών γραμμών 219 και 816 στον Δήμο Αγ. Δημητρίου", ["219", "816"]),
    ("Προσωρινή μερική τροποποίηση της διαδρομής των λεωφορειακών γραμμών 700, 747, A11 και Β11, λόγω εκδηλώσεων", ["700", "747", "Α11", "Β11"]),
    ("Μερική προσωρινή τροποποίηση της λεωφορειακής γραμμής 046 στον Δήμο Αθηναίων", ["046"]),
    ("Προσωρινή αναστολή λειτουργίας της λεωφορειακής γραμμής Χ80 «ΠΕΙΡΑΙΑΣ-ΑΚΡΟΠΟΛΗ»", ["Χ80"]),
    ("Μερική προσωρινή τροποποίηση των λεωφ. γραμμών 409 και 418 λόγω εορτασμού της 28ης Οκτωβρίου στο Δήμο Παπάγου-Χολαργού", ["409", "418"]),
    ("Λειτουργία των ΜΜΜ λόγω των εορταστικών εκδηλώσεων για την Εθνική Επέτειο της 28ης Οκτωβρίου", []),
    ("ο ΟΑΣΑ ανακοινώνει τη μερική τροποποίηση για την Τετάρτη 04/11/2026 και τις ώρες 07.00 έως 09.00", []),
])
def test_extract_lines(title, lines):
    from simera.collectors.oasa_notices import extract_lines

    assert extract_lines(title) == lines


@pytest.mark.parametrize("title,expected", [
    ("γραμμής 823 στον Δήμο Περιστερίου", "ΔΗΜΟΣ ΠΕΡΙΣΤΕΡΙΟΥ"),
    ("γραμμής 112 στον Δήμο Αγ. Δημητρίου", "ΔΗΜΟΣ ΑΓ.ΔΗΜΗΤΡΙΟΥ"),
    ("γραμμής 418 λόγω έργων στην οδό Σαρανταπόρου του Δήμου Παπάγου Χολαργού", "ΔΗΜΟΣ ΠΑΠΑΓΟΥ"),
    ("γραμμών 409 και 418 λόγω εορτασμού στο Δήμο Παπάγου-Χολαργού", "ΔΗΜΟΣ ΠΑΠΑΓΟΥ"),
    ("γραμμών 305, 319 και 326, στον Δήμο Σπάτων – Αρτέμιδος", "ΔΗΜΟΣ ΣΠΑΤΩΝ-ΛΟΥΤΣΑΣ"),
    ("γραμμής 859, λόγω εκδηλώσεων στον Δήμο Κερατσινίου-Δραπετσώνας.", "ΔΗΜΟΣ ΚΕΡΑΤΣΙΝΙΟΥ"),
    ("γραμμών 116, 117 στον Δήμο Βάρης – Βούλας – Βουλιαγμένης", "ΔΗΜΟΣ ΒΑΡΗΣ"),
])
def test_extract_municipalities(title, expected):
    from simera.collectors.outages import MUNICIPALITIES
    from simera.collectors.oasa_notices import extract_municipalities

    ids, area = extract_municipalities(title)
    names = {m["id"]: m["name"] for m in MUNICIPALITIES}
    assert [names[i] for i in ids] == [expected]
    assert area


def test_relevant_by_line_area_and_general(monkeypatch, tmp_path):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    import simera.db as db
    from simera.collectors import oasa_notices as o
    from simera.models import TransitNotice

    engine = create_engine(f"sqlite:///{tmp_path}/t.db", future=True)
    db.Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    monkeypatch.setattr(o, "SessionLocal", Session)
    now = datetime(2026, 11, 2, 12, 0)
    today = now.date()
    with Session() as s:
        s.add_all([
            TransitNotice(source_id="a", title="823 στον Δήμο Περιστερίου", url="u", published=now - timedelta(hours=5), starts_on=today + timedelta(days=1), ends_on=today + timedelta(days=1), lines="823", municipality_ids="176", summary="", fetched_at=now),
            TransitNotice(source_id="b", title="219 και 816 στον Δήμο Αγ. Δημητρίου", url="u", published=now - timedelta(days=1), starts_on=today - timedelta(days=2), ends_on=today + timedelta(days=5), lines="219,816", municipality_ids="108", summary="", fetched_at=now),
            TransitNotice(source_id="c", title="Λειτουργία των ΜΜΜ την αργία", url="u", published=now - timedelta(days=2), starts_on=None, ends_on=None, lines="", municipality_ids="", summary="", fetched_at=now),
            TransitNotice(source_id="d", title="Παλιά αλλαγή 823", url="u", published=now - timedelta(days=10), starts_on=today - timedelta(days=9), ends_on=today - timedelta(days=8), lines="823", municipality_ids="176", summary="", fetched_at=now),
            TransitNotice(source_id="e", title="Άσχετος δήμος", url="u", published=now, starts_on=None, ends_on=None, lines="311", municipality_ids="155", summary="", fetched_at=now),
        ])
        s.commit()

    # a visitor in Αγ. Δημήτριος whose nearby stops serve line 823 (Latin letters and case do not matter)
    got = o.relevant([108], ["823"], now)
    assert [(x["title"][:3], x["match"], x["status"]) for x in got] == [("219", "area", "active"), ("823", "line", "upcoming"), ("Λει", "general", "recent")]
    assert got[1]["matched_lines"] == ["823"]
    # nothing nearby: only the general notice
    assert [x["match"] for x in o.relevant([], [], now)] == ["general"]
    assert [x["match"] for x in o.relevant([], ["x80", "Β11"], now)] == ["general"]
