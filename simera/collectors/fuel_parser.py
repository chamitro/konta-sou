"""Parser for the daily per-prefecture fuel price bulletin PDF (fuelprices.gr).

Layouts changed over the years (a Super column until ~2021, heating oil only from
15 October to 30 April, column order differs in 2018 bulletins, and 2018 PDFs use a
font whose Σ/Τ/Υ glyphs decode one code point off). The parser therefore locates
column headers by x-position and assigns each price cell to the nearest header.
"""
from __future__ import annotations

import difflib
import io
import logging
import re
from dataclasses import dataclass
from datetime import date

import pdfplumber

log = logging.getLogger(__name__)

NATIONAL_LABEL = "ΕΛΛΑΔΑ"

# header word -> fuel type. Capital-Κ "Κίνησης" is the Diesel column; lowercase "κίνησης" belongs to Autogas.
ANCHORS = [
    (re.compile(r"^95$"), "unleaded_95"),
    (re.compile(r"^100$"), "unleaded_100"),
    (re.compile(r"^Super$"), "super"),
    (re.compile(r"^Κ.νησης$"), "diesel"),
    (re.compile(r"^\(Autogas\)$"), "autogas"),
    (re.compile(r"^Κατ.ο.κον$"), "heating_oil"),
]
VALUE_RE = re.compile(r"^(\d+,\d{3}|-|–)$")
MISSING = {"-", "–", "0,000"}
MAX_ANCHOR_DISTANCE = 45  # points

DATE_WORDS_RE = re.compile(r"(\d{1,2})\s+([Α-Ωα-ωίόάέύήώϊΐζ]+)\s+(\d{4})")
DATE_NUM_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
GREEK_MONTHS = {
    "ιανουαριου": 1, "φεβρουαριου": 2, "μαρτιου": 3, "απριλιου": 4, "μαιου": 5, "ιουνιου": 6,
    "ιουλιου": 7, "αυγουστου": 8, "σεπτεμβριου": 9, "οκτωβριου": 10, "νοεμβριου": 11, "δεκεμβριου": 12,
}
_ACCENTS = str.maketrans("άέήίόύώϊΐζ", "αεηιουωιιε")  # ζ: garbled έ in 2018 font
# 2018 font bug: Σ printed as U+03A2, Τ as Σ, Υ as Τ.
_GARBLE = str.maketrans({"΢": "Σ", "Σ": "Τ", "Τ": "Υ"})


@dataclass
class PriceRow:
    prefecture: str
    fuel_type: str
    price: float


@dataclass
class ParsedBulletin:
    price_date: date | None
    rows: list[PriceRow]
    columns: list[str]


def fix_garble(text: str) -> str:
    return text.translate(_GARBLE) if "΢" in text else text


def parse_date(text: str) -> date | None:
    """Price date: only the date that follows 'για την'. The letterhead carries the (later) issue
    date, so when the phrase is missing we return None and the caller uses the filename date."""
    for scope in (text[m.end():m.end() + 60] for m in re.finditer(r"για την", text)):
        d = _parse_date_any(scope)
        if d:
            return d
    return None


def _parse_date_any(text: str) -> date | None:
    for m in DATE_WORDS_RE.finditer(text):
        month = GREEK_MONTHS.get(m.group(2).translate(_ACCENTS).lower())
        if month:
            return date(int(m.group(3)), month, int(m.group(1)))
    m = DATE_NUM_RE.search(text)
    if m:
        return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
    return None


def _find_anchors(words) -> list[tuple[float, str]]:
    out = []
    for w in words:
        for rx, fuel in ANCHORS:
            if rx.match(w["text"]):
                out.append(((w["x0"] + w["x1"]) / 2, fuel))
                break
    return sorted(out)


def _infer_anchors_from_cells(words, fallback_columns: list[str]) -> list[tuple[float, str]]:
    """No readable header: numbers still line up in columns, so cluster their x-centres and
    name the clusters with the fallback column order. Empty if the counts disagree."""
    xs = sorted((w["x0"] + w["x1"]) / 2 for w in words if VALUE_RE.match(w["text"]))
    clusters: list[list[float]] = []
    for x in xs:
        if clusters and x - clusters[-1][-1] < 20:
            clusters[-1].append(x)
        else:
            clusters.append([x])
    if len(clusters) != len(fallback_columns):
        log.warning("headerless page: %d value columns but fallback has %d", len(clusters), len(fallback_columns))
        return []
    return [(sum(c) / len(c), f) for c, f in zip(clusters, fallback_columns)]


def _group_rows(words, tol: float = 2.5):
    rows: list[list] = []
    for w in sorted(words, key=lambda w: (w["top"], w["x0"])):
        if rows and abs(rows[-1][0]["top"] - w["top"]) <= tol:
            rows[-1].append(w)
        else:
            rows.append([w])
    return rows


NATIONAL_RE = re.compile(r"^(ΠΑΝΕΛΛΗΝΙΟΣ|ΠΑΝΕΛΛΑΔΙΚ|Μ\.Ο\.|ΣΤΑΘΜΙΣΜΕΝΟΣ)")
NATIONAL_FULL = "ΠΑΝΕΛΛΗΝΙΟΣ ΣΤΑΘΜΙΣΜΕΝΟΣ Μ.Ο."


def _canonical_names() -> list[str]:
    from simera.geo import PREFECTURE_CENTROIDS

    return list(PREFECTURE_CENTROIDS) + [NATIONAL_FULL]


