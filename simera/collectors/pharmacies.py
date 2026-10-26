"""On-duty pharmacies for Attica from the Attica Pharmacists' Association site (fsa-efimeries.gr).

The site is an htmx page: POST /Home/FilteredHomeResults with Date=YYYY-MM-DD returns HTML
cards for every pharmacy on duty that day (about 80 in Attica). We fetch each date once a day.
"""
from __future__ import annotations

import argparse
import html
import logging
import re
import sys
import time
from dataclasses import dataclass
from datetime import date, timedelta

import httpx
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from simera.db import SessionLocal, init_db
from simera.models import Pharmacy, PharmacyDuty

log = logging.getLogger(__name__)

BASE_URL = "https://fsa-efimeries.gr"
RESULTS_URL = f"{BASE_URL}/Home/FilteredHomeResults"
REGION = "attica"
USER_AGENT = "simera-collector/0.1 (+contact: project owner)"

CARD_RE = re.compile(r'<div id="(\d+)" class="card w-100">(.*?)<a href="https://www\.google\.gr/maps/search/\?api=1&amp;query=([\d.\-]+)%2C([\d.\-]+)"', re.S)
TAG_RE = re.compile(r"<[^>]+>")

PERIOD_OFFSET = {"ΠΡΩΙ": 0, "ΜΕΣΗΜΕΡΙ": 12, "ΑΠΟΓΕΥΜΑ": 12, "ΒΡΑΔΥ": 12}
TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*(ΠΡΩΙ|ΜΕΣΗΜΕΡΙ|ΑΠΟΓΕΥΜΑ|ΒΡΑΔΥ)(\s+ΕΠΟΜΕΝΗΣ(?:\s+ΗΜΕΡΑΣ)?)?")


@dataclass
class DutyCard:
    pharmacy_id: int
    name: str
    address: str
    area: str
    phone: str
    lat: float
    lng: float
    hours_text: str
    intervals: list[tuple[int, int]]


def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(TAG_RE.sub(" ", s))).strip()


def parse_hours(text: str) -> list[tuple[int, int]]:
    """'8 ΠΡΩΙ - 2 ΜΕΣΗΜΕΡΙ & 5 ΑΠΟΓΕΥΜΑ - 8 ΠΡΩΙ ΕΠΟΜΕΝΗΣ' -> [(480, 840), (1020, 1920)] (minutes from midnight)."""
    out = []
    for part in re.split(r"\s*&\s*", text.upper()):
        times = []
        for m in TIME_RE.finditer(part):
            h = int(m.group(1)) % 12 + PERIOD_OFFSET[m.group(3)]
            if m.group(3) == "ΜΕΣΗΜΕΡΙ" and int(m.group(1)) == 12:
                h = 12
            minutes = h * 60 + int(m.group(2) or 0) + (1440 if m.group(4) else 0)
            times.append(minutes)
        if len(times) == 2:
            start, end = times
            if end <= start:
                end += 1440
            out.append((start, end))
        else:
            log.warning("could not parse hours %r", text)
    return out


def parse_cards(page: str) -> list[DutyCard]:
    cards = []
    for cid, body, lat, lng in CARD_RE.findall(page):
        title = re.search(r'<h6 class="">(.*?)</h6>', body, re.S)
        subtitle = re.search(r'<div class="card-subtitle[^"]*">(.*?)</div>', body, re.S)
        spans = re.findall(r"<span>(.*?)</span>", body, re.S)
        phone = re.search(r'<h6 class="[^"]*text-secondary">(.*?)</h6>', body, re.S)
        if not (title and len(spans) >= 2):
            log.warning("skipping malformed card %s", cid)
            continue
        hours_text = _clean(spans[1])
        cards.append(
            DutyCard(
                pharmacy_id=int(cid),
                name=_clean(spans[0]),
                address=_clean(title.group(1)),
                area=_clean(subtitle.group(1)) if subtitle else "",
                phone=_clean(phone.group(1)) if phone else "",
                lat=float(lat),
                lng=float(lng),
                hours_text=hours_text,
                intervals=parse_hours(hours_text),
            )
        )
    return cards


def fetch_day(client: httpx.Client, day: date) -> list[DutyCard]:
    r = client.post(RESULTS_URL, data={"Date": day.isoformat(), "IsOpen": "false"}, headers={"HX-Request": "true", "Referer": BASE_URL + "/"})
    r.raise_for_status()
    return parse_cards(r.text)


def store_day(session, day: date, cards: list[DutyCard]) -> None:
    if not cards:
        return
    ph = sqlite_insert(Pharmacy).values(
        [dict(id=c.pharmacy_id, region=REGION, name=c.name, address=c.address, area=c.area, phone=c.phone, lat=c.lat, lng=c.lng) for c in cards]
    )
    session.execute(ph.on_conflict_do_update(index_elements=["id"], set_={k: getattr(ph.excluded, k) for k in ("name", "address", "area", "phone", "lat", "lng")}))
    du = sqlite_insert(PharmacyDuty).values(
        [dict(pharmacy_id=c.pharmacy_id, duty_date=day, hours_text=c.hours_text, intervals=";".join(f"{a}-{b}" for a, b in c.intervals)) for c in cards]
    )
    session.execute(du.on_conflict_do_update(index_elements=["pharmacy_id", "duty_date"], set_={"hours_text": du.excluded.hours_text, "intervals": du.excluded.intervals}))
    session.commit()


def collect(days_ahead: int = 7, delay: float = 1.0) -> int:
    init_db()
    today = date.today()
    total = 0
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True) as client, SessionLocal() as session:
        client.get(BASE_URL + "/")  # session cookie
        for i in range(days_ahead + 1):
            day = today + timedelta(days=i)
            cards = fetch_day(client, day)
            store_day(session, day, cards)
            log.info("%s: %d pharmacies on duty", day, len(cards))
            total += len(cards)
            time.sleep(delay)
    return total


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Collect on-duty pharmacies (Attica)")
    p.add_argument("--days-ahead", type=int, default=7)
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    print(f"stored {collect(a.days_ahead)} duty entries")
    return 0


if __name__ == "__main__":
    sys.exit(main())
