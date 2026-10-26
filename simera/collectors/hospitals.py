"""On-duty hospitals for Attica from the Ministry of Health daily rota.

Source: https://www.moh.gov.gr/articles/citizen/efhmeries-nosokomeiwn/68-efhmeries-nosokomeiwn-attikhs
publishes one Word (.doc) and one PDF per day. We download the .doc, convert it to HTML with
LibreOffice (soffice --headless) and parse the table: one row block per clinic specialty, one
column per shift, hospitals listed inside the cells, with region sub-headers such as ΠΕΙΡΑΙΑΣ.
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from simera.db import SessionLocal, init_db
from simera.models import HealthCenterDuty, HospitalDuty, HospitalRota

log = logging.getLogger(__name__)

PAGE_URL = "https://www.moh.gov.gr/articles/citizen/efhmeries-nosokomeiwn/68-efhmeries-nosokomeiwn-attikhs"
USER_AGENT = "simera-collector/0.1 (+contact: project owner)"
HOSPITALS_FILE = Path(__file__).resolve().parent.parent / "data" / "attica_hospitals.json"

FILE_RE = re.compile(r'href="\?fdl=(\d+)"[^>]*?title="Download: efimeria_(\d{8})\.doc', re.S)
TIME_RE = re.compile(r"\d\d:\d\d")
REGION_WORDS = {"ΠΕΙΡΑΙΑΣ", "ΠΕΙΡΑΙΑ", "ΑΝΑΤΟΛΙΚΗ ΑΤΤΙΚΗ", "ΑΝΑΤ. ΑΤΤΙΚΗ", "ΔΥΤΙΚΗ ΑΤΤΙΚΗ", "ΔΥΤ. ΑΤΤΙΚΗ"}
# institution-type prefixes that precede the «name»: Γ.Ν.Α., Π.Γ.Ν., Ν.Δ.Ν.Α., Γ.Ο.Ν.Κ., Γ.Ν.Ν.ΙΩΝΙΑΣ, Γ.Ν.Ν.Θ.Α. ...
PREFIX_TOKEN_RE = re.compile(r"^\.?(?:[Α-ΩΆ-Ώ]{1,2}\.)*(?:[Α-ΩΆ-Ώ]{1,2}|[Α-ΩΆ-Ώ]{3,}(?:Σ)?)?\.?$|^Γ\.Ν\.Ν\.ΙΩΝΙΑΣ$")


def _is_prefix(tok: str) -> bool:
    return bool(PREFIX_TOKEN_RE.match(tok)) and ("." in tok or len(tok) <= 2)
HC_RE = re.compile(r"(Κ\.Υ\.\s*[Α-ΩΆ-ΏΪ\. ]+?)\s*:\s*\(([^)]*)\)")
_ACCENTS = str.maketrans("ΆΈΉΊΌΎΏΪΫάέήίόύώϊΐΰϋ", "ΑΕΗΙΟΥΩΙΥαεηιουωιιυυ")


@dataclass
class DutyEntry:
    specialty: str
    shift: str
    hospital: str
    region: str = ""
    note: str = ""
    key: str = ""


@dataclass
class ParsedRota:
    duty_date: date | None
    shifts: list[str]
    entries: list[DutyEntry]
    health_centers: list[tuple[str, str, str]] = field(default_factory=list)  # (name, hours, key)


# ---- hospital directory -----------------------------------------------------

def _norm(s: str) -> str:
    s = s.upper().translate(_ACCENTS)
    s = s.replace("«", " ").replace("»", " ").replace(".", "").replace("-", " ")
    return re.sub(r"\s+", " ", s).strip()


def load_hospitals() -> list[dict]:
    return json.loads(HOSPITALS_FILE.read_text(encoding="utf-8"))["hospitals"]


_HOSPITALS = load_hospitals()
_HOSPITAL_BY_KEY = {h["key"]: h for h in _HOSPITALS}


def match_hospital(text: str) -> str:
    n = " " + _norm(text) + " "
    for h in _HOSPITALS:  # pass 1: whole words
        if any(" " + _norm(m) + " " in n for m in h["match"]):
            return h["key"]
    compact = n.replace(" ", "")
    for h in _HOSPITALS:  # pass 2: loose substring (handles ΑΓ.ΑΝΑΡΓΥΡΟΙ vs ΑΓ ΑΝΑΡΓΥΡΟΙ, ΑΣΚΛΗΠΙΕΙΟΥ ...)
        if any(len(_norm(m)) >= 6 and _norm(m).replace(" ", "") in compact for m in h["match"]):
            return h["key"]
    return ""


def hospital_info(key: str) -> dict | None:
    return _HOSPITAL_BY_KEY.get(key)


# ---- HTML table -> grid ----------------------------------------------------

def _cell_paragraphs(cell_html: str) -> list[str]:
    cell_html = re.sub(r"<br\s*/?>|</p>|</div>", "\n", cell_html, flags=re.I)
    text = html.unescape(re.sub(r"<[^>]+>", "", cell_html))
    text = re.sub(r"[\ue000-\uf8ff\xa0\u200b]", " ", text)  # symbol-font glyphs (Wingdings bullets), nbsp, zero-width
    return [re.sub(r"\s+", " ", p).strip() for p in text.split("\n") if p.strip()]


def table_grid(table_html: str) -> list[list[tuple[int, int, list[str]]]]:
    """Rows of (start_col, span, paragraphs) on the table's base column grid, with rowspans
    expanded into the rows they cover. Word tables use different colspans per row, so column
    identity must later be decided by overlap, not by index."""
    grid: list[list[tuple[int, int, list[str]]]] = []
    pending: list[tuple[int, int, int, list[str]]] = []  # (start, span, rows_left, paras)
    for row_html in re.findall(r"<tr.*?</tr>", table_html, re.S | re.I):
        cells = re.findall(r"<td([^>]*)>(.*?)</td>", row_html, re.S | re.I)
        row: list[tuple[int, int, list[str]]] = [(st, sp, paras) for st, sp, _, paras in pending]
        occupied = sorted((st, st + sp) for st, sp, _, _ in pending)
        col, ci = 0, 0
        while ci < len(cells):
            # skip base columns covered by a rowspan from above
            while any(a <= col < b for a, b in occupied):
                col = next(b for a, b in occupied if a <= col < b)
            attrs, c = cells[ci]
            ci += 1
            rs = int((re.search(r'rowspan="?(\d+)', attrs, re.I) or [0, 1])[1])
            cs = int((re.search(r'colspan="?(\d+)', attrs, re.I) or [0, 1])[1])
            paras = _cell_paragraphs(c)
            row.append((col, cs, paras))
            if rs > 1:
                pending.append((col, cs, rs - 1, paras))
            col += cs
        pending = [(st, sp, left - 1, paras) for st, sp, left, paras in pending if left - 1 > 0]
        grid.append(sorted(row))
    return grid


def _overlap(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(0, min(a[0] + a[1], b[0] + b[1]) - max(a[0], b[0]))


# ---- cell text -> hospitals ---------------------------------------------------

def split_hospitals(paragraphs: list[str], region: str = "", state: dict | None = None) -> list[tuple[str, str, str]]:
    """Turn a cell's paragraphs into [(hospital, region, note)].

    `region` is the sub-header in force from earlier rows of the same column (the table puts
    'ΠΕΙΡΑΙΑΣ' in one row and the hospitals in the rows below); the final region is written to
    state["region"] when a state dict is given.

    Cells read like: 'ΠΕΙΡΑΙΑΣ', 'Γ.Ν.Ν.', '«ΑΓ. ΠΑΝΤΕΛΕΗΜΩΝ»', 'Γ.Ν. «ΑΣΚΛΗΠΙΕΙΟ» ΒΟΥΛΑΣ', 'Γ.Ν.Α. «ΠΑΜΜΑΚΑΡΙΣΤΟ» έως 23:00'.
    """
    tokens = " ".join(paragraphs).replace("« ", "«").replace(" »", "»").split()
    out: list[tuple[str, str, str]] = []
    prefix: list[str] = []
    i = 0
    while i < len(tokens):
        t = tokens[i]
        if t in REGION_WORDS or (i + 1 < len(tokens) and f"{t} {tokens[i + 1]}" in REGION_WORDS):
            if t not in REGION_WORDS:
                i += 1
                t = f"{t} {tokens[i]}"
            region = t
            prefix = []
            i += 1
            continue
        if TIME_RE.search(t) or t in ("–", "-"):  # stray header fragments like '08:00 – 14:30'
            i += 1
            continue
        if "«" in t:
            name_tokens = [t]
            while "»" not in name_tokens[-1] and i + 1 < len(tokens):
                i += 1
                name_tokens.append(tokens[i])
            i += 1
            # trailing capital words belong to the name (ΒΟΥΛΑΣ); lowercase / numeric words are a note (έως 23:00)
            suffix, note = [], []
            while i < len(tokens) and "«" not in tokens[i] and tokens[i] not in REGION_WORDS and not _is_prefix(tokens[i]):
                (note if (tokens[i][:1].islower() or TIME_RE.search(tokens[i]) or note) else suffix).append(tokens[i])
                i += 1
            name = " ".join(prefix + name_tokens + suffix)
            out.append((name, region, " ".join(note)))
            prefix = []
            continue
        if _is_prefix(t):
            if prefix and t.startswith(".") and not prefix[-1].endswith("."):
                prefix[-1] += t  # "Γ" + ".Ο.Ν.Κ." split by a soft line break
            else:
                prefix.append(t)
        else:
            log.debug("ignoring token %r", t)
        i += 1
    if state is not None:
        state["region"] = region
    return out


# ---- interpret a whole document ---------------------------------------------

def parse_rota_html(doc_html: str) -> ParsedRota:
    body = doc_html[doc_html.lower().find("<body"):] if "<body" in doc_html.lower() else doc_html
    text = html.unescape(re.sub(r"<[^>]+>", " ", body))
    text = re.sub(r"\s+", " ", text)
    m = re.search(r"(?:ΔΕΥΤΕΡΑ|ΤΡΙΤΗ|ΤΕΤΑΡΤΗ|ΠΕΜΠΤΗ|ΠΑΡΑΣΚΕΥΗ|ΣΑΒΒΑΤΟ|ΚΥΡΙΑΚΗ)\s+(\d{1,2})\s+([Α-ΩΆ-Ώ]+)\s+(\d{4})", text)
    duty_date = _greek_date(m) if m else None
    health_centers = []
    for name, hours in HC_RE.findall(text):
        name = re.sub(r"\s+", " ", name).strip()
        hours = re.sub(r"\s+", " ", hours).strip()
        health_centers.append((name, hours, match_hospital(name)))

    shifts: list[str] = []
    entries: list[DutyEntry] = []
    seen: set[tuple] = set()
    for table_html in re.findall(r"<table.*?</table>", doc_html, re.S | re.I):
        grid = table_grid(table_html)
        hdr_i = next((i for i, r in enumerate(grid) if any(p.startswith("Κλινικ") for _, _, v in r for p in v)), None)
        if hdr_i is None:
            continue
        hdr = grid[hdr_i]
        spec_hdr = next((st, sp) for st, sp, v in hdr if any(p.startswith("Κλινικ") for p in v))
        shift_hdrs = [((st, sp), re.sub(r"\s+", " ", " ".join(v)).strip()) for st, sp, v in hdr if (st, sp) != spec_hdr and TIME_RE.search(" ".join(v))]
        for _, label in shift_hdrs:
            if label not in shifts:
                shifts.append(label)

        def column_of(st: int, sp: int) -> str | None:
            """'spec', a shift label, or None (notes column / nothing overlapping)."""
            best, best_ov = None, 0
            for span, label in [(spec_hdr, "spec")] + shift_hdrs:
                ov = _overlap((st, sp), span)
                if ov > best_ov:
                    best, best_ov = label, ov
            return best

        specialty = None
        region_by_col: dict[str, str] = {}
        last_hosp_col = shift_hdrs[0][1] if shift_hdrs else None
        for row in grid[hdr_i + 1:]:
            by_col: dict[str, list[str]] = {}
            if len(row) == 1 and "«" in " ".join(row[0][2]) and last_hosp_col:
                # orphan continuation row: Word dropped the empty cells, leaving one hospital cell at column 0
                by_col[last_hosp_col] = list(row[0][2])
            else:
                for st, sp, paras in row:
                    label = column_of(st, sp)
                    if label:
                        by_col.setdefault(label, []).extend(paras)
                        if label != "spec" and "«" in " ".join(paras):
                            last_hosp_col = label
            sp_text = " ".join(by_col.get("spec", [])).strip()
            if sp_text.startswith("Κλινικ"):
                continue
            if sp_text and not TIME_RE.search(sp_text) and "«" not in sp_text and sp_text != specialty:
                specialty = sp_text
                region_by_col = {}
            if not specialty:
                continue
            for _, shift in shift_hdrs:
                state: dict = {}
                found = split_hospitals(by_col.get(shift, []), region_by_col.get(shift, ""), state)
                region_by_col[shift] = state["region"]
                for hosp, region, note in found:
                    key = (specialty, shift, hosp)
                    if key in seen:
                        continue
                    seen.add(key)
                    entries.append(DutyEntry(specialty, shift, hosp, region, note, match_hospital(hosp)))
    return ParsedRota(duty_date, shifts, entries, health_centers)


GREEK_MONTHS = {"ΙΑΝΟΥΑΡΙΟΥ": 1, "ΦΕΒΡΟΥΑΡΙΟΥ": 2, "ΜΑΡΤΙΟΥ": 3, "ΑΠΡΙΛΙΟΥ": 4, "ΜΑΪΟΥ": 5, "ΜΑΙΟΥ": 5, "ΙΟΥΝΙΟΥ": 6,
                "ΙΟΥΛΙΟΥ": 7, "ΑΥΓΟΥΣΤΟΥ": 8, "ΣΕΠΤΕΜΒΡΙΟΥ": 9, "ΟΚΤΩΒΡΙΟΥ": 10, "ΝΟΕΜΒΡΙΟΥ": 11, "ΔΕΚΕΜΒΡΙΟΥ": 12}


def _greek_date(m) -> date | None:
    month = GREEK_MONTHS.get(m.group(2).translate(_ACCENTS))
    return date(int(m.group(3)), month, int(m.group(1))) if month else None


# ---- fetching -------------------------------------------------------------------

def _get_page(client: httpx.Client, url: str, params: dict | None = None) -> httpx.Response:
    """Retry on a fresh connection, then over plain http (which redirects to https): the
    ministry's front end has answered 421 Misdirected Request from some hosting networks."""
    last: Exception | None = None
    for attempt, u in enumerate([url, url, url.replace("https://", "http://", 1)]):
        try:
            with httpx.Client(headers={"User-Agent": USER_AGENT, "Accept-Language": "el"}, timeout=60, follow_redirects=True) as fresh:
                r = fresh.get(u, params=params)
            if r.status_code == 200:
                return r
            last = httpx.HTTPStatusError(f"HTTP {r.status_code} for {u}", request=r.request, response=r)
            log.warning("moh.gov.gr attempt %d: HTTP %s", attempt + 1, r.status_code)
        except httpx.HTTPError as e:
            last = e
            log.warning("moh.gov.gr attempt %d: %s", attempt + 1, e)
        time.sleep(2)
    raise last  # type: ignore[misc]


