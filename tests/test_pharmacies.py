from pathlib import Path

import pytest

from simera.collectors.pharmacies import parse_cards, parse_hours

FIXTURE = Path(__file__).parent / "fixtures" / "fsa_cards_sample.html"


@pytest.mark.parametrize("text,expected", [
    ("8 ΠΡΩΙ - 11 ΒΡΑΔΥ", [(480, 1380)]),
    ("8 ΠΡΩΙ - 2 ΜΕΣΗΜΕΡΙ & 5 ΑΠΟΓΕΥΜΑ - 8 ΠΡΩΙ ΕΠΟΜΕΝΗΣ", [(480, 840), (1020, 1920)]),
    ("8 ΠΡΩΙ - 9 ΒΡΑΔΥ", [(480, 1260)]),
    ("8 ΠΡΩΙ - 8 ΠΡΩΙ ΕΠΟΜΕΝΗΣ ΗΜΕΡΑΣ", [(480, 1920)]),
    ("9 ΒΡΑΔΥ - 8 ΠΡΩΙ ΕΠΟΜΕΝΗΣ", [(1260, 1920)]),
    ("8 ΠΡΩΙ - 10 ΒΡΑΔΥ", [(480, 1320)]),
    ("12 ΜΕΣΗΜΕΡΙ - 8 ΠΡΩΙ ΕΠΟΜΕΝΗΣ", [(720, 1920)]),
])
def test_parse_hours(text, expected):
    assert parse_hours(text) == expected


def test_parse_cards_fixture():
    cards = parse_cards(FIXTURE.read_text(encoding="utf-8"))
    assert len(cards) == 6
    c = cards[0]
    assert c.pharmacy_id == 292445
    assert c.address == "ΚΕΦΑΛΛΗΝΙΑΣ 98"
    assert c.area == "ΑΓ.ΑΝΑΡΓΥΡΟΙ"
    assert c.name.startswith("ΜΑΤΖΑΚΟΥ-ΚΑΡΑΣΤΑΤΗΡΗ")
    assert c.phone == "2102629305"
    assert (c.lat, c.lng) == (38.0279106, 23.7216171)
    assert c.hours_text == "8 ΠΡΩΙ - 2 ΜΕΣΗΜΕΡΙ & 5 ΑΠΟΓΕΥΜΑ - 8 ΠΡΩΙ ΕΠΟΜΕΝΗΣ"
    assert c.intervals == [(480, 840), (1020, 1920)]
    assert all(card.intervals for card in cards)
