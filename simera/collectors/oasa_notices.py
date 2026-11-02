"""OASA announcements: bus and trolley route changes from the operator's own news feed.

www.oasa.gr publishes every diversion, suspension or holiday schedule as a WordPress post, with an
RSS feed (https://www.oasa.gr/feed/, 10 items a page, ?paged=N for older ones). The title names the
lines ("γραμμών 219 και 816") and usually the municipality ("στον Δήμο Αγ. Δημητρίου"); the post body
carries the dates and hours. We keep the feed's items for a few weeks, fetch each new post once,
and match lines and municipalities so the page can answer "does any change touch my area or my stops?".
"""
from __future__ import annotations

import argparse
import html
import logging
import re
import time
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import httpx
from sqlalchemy import select

from simera.collectors.outages import MUNICIPALITIES, _norm, match_municipalities
from simera.db import SessionLocal, init_db
from simera.models import TransitNotice

log = logging.getLogger(__name__)
FEED = "https://www.oasa.gr/feed/"
UA = "simera-collector/0.1 (+https://github.com/chamitro/konta-sou)"
SOURCE = "ΟΑΣΑ (www.oasa.gr, ανακοινώσεις)"

_SKIP = re.compile(r"Διακήρυξη|διαγωνισμ|Προκήρυξη|Πρόσκληση|ανάθεση|σύμβαση", re.I)
_LATIN = str.maketrans("ABEXGabexg", "ΑΒΕΧΓΑΒΕΧΓ")
# a line code: optional letter (Χ95, Α7, Β12, Ε14, Γ...), 1-3 digits, optional suffix letter (861Β, 535Α); never part of a
# date (04/11/2026), a time (07.00), an ordinal (28ης) or a longer number
_LINE = re.compile(r"(?<![\dA-Za-zΑ-Ωα-ω/.:])([ΧΑΒΕΓXABEG]?\d{1,3}[ΑΒAB]?)(?![\d/.:]|ης|ων|ου|ο\b|η\b)")
_DATE = re.compile(r"\b(\d{1,2})[/.](\d{1,2})[/.](\d{4})\b")
_MUNI = re.compile(r"Δήμ(?:ο|ου|ος|ους)\s+([^,;:()]{3,60})")
_MUNI_STOP = re.compile(r"\s+(?:λόγω|στην|στον|στο|στη|στις|για|με|από|έως|και\s+(?:την|του|της|στ)|κοινότητα|Δημοτική|που|όπου)\b.*$", re.S)
_WS = re.compile(r"\s+")


def _clean(s: str) -> str:
    return _WS.sub(" ", html.unescape(s or "").replace("\xa0", " ")).strip()


def parse_feed(xml: str) -> list[dict]:
    """Items of one feed page: title, url, guid, published (UTC), categories, excerpt."""
    out = []
    for it in re.findall(r"<item>(.*?)</item>", xml, re.S):
        def tag(name: str) -> str:
            m = re.search(rf"<{name}[^>]*>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</{name}>", it, re.S)
            return _clean(m.group(1)) if m else ""
        pub = tag("pubDate")
        try:
            published = parsedate_to_datetime(pub).astimezone(timezone.utc).replace(tzinfo=None)
        except Exception:  # noqa: BLE001
            published = datetime.utcnow()
        out.append({
            "title": tag("title"), "url": tag("link"), "guid": tag("guid") or tag("link"), "published": published,
            "categories": [_clean(c) for c in re.findall(r"<category>(?:<!\[CDATA\[)?(.*?)(?:\]\]>)?</category>", it, re.S)],
            "excerpt": tag("description"),
        })
    return out


def parse_post(page: str) -> str:
    """The announcement's own text (the theme's entry content inside <article>), as plain text."""
    m = re.search(r"<article[^>]*>(.*?)</article>", page, re.S)
    body = m.group(1) if m else page
    m = re.search(r'class="[^"]*wd-entry-content[^"]*"[^>]*>(.*)', body, re.S)
    if m:
        body = m.group(1)
    body = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", body, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", body)
    return _clean(text)


def extract_lines(text: str) -> list[str]:
    """Line codes named in a title, in OASA's LineID spelling (Greek letters, leading zeros kept)."""
    seen: list[str] = []
    for m in _LINE.finditer(text):
        code = m.group(1).translate(_LATIN).upper()
        if code not in seen:
            seen.append(code)
    return seen


def extract_dates(text: str) -> tuple[date | None, date | None, str | None]:
    """First and last dd/mm/yyyy in the text, plus a short 'when' phrase around the first one."""
    found = []
    for m in _DATE.finditer(text):
        try:
            found.append((date(int(m.group(3)), int(m.group(2)), int(m.group(1))), m.start()))
        except ValueError:
            continue
    if not found:
        return None, None, None
    ds = sorted(d for d, _ in found)
    pos = found[0][1]
    start = max(text.rfind(",", 0, pos) + 1, pos - 40)
    end = text.find(",", pos)
    when = text[start: min(end if end > 0 else pos + 70, pos + 90)].strip(" ,")
    return ds[0], ds[-1], when[:120] or None