def list_documents(client: httpx.Client) -> dict[date, str]:
    r = _get_page(client, PAGE_URL)
    out = {}
    for fid, ymd in FILE_RE.findall(r.text):
        out[datetime.strptime(ymd, "%Y%m%d").date()] = fid
    return out


def doc_to_html(doc_bytes: bytes) -> str:
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "rota.doc"
        src.write_bytes(doc_bytes)
        subprocess.run(
            ["soffice", "--headless", f"-env:UserInstallation=file://{td}/profile", "--convert-to", "html", "--outdir", td, str(src)],
            check=True, capture_output=True, timeout=180,
        )
        return (Path(td) / "rota.html").read_text(encoding="utf-8", errors="replace")


def store(session, day: date, source_id: str, parsed: ParsedRota) -> None:
    from sqlalchemy import delete

    # replace the day's rota wholesale: the ministry re-issues corrected documents, and parser fixes must not leave stale rows behind
    session.execute(delete(HospitalDuty).where(HospitalDuty.duty_date == day))
    session.execute(delete(HealthCenterDuty).where(HealthCenterDuty.duty_date == day))
    if parsed.entries:
        stmt = sqlite_insert(HospitalDuty).values(
            [dict(duty_date=day, specialty=e.specialty, shift=e.shift, hospital=e.hospital, hospital_key=e.key, region=e.region, note=e.note) for e in parsed.entries]
        )
        session.execute(stmt.on_conflict_do_update(index_elements=["duty_date", "specialty", "shift", "hospital"], set_={"hospital_key": stmt.excluded.hospital_key, "region": stmt.excluded.region, "note": stmt.excluded.note}))
    if parsed.health_centers:
        stmt = sqlite_insert(HealthCenterDuty).values([dict(duty_date=day, name=n, hours=h, hospital_key=k) for n, h, k in parsed.health_centers])
        session.execute(stmt.on_conflict_do_update(index_elements=["duty_date", "name"], set_={"hours": stmt.excluded.hours, "hospital_key": stmt.excluded.hospital_key}))
    stmt = sqlite_insert(HospitalRota).values(duty_date=day, source_id=source_id, entries=len(parsed.entries))
    session.execute(stmt.on_conflict_do_update(index_elements=["duty_date"], set_={"source_id": source_id, "entries": len(parsed.entries), "fetched_at": datetime.utcnow()}))
    session.commit()


