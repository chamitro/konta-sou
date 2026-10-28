"""Planned power cuts from ΔΕΔΔΗΕ's public lookup (siteapps.deddie.gr/outages2public), per Attica municipality.

The lookup is a plain form: POST the prefecture and municipality, then GET the numbered pages.
We call it once a day per municipality with a pause between requests and an honest User-Agent.
"""
from __future__ import annotations

import argparse
import html
import json
import logging
import re
import time
import unicodedata
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

import httpx
from sqlalchemy import delete, select

from simera.db import SessionLocal, init_db
from simera.models import PowerOutage

log = logging.getLogger(__name__)
BASE = "https://siteapps.deddie.gr/Outages2Public"
USER_AGENT = "simera-collector/0.1 (+https://github.com/chamitro/konta-sou)"
DATA = Path(__file__).resolve().parent.parent / "data" / "deddie_municipalities_attica.json"
MUNICIPALITIES: list[dict] = json.loads(DATA.read_text(encoding="utf-8"))["municipalities"]
PREFECTURE_ID = json.loads(DATA.read_text(encoding="utf-8"))["prefecture_id"]

_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL = re.compile(r"<td[^>]*>(.*?)</td>", re.S)
_PAGE = re.compile(r"page=(\d+)")


def parse_dt(s: str) -> datetime:
    """'29/10/2026 8:00:00 πμ' -> datetime (Athens local, naive)."""
    s = s.strip()
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4}) (\d{1,2}):(\d{2})(?::(\d{2}))?\s*(πμ|μμ|ΠΜ|ΜΜ)?", s)
    if not m:
        raise ValueError(f"bad datetime {s!r}")
    d, mo, y, h, mi, _, ampm = m.groups()
    h = int(h)
    if ampm and ampm.lower() == "μμ" and h < 12:
        h += 12
    if ampm and ampm.lower() == "πμ" and h == 12:
        h = 0
    return datetime(int(y), int(mo), int(d), h, int(mi))


def parse_table(page: str) -> tuple[list[dict], int]:
    """Rows of the results table and the number of pages linked from it."""
    rows = []
    for tr in _ROW.findall(page):
        cells = [html.unescape(re.sub(r"<[^>]+>", " ", c)).strip() for c in _CELL.findall(tr)]
        if len(cells) < 6:
            continue
        try:
            rows.append({"starts_at": parse_dt(cells[0]), "ends_at": parse_dt(cells[1]), "municipality": cells[2], "area": " ".join(cells[3].split()), "note_no": cells[4], "purpose": cells[5]})
        except ValueError:
            continue
    pages = max([int(p) for p in _PAGE.findall(page)] + [1])
    return rows, pages


def fetch_municipality(client: httpx.Client, mid: int, delay: float = 1.0) -> list[dict]:
    r = client.post(f"{BASE}/?Length=4", data={"PrefectureID": PREFECTURE_ID, "MunicipalityID": mid}, headers={"X-Requested-With": "XMLHttpRequest"})
    r.raise_for_status()
    rows, pages = parse_table(r.text)
    for p in range(2, pages + 1):
        time.sleep(delay)
        rp = client.get(f"{BASE}/Home/OutagesPartial", params={"page": p, "municipalityID": mid, "prefectureID": PREFECTURE_ID}, headers={"X-Requested-With": "XMLHttpRequest"})
        rp.raise_for_status()
        more, _ = parse_table(rp.text)
        rows.extend(more)
    return rows


def collect(delay: float = 1.0, only: list[int] | None = None) -> dict:
    init_db()
    fetched_at = datetime.utcnow().replace(microsecond=0)
    total, failed = 0, 0
    with httpx.Client(headers={"User-Agent": USER_AGENT, "Accept-Language": "el"}, timeout=30, follow_redirects=True) as client:
        client.get(f"{BASE}/")   # cookies
        for m in MUNICIPALITIES:
            if only and m["id"] not in only:
                continue
            try:
                rows = fetch_municipality(client, m["id"], delay)
            except Exception as e:  # noqa: BLE001
                failed += 1
                log.warning("deddie %s (%s): %s", m["name"], m["id"], e)
                continue
            with SessionLocal() as s:
                s.execute(delete(PowerOutage).where(PowerOutage.municipality_id == m["id"]))
                seen = set()
                for r in rows:
                    key = (r["note_no"], r["starts_at"])
                    if key in seen:
                        continue
                    seen.add(key)
                    s.add(PowerOutage(municipality_id=m["id"], municipality=m["name"], fetched_at=fetched_at, **{k: v for k, v in r.items() if k != "municipality"}))
                s.commit()
            total += len(rows)
            time.sleep(delay)
    return {"municipalities": len(only) if only else len(MUNICIPALITIES), "outages": total, "failed": failed}


# ---- matching a place to ΔΕΔΔΗΕ municipalities --------------------------------------------------

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").upper()
    s = re.sub(r"\bΔΗΜΟΣ\b|\bΔΗΜΟΤΙΚΗ ΕΝΟΤΗΤΑ\b|\bΚΟΙΝΟΤΗΤΑ\b", " ", s)
    s = re.sub(r"\bΑΓ(?:ΙΑΣ|ΙΟΥ|ΙΩΝ|ΙΟΙ|ΙΑ)?\.?\s*", "ΑΓ ", s)
    s = s.replace("-", " ").replace(".", " ")
    return " ".join(s.split())


def match_municipalities(*names: str, cutoff: float = 0.82) -> list[dict]:
    """ΔΕΔΔΗΕ municipalities whose name resembles any of the given place names (municipality, town, suburb)."""
    out, seen = [], set()
    for name in names:
        n = _norm(name)
        if not n:
            continue
        for m in MUNICIPALITIES:
            if m["id"] in seen:
                continue
            score = SequenceMatcher(None, n, _norm(m["name"])).ratio()
            if score >= cutoff:
                out.append({**m, "score": round(score, 2)})
                seen.add(m["id"])
    return sorted(out, key=lambda m: -m["score"])


def upcoming(municipality_ids: list[int], now: datetime, horizon_days: int = 3) -> list[dict]:
    from datetime import timedelta
    with SessionLocal() as s:
        rows = s.execute(select(PowerOutage).where(PowerOutage.municipality_id.in_(municipality_ids), PowerOutage.ends_at >= now, PowerOutage.starts_at <= now + timedelta(days=horizon_days)).order_by(PowerOutage.starts_at)).scalars().all()
        return [{"municipality": r.municipality, "area": r.area, "note_no": r.note_no, "purpose": r.purpose, "starts_at": r.starts_at.isoformat(), "ends_at": r.ends_at.isoformat(), "fetched_at": r.fetched_at.isoformat()} for r in rows]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--delay", type=float, default=1.0)
    p.add_argument("--only", type=int, nargs="*", help="ΔΕΔΔΗΕ municipality ids")
    a = p.parse_args()
    print(collect(delay=a.delay, only=a.only))
