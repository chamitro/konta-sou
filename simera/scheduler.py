"""In-process daily scheduler for hosts without cron (e.g. a single free web service).

Enabled with SCHEDULER=1. Runs the light daily collectors (fuel: last 14 days, pharmacies,
hospitals) shortly after startup and then once a day at SCHEDULE_HOUR_UTC (default 04:30 UTC).
Heavy imports (OpenStreetMap places, GTFS) are shipped in the data snapshot instead.
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)


def _hospitals():
    from simera.collectors import hospitals

    try:
        return hospitals.collect(1)
    except Exception as e:  # noqa: BLE001
        relay = os.environ.get("HOSPITALS_URL")
        if not relay:
            raise
        log.warning("hospitals: ministry fetch failed (%s); importing relay file %s", e, relay)
        return hospitals.import_json(relay)


def _run_all() -> None:
    from simera.collectors import fuel, hospitals, pharmacies

    for name, fn in (("fuel", lambda: fuel.collect(since=datetime.now(timezone.utc).date() - timedelta(days=14), keep_raw=False)),
                     ("pharmacies", lambda: pharmacies.collect(7)),
                     ("hospitals", _hospitals)):
        try:
            t0 = time.time()
            result = fn()
            log.info("scheduler: %s done in %.0fs (%s)", name, time.time() - t0, result)
        except Exception:  # noqa: BLE001
            log.exception("scheduler: %s failed", name)


def _loop() -> None:
    hour = int(os.environ.get("SCHEDULE_HOUR_UTC", "4"))
    minute = int(os.environ.get("SCHEDULE_MINUTE_UTC", "30"))
    time.sleep(20)  # let the server come up and pass its health check first
    _run_all()
    while True:
        now = datetime.now(timezone.utc)
        nxt = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if nxt <= now:
            nxt += timedelta(days=1)
        time.sleep((nxt - now).total_seconds())
        _run_all()


def start_if_enabled() -> None:
    if os.environ.get("SCHEDULER") == "1":
        threading.Thread(target=_loop, name="simera-scheduler", daemon=True).start()
        log.info("scheduler enabled")