def collect(days_back: int = 1, refresh_today: bool = True, force: bool = False) -> int:
    init_db()
    today = date.today()
    n = 0
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True) as client, SessionLocal() as session:
        docs = list_documents(client)
        have = {r.duty_date: r.source_id for r in session.scalars(select(HospitalRota)).all()}
        for day in sorted(docs):
            if day < today - timedelta(days=days_back):
                continue
            if not force and have.get(day) == docs[day] and not (refresh_today and day >= today):
                continue
            r = _get_page(client, PAGE_URL, params={"fdl": docs[day]})
            if "msword" not in r.headers.get("content-type", ""):
                log.warning("%s: unexpected response %s %s", day, r.status_code, r.headers.get("content-type"))
                continue
            parsed = parse_rota_html(doc_to_html(r.content))
            if parsed.duty_date and parsed.duty_date != day:
                log.warning("%s: document says %s", day, parsed.duty_date)
            store(session, day, docs[day], parsed)
            unmatched = sorted({e.hospital for e in parsed.entries if not e.key})
            log.info("%s: %d entries, %d specialties, %d health centres%s", day, len(parsed.entries), len({e.specialty for e in parsed.entries}), len(parsed.health_centers), f"; unmatched: {unmatched}" if unmatched else "")
            n += 1
            time.sleep(1)
    return n


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Collect Attica hospital duty rotas (Ministry of Health)")
    p.add_argument("--days-back", type=int, default=1)
    p.add_argument("--force", action="store_true", help="re-fetch days already stored")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    print(f"fetched {collect(a.days_back, force=a.force)} rota documents")
    return 0


if __name__ == "__main__":
    sys.exit(main())
