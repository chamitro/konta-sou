"""In-process daily scheduler for hosts without cron (e.g. a single free web service).

Enabled with SCHEDULER=1. Runs the light daily collectors (hospitals, pharmacies, fuel: last 14 days)
right after startup and then once a day at SCHEDULE_HOUR_UTC (default 04:30 UTC); the hospital rota is
also refreshed every HOSPITALS_EVERY_HOURS (default 6) because the ministry posts it during the day.
Heavy imports (OpenStreetMap places, GTFS) are shipped in the data snapshot instead.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)
STATUS: dict[str, dict] = {}  # last outcome per task, shown by /healthz


def _hospitals():
    from simera.collectors import hospitals

    try:
        return hospitals.collect(1)
    except Exception as e:  # noqa: BLE001
        relay = os.environ.get("HOSPITALS_URL")
        if not relay:
            raise
        log.warning("hospitals: ministry fetch failed (%s); importing relay file %s", e, relay)
        return {"fallback_file": hospitals.import_json(relay)}


def _run_all() -> None:
    from simera.collectors import fuel, hospitals, pharmacies

    # the quick, most time-sensitive sources first: the disk is ephemeral on free hosts, so after a
    # restart the rota must be back within a minute
    for name, fn in (("hospitals", _hospitals),
                     ("pharmacies", lambda: pharmacies.collect(7)),
                     ("fuel", lambda: fuel.collect(since=datetime.now(timezone.utc).date() - timedelta(days=14), keep_raw=False))):
        _run_one(name, fn)


def _run_one(name: str, fn) -> None:
    t0 = time.time()
    try:
        result = fn()
        log.info("scheduler: %s done in %.0fs (%s)", name, time.time() - t0, result)
        STATUS[name] = {"ok": True, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "seconds": round(time.time() - t0), "result": str(result)[:200]}
    except Exception as e:  # noqa: BLE001
        log.exception("scheduler: %s failed", name)
        STATUS[name] = {"ok": False, "at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "error": str(e)[:200]}


def _loop() -> None:
    hour = int(os.environ.get("SCHEDULE_HOUR_UTC", "4"))
    minute = int(os.environ.get("SCHEDULE_MINUTE_UTC", "30"))
    every = int(os.environ.get("HOSPITALS_EVERY_HOURS", "6"))
    time.sleep(5)  # let the server come up and pass its health check first
    _run_all()
    last_hosp = time.time()
    while True:
        now = datetime.now(timezone.utc)
        nxt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        wait = (nxt - now).total_seconds()
        hosp_due = max(0.0, last_hosp + every * 3600 - time.time())
        if hosp_due < wait:   # the rota is posted during the day: refresh it a few times, cheaply
            time.sleep(hosp_due)
            _run_one("hospitals", _hospitals)
            last_hosp = time.time()
            continue
        time.sleep(wait)
        _run_all()
        last_hosp = time.time()


def start_if_enabled() -> None:
    if os.environ.get("SCHEDULER") == "1":
        threading.Thread(target=_loop, name="simera-scheduler", daemon=True).start()
        log.info("scheduler enabled")
