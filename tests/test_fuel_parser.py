from datetime import date
from pathlib import Path

import pytest

from simera.collectors.fuel import date_from_filename
from simera.collectors.fuel_parser import fix_garble, parse_bulletin_pdf, parse_date

FIX = Path(__file__).parent / "fixtures"


def by_pref(parsed, pref):
    return {r.fuel_type: r.price for r in parsed.rows if r.prefecture == pref}


def test_2026_layout():
    p = parse_bulletin_pdf((FIX / "IMERISIO_DELTIO_ANA_NOMO_22_10_2026.pdf").read_bytes())
    assert p.price_date == date(2026, 10, 22)
    assert p.columns == ["unleaded_95", "unleaded_100", "diesel", "autogas", "heating_oil"]
    assert len({r.prefecture for r in p.rows}) == 52
    assert by_pref(p, "ΝΟΜΟΣ ΑΤΤΙΚΗΣ") == {"unleaded_95": 2.135, "unleaded_100": 2.426, "diesel": 2.100, "autogas": 1.173, "heating_oil": 1.531}
    assert by_pref(p, "ΕΛΛΑΔΑ")["unleaded_95"] == 2.168
    assert by_pref(p, "ΝΟΜΟΣ ΑΙΤΩΛΙΑΣ ΚΑΙ ΑΚΑΡΝΑΝΙΑΣ")["diesel"] == 2.145


def test_2024_summer_layout_without_heating_oil():
    p = parse_bulletin_pdf((FIX / "IMERISIO_DELTIO_ANA_NOMO_01_06_2024.pdf").read_bytes())
    assert p.price_date == date(2024, 6, 1)
    assert p.columns == ["unleaded_95", "unleaded_100", "diesel", "autogas"]
    assert by_pref(p, "ΝΟΜΟΣ ΑΤΤΙΚΗΣ") == {"unleaded_95": 1.866, "unleaded_100": 2.089, "diesel": 1.594, "autogas": 0.762}
    assert len({r.prefecture for r in p.rows}) == 52


def test_2021_layout_with_super():
    p = parse_bulletin_pdf((FIX / "IMERISIO_DELTIO_ANA_NOMO_01_03_2021.pdf").read_bytes())
    assert p.price_date == date(2021, 3, 1)
    assert p.columns == ["unleaded_95", "unleaded_100", "super", "diesel", "autogas", "heating_oil"]
    assert by_pref(p, "ΝΟΜΟΣ ΑΤΤΙΚΗΣ") == {"unleaded_95": 1.537, "unleaded_100": 1.729, "super": 1.720, "diesel": 1.278, "autogas": 0.787, "heating_oil": 0.928}
    assert "super" not in by_pref(p, "ΝΟΜΟΣ ΑΡΚΑΔΙΑΣ")  # "-" cell


def test_2018_layout_garbled_font_and_reordered_columns():
    p = parse_bulletin_pdf((FIX / "IMERISIO_DELTIO_ANA_NOMO_01_02_2018.pdf").read_bytes())
    assert p.price_date == date(2018, 2, 1)
    assert p.columns == ["unleaded_95", "unleaded_100", "super", "diesel", "heating_oil", "autogas"]
    assert by_pref(p, "ΝΟΜΟΣ ΑΤΤΙΚΗΣ") == {"unleaded_95": 1.527, "unleaded_100": 1.736, "super": 1.620, "diesel": 1.303, "heating_oil": 1.005, "autogas": 0.788}
    assert by_pref(p, "ΝΟΜΟΣ ΔΩΔΕΚΑΝΗΣΟΥ").keys() == {"unleaded_95", "unleaded_100", "diesel", "heating_oil"}  # 0,000 = missing
    assert len({r.prefecture for r in p.rows}) == 52
    assert "ΝΟΜΟΣ ΘΕΣΣΑΛΟΝΙΚΗΣ" in {r.prefecture for r in p.rows}


def test_fix_garble():
    assert fix_garble("ΝΟΜΟ΢ ΑΣΣΙΚΗ΢") == "ΝΟΜΟΣ ΑΤΤΙΚΗΣ"
    assert fix_garble("ΝΟΜΟΣ ΑΤΤΙΚΗΣ") == "ΝΟΜΟΣ ΑΤΤΙΚΗΣ"  # untouched when not garbled


@pytest.mark.parametrize("text,expected", [
    ("ανά Νομό, για την\nΠέμπτη, 22 Οκτωβρίου 2026\n(τιμές σε €/λτ)", date(2026, 10, 22)),
    ("για την 1/2/2018", date(2018, 2, 1)),
    ("Αθήνα, 16/03/2018 (issue date only, no price-date phrase)", None),
    ("nothing here", None),
])
def test_parse_date(text, expected):
    assert parse_date(text) == expected


def test_date_from_filename():
    assert date_from_filename("https://x/IMERISIO_DELTIO_ANA_NOMO_01_02_2019.pdf") == date(2019, 2, 1)


def test_2018_march_no_price_date_phrase_and_wrapped_national_label():
    p = parse_bulletin_pdf((FIX / "IMERISIO_DELTIO_ANA_NOMO_15_03_2018.pdf").read_bytes())
    assert p.price_date is None  # letterhead date must NOT be used; the collector falls back to the filename date
    assert len({r.prefecture for r in p.rows}) == 52
    assert by_pref(p, "ΕΛΛΑΔΑ")["unleaded_95"] > 1.0


def test_2018_august_headerless_bulletin_uses_fallback_columns():
    data = (FIX / "IMERISIO_DELTIO_ANA_NOMO_08_08_2018.pdf").read_bytes()
    assert parse_bulletin_pdf(data).rows == []  # no header, no fallback: nothing, rather than guesses
    cols = ["unleaded_95", "unleaded_100", "super", "diesel", "heating_oil", "autogas"]  # 2018 order, from the previous day
    p = parse_bulletin_pdf(data, fallback_columns=cols)
    assert p.price_date == date(2018, 8, 8)
    assert p.columns == cols
    assert len({r.prefecture for r in p.rows}) == 52
    # Attica's heating-oil cell is blank in this bulletin; the other five must still land in the right columns
    assert by_pref(p, "ΝΟΜΟΣ ΑΤΤΙΚΗΣ") == {"unleaded_95": 1.618, "unleaded_100": 1.830, "super": 1.724, "diesel": 1.391, "autogas": 0.787}
    assert by_pref(p, "ΝΟΜΟΣ ΜΕΣΣΗΝΙΑΣ")["heating_oil"] == 1.119
    assert parse_bulletin_pdf(data, fallback_columns=cols[:5]).rows == []  # wrong column count: refuse rather than guess