_CANON: list[str] = []


def _garble_similarity(a: str, b: str) -> float:
    """Position-wise similarity where letters count as equal when their code points differ by at
    most 2: broken PDF fonts shift glyphs by one or two places (Ι->Η, Δ->Γ, Χ->Υ, Σ->΢)."""
    if abs(len(a) - len(b)) > 1:
        return 0.0
    n = max(len(a), len(b))
    hits = sum(1 for x, y in zip(a, b) if x == y or abs(ord(x) - ord(y)) <= 2)
    return hits / n


def snap_label(label: str) -> str | None:
    """Map a row label to a canonical prefecture name (or NATIONAL_LABEL), tolerating the
    letter substitutions of broken PDF fonts (ΑΣΣΗΚΖ΢ -> ΑΤΤΙΚΗΣ). None if nothing is close."""
    global _CANON
    if not _CANON:
        _CANON = _canonical_names()
    label = re.sub(r"\s+", " ", label).strip()
    if label in _CANON:
        return NATIONAL_LABEL if label == NATIONAL_FULL else label
    if NATIONAL_RE.match(label):
        return NATIONAL_LABEL
    scored = sorted(((_garble_similarity(label, c), c) for c in _CANON), reverse=True)
    best, name = scored[0]
    if best < 0.8 or (len(scored) > 1 and scored[1][0] == best):
        m = difflib.get_close_matches(label, _CANON, n=1, cutoff=0.85)  # last resort for other kinds of damage
        if not m:
            return None
        name = m[0]
    return NATIONAL_LABEL if name == NATIONAL_FULL else name


def _merge_split_numbers(words: list) -> list:
    """Some fonts make pdfplumber split '1,998' into '1,9' + '98'; glue such pairs back."""
    out = []
    i = 0
    while i < len(words):
        w = words[i]
        if i + 1 < len(words):
            n = words[i + 1]
            if re.fullmatch(r"\d,\d{1,2}", w["text"]) and re.fullmatch(r"\d{1,2}", n["text"]) and len(w["text"].split(",")[1]) + len(n["text"]) == 3 \
                    and abs(n["top"] - w["top"]) < 2 and 0 <= n["x0"] - w["x1"] < 8:
                out.append({**w, "text": w["text"] + n["text"], "x1": n["x1"]})
                i += 2
                continue
        out.append(w)
        i += 1
    return out


def parse_bulletin_pdf(data: bytes, fallback_columns: list[str] | None = None) -> ParsedBulletin:
    """fallback_columns: column order to assume when the PDF has no readable header
    (a few 2018 bulletins); normally the previous day's columns."""
    rows_out: list[PriceRow] = []
    anchors: list[tuple[float, str]] = []
    seen_prefectures: set[str] = set()
    used_fallback = False  # noqa: F841 (kept for debugging)
    full_text = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            words = _merge_split_numbers(page.extract_words())
            full_text.append(fix_garble(page.extract_text() or ""))
            page_anchors = _find_anchors(words)
            if len(page_anchors) >= 3:
                anchors = page_anchors
            if not anchors and fallback_columns:
                anchors = _infer_anchors_from_cells(words, fallback_columns)
                used_fallback = bool(anchors)
            if not anchors:
                continue
            groups = _group_rows(words)
            for gi, row in enumerate(groups):
                row.sort(key=lambda w: w["x0"])
                values = [w for w in row if VALUE_RE.match(w["text"])]
                label_words = [w for w in row if w not in values]
                if values and not label_words:
                    # label wrapped onto two lines with the numbers vertically centred between them
                    for other in groups[max(0, gi - 1):gi] + groups[gi + 1:gi + 2]:
                        if abs(other[0]["top"] - row[0]["top"]) <= 10 and not any(VALUE_RE.match(w["text"]) for w in other):
                            label_words += other
                label = fix_garble(" ".join(w["text"] for w in sorted(label_words, key=lambda w: (w["top"], w["x0"])))).strip()
                if not values or not (label.startswith("ΝΟΜΟ") or NATIONAL_RE.match(label) or label.startswith("ΠΑΝ")):
                    continue
                prefecture = snap_label(label)
                if prefecture is None:
                    log.warning("unrecognised row label %r", label)
                    continue
                if prefecture in seen_prefectures:
                    log.warning("label %r resolved to %r which this bulletin already has; skipped", label, prefecture)
                    continue
                seen_prefectures.add(prefecture)
                if len(values) == len(anchors):
                    assigned = [(w, f) for w, (_, f) in zip(values, anchors)]
                else:
                    assigned, seen = [], set()
                    for w in values:
                        cx = (w["x0"] + w["x1"]) / 2
                        dist, fuel = min((abs(cx - ax), f) for ax, f in anchors)
                        if dist > MAX_ANCHOR_DISTANCE or fuel in seen:
                            log.warning("unassigned cell %r in %r (dist %.0f)", w["text"], prefecture, dist)
                            continue
                        seen.add(fuel)
                        assigned.append((w, fuel))
                for w, fuel in assigned:
                    if w["text"] in MISSING:
                        continue
                    rows_out.append(PriceRow(prefecture, fuel, float(w["text"].replace(",", "."))))
    text = "\n".join(full_text)
    return ParsedBulletin(parse_date(text), rows_out, [f for _, f in anchors])
