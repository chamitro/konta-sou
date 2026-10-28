from datetime import date

from simera.namedays import holiday, names_for, next_nameday, orthodox_easter


def test_orthodox_easter_known_years():
    assert orthodox_easter(2024) == date(2024, 5, 5)
    assert orthodox_easter(2025) == date(2025, 4, 20)
    assert orthodox_easter(2026) == date(2026, 4, 12)
    assert orthodox_easter(2027) == date(2027, 5, 2)


def test_fixed_and_movable_names():
    assert "Δημήτρης" in names_for(date(2026, 10, 26))
    assert "Αναστασία" in names_for(date(2026, 4, 12))
    assert "Θωμάς" in names_for(date(2026, 4, 19))
    assert "Γιώργος" in names_for(date(2026, 4, 23))      # 2026: Easter 12 April, so George stays on the 23rd
    assert "Γιώργος" in names_for(date(2027, 5, 3))       # 2027: Easter 2 May, so George moves to Easter Monday
    assert names_for(date(2026, 10, 28)) == []


def test_holidays_and_next():
    assert holiday(date(2026, 10, 28)).startswith("Επέτειος")
    assert holiday(date(2026, 2, 23)) == "Καθαρά Δευτέρα"      # Easter 12 April 2026 minus 48 days
    assert holiday(date(2026, 10, 27)) is None
    assert next_nameday(date(2026, 10, 29)) == (date(2026, 11, 1), ["Ανάργυρος", "Αργύρης", "Αργυρώ"])
