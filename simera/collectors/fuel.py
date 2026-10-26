"""Collector for the Greek Fuel Price Observatory (fuelprices.gr).

The ministry publishes a daily PDF bulletin with average retail prices per prefecture.
Station-level data on the site is protected by a CAPTCHA intended to block automated
access, so this collector deliberately uses only the openly published bulletins.
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from simera.db import SessionLocal, init_db
from simera.models import FuelBulletin, FuelPrice

log = logging.getLogger(__name__)

BASE_URL = "https://www.fuelprices.gr"
LIST_URL = f"{BASE_URL}/deltia_dn.view"
RAW_DIR = Path("data/raw/fuel")
USER_AGENT = "simera-collector/0.1 (+contact: project owner)"

MIN_DATE = date(2018, 1, 1)  # 2017 bulletins are Excel exports with columns spilling onto extra pages; not supported
FILENAME_RE = re.compile(r"IMERISIO_DELTIO_ANA_NOMO_(\d{2})_(\d{2})_(\d{4})\.pdf")

from simera.collectors.fuel_parser import ParsedBulletin, parse_bulletin_pdf  # noqa: E402


def date_from_filename(url: str) -> date | None:
    m = FILENAME_RE.search(url)
    return date(int(m.group(3)), int(m.group(2)), int(m.group(1))) if m else None


def list_bulletin_urls(client: httpx.Client) -> dict[date, str]:
    """Return {price_date: absolute_url} for every per-prefecture daily bulletin listed on the site."""
    r = client.get(LIST_URL)
    r.raise_for_status()
    html = r.content.decode("windows-1253", errors="replace")
    out: dict[date, str] = {}
    for href in re.findall(r'href="(\./files/deltia/IMERISIO_DELTIO_ANA_NOMO_[^"]+\.pdf)"', html):
        url = BASE_URL + href[1:]
        d = date_from_filename(url)
        if d:
            out[d] = url
    return out


def _columns_before(session, d: date) -> list[str] | None:
    row = session.execute(
        select(FuelBulletin.columns).where(FuelBulletin.price_date < d, FuelBulletin.columns != "").order_by(FuelBulletin.price_date.desc()).limit(1)
    ).first()
    return row[0].split(",") if row and row[0] else None


def store_bulletin(session, url: str, price_date: date, parsed: ParsedBulletin) -> int:
    existing = session.scalar(select(FuelBulletin).where(FuelBulletin.url == url))
    if existing:
        return 0
    stmt = sqlite_insert(FuelPrice).values(
        [dict(price_date=price_date, prefecture=r.prefecture, fuel_type=r.fuel_type, price=r.price) for r in parsed.rows]
    )
    if parsed.rows:
        session.execute(stmt.on_conflict_do_update(index_elements=["price_date", "prefecture", "fuel_type"], set_={"price": stmt.excluded.price}))
    session.add(FuelBulletin(kind="daily_prefecture", price_date=price_date, url=url, rows_parsed=len(parsed.rows), columns=",".join(parsed.columns)))
    session.commit()
    return len(parsed.rows)


def collect(since: date | None = None, limit: int | None = None, keep_raw: bool = True, delay: float = 0.5) -> int:
    """Download and parse bulletins not yet stored. Returns number of bulletins processed."""
    init_db()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    processed = 0
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=60, follow_redirects=True) as client, SessionLocal() as session:
        known = set(session.scalars(select(FuelBulletin.url)).all())
        urls = list_bulletin_urls(client)
        todo = sorted((d, u) for d, u in urls.items() if u not in known and d >= MIN_DATE and (since is None or d >= since))
        if limit:
            todo = todo[-limit:]
        log.info("%d bulletins listed, %d to fetch", len(urls), len(todo))
        last_columns: list[str] | None = None
        for d, url in todo:
            raw_path = RAW_DIR / url.rsplit("/", 1)[1]
            if raw_path.exists():
                data = raw_path.read_bytes()
            else:
                r = client.get(url)
                if r.status_code != 200:
                    log.warning("skip %s: HTTP %s", url, r.status_code)
                    continue
                data = r.content
                if keep_raw:
                    raw_path.write_bytes(data)
                time.sleep(delay)
            try:
                parsed = parse_bulletin_pdf(data, fallback_columns=last_columns or _columns_before(session, d))
            except Exception as e:  # corrupt PDF etc.
                log.warning("parse failed for %s: %s", url, e)
                continue
            price_date = parsed.price_date or d
            if parsed.price_date and parsed.price_date != d:
                log.warning("date in PDF %s differs from filename %s; using PDF date", parsed.price_date, d)
            n = store_bulletin(session, url, price_date, parsed)
            if parsed.columns:
                last_columns = parsed.columns
            log.info("%s: %d rows", price_date, n)
            processed += 1
    return processed


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Collect fuel price bulletins from fuelprices.gr")
    p.add_argument("--days", type=int, default=14, help="fetch bulletins from the last N days (default 14)")
    p.add_argument("--all", action="store_true", help="fetch the whole archive (back to 2018)")
    p.add_argument("--limit", type=int, help="max bulletins to fetch in this run")
    p.add_argument("--discard-raw", action="store_true", help="do not keep the downloaded PDFs on disk")
    p.add_argument("--delay", type=float, default=0.5, help="seconds to wait between downloads")
    p.add_argument("--repair", action="store_true", help="re-fetch bulletins that look wrongly parsed")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    if a.repair:
        print(f"re-fetched {repair(dry_run=a.dry_run)} bulletins")
        return 0
    since = None if a.all else date.today() - timedelta(days=a.days)
    n = collect(since=since, limit=a.limit, keep_raw=not a.discard_raw, delay=a.delay)
    print(f"processed {n} bulletins")
    return 0


if __name__ == "__main__":
    sys.exit(main())


EXPECTED_MIN_ROWS = 52 * 4  # 51 prefectures + national average, at least 4 fuel columns


def repair(dry_run: bool = False) -> int:
    """Re-fetch bulletins that look wrongly parsed: too few rows, or a price date that
    disagrees with the filename. Removes their stored prices first so the re-parse is clean."""
    init_db()
    with SessionLocal() as session:
        bulletins = session.scalars(select(FuelBulletin)).all()
        suspicious = [b for b in bulletins if b.rows_parsed < EXPECTED_MIN_ROWS or date_from_filename(b.url) != b.price_date or b.price_date < MIN_DATE]
        dates = {b.price_date for b in suspicious} | {date_from_filename(b.url) for b in suspicious}
        victims = [b for b in bulletins if b.price_date in dates or date_from_filename(b.url) in dates]
        log.info("%d suspicious bulletins, %d bulletins/%d dates to re-fetch", len(suspicious), len(victims), len(dates))
        if dry_run:
            for b in suspicious[:20]:
                log.info("  %s rows=%d filename_date=%s", b.price_date, b.rows_parsed, date_from_filename(b.url))
            return len(victims)
        for b in victims:
            session.delete(b)
        from sqlalchemy import delete

        session.execute(delete(FuelPrice).where(FuelPrice.price_date.in_(list(dates))))
        session.commit()
    return collect(since=None, keep_raw=False)
