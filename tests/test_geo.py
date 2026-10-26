from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from simera.geo import haversine_km, is_open_now, nearest_prefecture

ATH = ZoneInfo("Europe/Athens")


def test_nearest_prefecture():
    assert nearest_prefecture(37.9838, 23.7275) == "ΝΟΜΟΣ ΑΤΤΙΚΗΣ"  # Omonoia
    assert nearest_prefecture(40.6401, 22.9444) == "ΝΟΜΟΣ ΘΕΣΣΑΛΟΝΙΚΗΣ"
    assert nearest_prefecture(35.3387, 25.1442) == "ΝΟΜΟΣ ΗΡΑΚΛΕΙΟΥ"
    assert nearest_prefecture(38.2466, 21.7346) == "ΝΟΜΟΣ ΑΧΑΪΑΣ"  # Patras


def test_haversine():
    assert round(haversine_km(37.9838, 23.7275, 37.9755, 23.7348), 2) == pytest.approx(1.11, abs=0.05)


@pytest.mark.parametrize("oh,when,expected", [
    ("24/7", "2026-10-26 03:00", True),
    ("Mo-Fr 08:00-20:00; Sa 09:00-15:00", "2026-10-26 10:00", True),   # Monday
    ("Mo-Fr 08:00-20:00; Sa 09:00-15:00", "2026-10-26 21:00", False),
    ("Mo-Fr 08:00-20:00; Sa 09:00-15:00", "2026-10-25 10:00", False),  # Sunday
    ("Mo-Su 07:00-01:00", "2026-10-26 00:30", True),                   # past midnight from Sunday
    ("Mo-Su 07:00-01:00", "2026-10-26 02:00", False),
    ("Mo-Fr 08:00-14:00,17:00-21:00", "2026-10-26 15:00", False),
    ("Mo-Fr 08:00-14:00,17:00-21:00", "2026-10-26 18:00", True),
    ("Mo-Sa 08:00-21:00; Su off", "2026-10-25 12:00", False),
    (None, "2026-10-26 12:00", None),
    ('Mo-Fr 08:00-20:00 "call first"', "2026-10-26 12:00", None),  # too complex: unknown
])
def test_is_open_now(oh, when, expected):
    at = datetime.strptime(when, "%Y-%m-%d %H:%M").replace(tzinfo=ATH)
    assert is_open_now(oh, at) is expected