def extract_municipalities(text: str) -> tuple[list[int], str | None]:
    """ΔΕΔΔΗΕ municipality ids for every 'Δήμο ...' phrase in the text, and the first phrase as written."""
    ids: list[int] = []
    first: str | None = None
    for m in _MUNI.finditer(text):
        phrase = _MUNI_STOP.sub("", m.group(1).replace("–", "-")).strip(" .-")
        if not phrase:
            continue
        first = first or phrase
        words = phrase.replace("-", " ").split()
        parts = [x.strip() for x in phrase.split("-") if x.strip()]
        hit = None
        for cand in [phrase, " ".join(words[:2]), words[0]] + parts:
            hit = match_municipalities(cand)
            if hit:
                break
        if not hit and len(words[0]) >= 5:   # renamed municipalities: "Σπάτων-Αρτέμιδος" is still "ΣΠΑΤΩΝ-ΛΟΥΤΣΑΣ" at ΔΕΔΔΗΕ
            w = _norm(words[0])
            hit = [m for m in MUNICIPALITIES if _norm(m["name"]).startswith(w + " ") or _norm(m["name"]) == w]
        if hit and hit[0]["id"] not in ids:
            ids.append(hit[0]["id"])
    return ids, first


def classify(item: dict, body: str) -> dict | None:
    """Everything we store for one feed item; None for posts that are not service announcements."""
    title = item["title"]
    if _SKIP.search(title):
        return None
    lines = extract_lines(title) or extract_lines(body.split("ως εξής")[0][:400])
    muni_ids, area = extract_municipalities(title + " . " + body[:600])
    starts, ends, when = extract_dates(body)
    return {
        "source_id": item["guid"], "title": title, "url": item["url"], "published": item["published"],
        "starts_on": starts, "ends_on": ends, "when_text": when, "lines": ",".join(lines),
        "municipality_ids": ",".join(str(i) for i in muni_ids), "area_text": area, "summary": body[:700],
    }


def collect(delay: float = 0.7, max_pages: int = 3, lookback_days: int = 21) -> dict:
    """Walk the feed (newest first) until items are older than lookback_days, fetching each new post once."""
    init_db()
    since = datetime.utcnow() - timedelta(days=lookback_days)
    seen = new = skipped = 0
    with httpx.Client(headers={"User-Agent": UA}, timeout=30, follow_redirects=True) as c, SessionLocal() as s:
        known = set(s.scalars(select(TransitNotice.source_id)).all())
        for page in range(1, max_pages + 1):
            r = c.get(FEED, params={"paged": page} if page > 1 else None)
            if r.status_code == 404:
                break
            r.raise_for_status()
            items = parse_feed(r.text)
            if not items:
                break
            for it in items:
                seen += 1
                if it["published"] < since:
                    continue
                if it["guid"] in known:
                    continue
                time.sleep(delay)
                try:
                    body = parse_post(c.get(it["url"]).text)
                except Exception as e:  # noqa: BLE001
                    log.warning("oasa notice %s: %s", it["url"], e)
                    body = it.get("excerpt", "")
                row = classify(it, body)
                if row is None:
                    skipped += 1
                    continue
                s.add(TransitNotice(fetched_at=datetime.utcnow(), **row))
                known.add(it["guid"])
                new += 1
            s.commit()
            if items[-1]["published"] < since:
                break
        # forget old notices
        for old in s.scalars(select(TransitNotice).where(TransitNotice.published < since - timedelta(days=30))).all():
            s.delete(old)
        s.commit()
    return {"seen": seen, "new": new, "skipped": skipped}


def relevant(municipality_ids: list[int], lines: list[str], now: datetime, days_back: int = 14, limit: int = 20) -> list[dict]:
    """Notices that touch the municipalities or the lines (or general ones naming neither), newest and current first."""
    today = now.date()
    lines_n = {l.translate(_LATIN).upper() for l in lines}
    muni = set(municipality_ids)
    with SessionLocal() as s:
        rows = s.scalars(select(TransitNotice).where(TransitNotice.published >= now - timedelta(days=days_back)).order_by(TransitNotice.published.desc())).all()
    out = []
    for n in rows:
        n_lines = set(filter(None, n.lines.split(",")))
        n_muni = {int(x) for x in n.municipality_ids.split(",") if x}
        if n_lines & lines_n:
            match = "line"
        elif n_muni & muni:
            match = "area"
        elif not n_lines and not n_muni:
            match = "general"
        else:
            continue
        if n.ends_on and n.ends_on < today - timedelta(days=1):
            continue  # over
        if match == "general" and not n.starts_on and n.published < now - timedelta(days=5):
            continue  # an undated general notice (holiday schedule) is old news after a few days
        status = "active" if (n.starts_on and n.ends_on and n.starts_on <= today <= n.ends_on) else "upcoming" if (n.starts_on and n.starts_on > today) else "recent"
        out.append({
            "title": n.title, "url": n.url, "published": n.published.replace(tzinfo=timezone.utc).isoformat(), "starts_on": n.starts_on.isoformat() if n.starts_on else None,
            "ends_on": n.ends_on.isoformat() if n.ends_on else None, "when": (n.when_text or "")[:120] or None, "lines": sorted(n_lines), "matched_lines": sorted(n_lines & lines_n),
            "area": n.area_text, "match": match, "status": status, "summary": n.summary[:300],
        })
    order = {"active": 0, "upcoming": 1, "recent": 2}
    out.sort(key=lambda x: (order[x["status"]], {"line": 0, "area": 1, "general": 2}[x["match"]]))   # stable: newest first inside each group
    return out[:limit]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser()
    p.add_argument("--delay", type=float, default=0.7)
    p.add_argument("--pages", type=int, default=3)
    p.add_argument("--days", type=int, default=21)
    a = p.parse_args()
    print(collect(delay=a.delay, max_pages=a.pages, lookback_days=a.days))
