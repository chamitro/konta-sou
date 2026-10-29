from datetime import datetime
from pathlib import Path

from simera.collectors import events

FIX = Path(__file__).parent / "fixtures"


def test_parse_event_page():
    p = events.parse_event_page((FIX / "cultureisathens_event.html").read_text(encoding="utf-8"))
    assert p["starts_at"] == datetime(2026, 10, 2, 11, 0)
    assert p["venue"] == "Κέντρο Τεχνών" and p["categories"] == "Εικαστικά · Ομιλίες" and p["price"] == "Δωρεάν"
    assert abs(p["lat"] - 37.9807) < 0.001 and abs(p["lng"] - 23.7520) < 0.001
    assert p["image"] is None   # the page only carries the site logo


def test_greek_datetimes():
    assert events.parse_greek_datetime("6 Νοεμβρίου 2026 21:00") == datetime(2026, 11, 6, 21, 0)
    assert events.parse_greek_datetime("31 Οκτωβρίου 2026") == datetime(2026, 10, 31)
    assert events.parse_greek_datetime("1 Μαΐου 2027 10:30") == datetime(2027, 5, 1, 10, 30)
    assert events.parse_greek_datetime("χωρίς ημερομηνία") is None
