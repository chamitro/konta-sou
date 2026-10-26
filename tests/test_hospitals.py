from datetime import date
from pathlib import Path

from simera.collectors.hospitals import match_hospital, parse_rota_html, split_hospitals

FIX = Path(__file__).parent / "fixtures"


def entries(parsed, specialty):
    return {(e.shift, e.hospital, e.region, e.note, e.key) for e in parsed.entries if e.specialty == specialty}


def test_split_hospitals_fragments_regions_and_notes():
    out = split_hospitals(["ΠΕΙΡΑΙΑΣ", "Γ.Ν.Ν.", "«ΑΓ. ΠΑΝΤΕΛΕΗΜΩΝ»", "Γ.Ν.", "«ΑΣΚΛΗΠΙΕΙΟ» ΒΟΥΛΑΣ", "Γ.Ν.Α. «ΠΑΜΜΑΚΑΡΙΣΤΟ» έως 23:00", "Γ", ".Ο.Ν.Κ. «ΑΓ. ΑΝΑΡΓΥΡΟΙ»"])
    assert out == [
        ("Γ.Ν.Ν. «ΑΓ. ΠΑΝΤΕΛΕΗΜΩΝ»", "ΠΕΙΡΑΙΑΣ", ""),
        ("Γ.Ν. «ΑΣΚΛΗΠΙΕΙΟ» ΒΟΥΛΑΣ", "ΠΕΙΡΑΙΑΣ", ""),
        ("Γ.Ν.Α. «ΠΑΜΜΑΚΑΡΙΣΤΟ»", "ΠΕΙΡΑΙΑΣ", "έως 23:00"),
        ("Γ.Ο.Ν.Κ. «ΑΓ. ΑΝΑΡΓΥΡΟΙ»", "ΠΕΙΡΑΙΑΣ", ""),
    ]


def test_match_hospital():
    assert match_hospital("Γ.Ν.Ν.ΙΩΝΙΑΣ «ΚΩΝ/ΠΟΥΛΕΙΟ»") == "konstantopouleio"
    assert match_hospital("Γ.Ο.Ν.Κ. «ΑΓ. ΑΝΑΡΓΥΡΟΙ»") == "agioi_anargyroi"
    assert match_hospital("Γ.Ν.Α. «ΚΟΡΓ. ΜΠΕΝ. ΕΕΣ»") == "erythros"
    assert match_hospital("Κ.Υ. ΑΛΕΞΑΝΔΡΑΣ") == "ky_alexandras"
    assert match_hospital("Γ.Ν.Α. «ΑΛΕΞΑΝΔΡΑ»") == "alexandra"
    assert match_hospital("«ΑΓΝΩΣΤΟ»") == ""


def test_sunday_rota():
    p = parse_rota_html((FIX / "hospitals_20261025_sunday.html").read_text(encoding="utf-8", errors="replace"))
    assert p.duty_date == date(2026, 10, 25)
    assert p.shifts == ["08:00 – 08:00 επομένης", "08:00 – 23:00"]
    path = entries(p, "Παθολογική")
    assert ("08:00 – 08:00 επομένης", "Γ.Ν.Α. «ΕΥΑΓΓΕΛΙΣΜΟΣ»", "", "", "evangelismos") in path
    assert ("08:00 – 08:00 επομένης", "Γ.Ν. «ΑΣΚΛΗΠΙΕΙΟ» ΒΟΥΛΑΣ", "ΠΕΙΡΑΙΑΣ", "", "asklepieio") in path
    assert ("08:00 – 08:00 επομένης", "Γ.Ν.Ν.ΙΩΝΙΑΣ «ΚΩΝ/ΠΟΥΛΕΙΟ»", "", "", "konstantopouleio") in path
    assert len({e.specialty for e in p.entries}) >= 14
    assert all(e.key for e in p.entries), [e.hospital for e in p.entries if not e.key]
    assert ("Κ.Υ. ΑΛΕΞΑΝΔΡΑΣ", "08:00 – 08:00 επομένης", "ky_alexandras") in p.health_centers


def test_monday_rota():
    p = parse_rota_html((FIX / "hospitals_20261026_monday.html").read_text(encoding="utf-8", errors="replace"))
    assert p.duty_date == date(2026, 10, 26)
    assert p.shifts == ["08:00 – 14:30", "08:00 – 16:00", "08:00 – 23:00", "14:30 – 08:00 επομένης", "08:00 – 08:00 επομένης"]
    path = entries(p, "Παθολογική")
    assert ("08:00 – 14:30", "Γ.Ν.Α. «ΕΛΠΙΣ»", "", "", "elpis") in path
    assert ("08:00 – 23:00", "Γ.Ν.Α. «ΠΑΜΜΑΚΑΡΙΣΤΟ»", "", "έως 23:00", "pammakaristos") in path
    assert ("08:00 – 08:00 επομένης", "Γ.Ν.Ν. «ΑΓ. ΠΑΝΤΕΛΕΗΜΩΝ»", "ΠΕΙΡΑΙΑΣ", "", "nikaia") in path
    assert ("14:30 – 08:00 επομένης", "Γ.Ν.Α. «ΚΟΡΓ. ΜΠΕΝ. ΕΕΣ»", "", "", "erythros") in path
    assert len({e.specialty for e in p.entries}) >= 25
    assert not any("«" in e.hospital and "»" not in e.hospital for e in p.entries)
    assert not any(e.hospital.startswith("«") for e in p.entries), [e.hospital for e in p.entries if e.hospital.startswith("«")]
    assert len(p.health_centers) == 4


def test_saturday_rota_with_varying_cell_widths():
    p = parse_rota_html((FIX / "hospitals_20261024_saturday.html").read_text(encoding="utf-8", errors="replace"))
    assert p.duty_date == date(2026, 10, 24)
    assert p.shifts == ["08:00 – 08:00 επομένης", "08:00 – 23:00"]
    assert len(p.entries) >= 24  # a Saturday rota is small: two shift columns, ~10 specialties staffed
    assert len({e.specialty for e in p.entries}) >= 10
    tzaneio = [e for e in p.entries if "ΤΖΑΝΕΙΟ" in e.hospital]
    assert len(tzaneio) >= 2 and all(e.region == "ΠΕΙΡΑΙΑΣ" and e.key == "tzaneio" for e in tzaneio), tzaneio
    assert ("Παθολογική", "Γ.Ν.Α. «Γ. ΓΕΝΝΗΜΑΤΑΣ»") in {(e.specialty, e.hospital) for e in p.entries}
    assert not any(e.hospital.startswith("«") for e in p.entries)
    assert not any("«" in e.specialty for e in p.entries)
    assert all(e.key for e in p.entries), [e.hospital for e in p.entries if not e.key]
