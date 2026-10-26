"""Thin client for the OASA (Athens public transport) telematics API.

Unofficial but public and widely used; no API key. Endpoints may change without notice.
"""
from __future__ import annotations

import os
import time
from typing import Any

import httpx

API_URL = os.environ.get("OASA_API_URL", "https://telematics.oasa.gr/api/")  # may point at the relay worker
USER_AGENT = "simera/0.1"
_cache: dict[str, tuple[float, Any]] = {}


def _get(act: str, ttl: float = 0, **params) -> Any:
    key = act + "|" + "|".join(f"{k}={v}" for k, v in sorted(params.items()))
    now = time.time()
    if ttl and key in _cache and _cache[key][0] > now:
        return _cache[key][1]
    q = {"act": act, **params}
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=15) as c:
        r = c.get(API_URL, params=q)
        r.raise_for_status()
        data = r.json()
    if ttl:
        _cache[key] = (now + ttl, data)
    return data


def lines() -> list[dict]:
    return _get("webGetLines", ttl=6 * 3600) or []


def routes_for_line(line_code: str) -> list[dict]:
    return _get("webGetRoutes", ttl=6 * 3600, p1=line_code) or []


def stops_for_route(route_code: str) -> list[dict]:
    return _get("webGetStops", ttl=6 * 3600, p1=route_code) or []


def closest_stops(lat: float, lng: float) -> list[dict]:
    return _get("getClosestStops", p1=lat, p2=lng) or []


def routes_for_stop(stop_code: str) -> list[dict]:
    return _get("webRoutesForStop", ttl=3600, p1=stop_code) or []


def arrivals(stop_code: str) -> list[dict]:
    """Live arrivals: [{route_code, veh_code, btime2 (minutes)}]."""
    return _get("getStopArrivals", p1=stop_code) or []


def vehicles_on_route(route_code: str) -> list[dict]:
    return _get("getBusLocation", p1=route_code) or []


def arrivals_with_lines(stop_code: str) -> list[dict]:
    """Arrivals enriched with line number and destination."""
    routes = {r["RouteCode"]: r for r in routes_for_stop(stop_code)}
    out = []
    for a in arrivals(stop_code):
        r = routes.get(a["route_code"], {})
        out.append(
            {
                "line": r.get("LineID"),
                "destination": r.get("RouteDescr"),
                "route_code": a["route_code"],
                "vehicle": a["veh_code"],
                "minutes": int(a["btime2"]),
            }
        )
    return sorted(out, key=lambda x: x["minutes"])
