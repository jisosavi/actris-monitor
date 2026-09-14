"""
EBAS near-real-time (NRT) availability.

Why this lives in the backend at all: <https://ebas-nrt.nilu.no> serves **no CORS
headers**, so the browser cannot ask it anything directly. This module is the
proxy that answers one question — which stations have live data for our three
variables — so the map can badge them and link out.

What it deliberately does not do: fetch measurements. NRT visualisation stays
NILU's job; we link to it. See `docs/nrt-integration-plan.md` for why, and for
what it would take to change that.

Three properties matter more than the shape of the response:

1. **Cached an hour.** One upstream request per hour per container no matter how
   many visitors — the same politeness rule `ebas_thredds.py` follows. NRT updates
   hourly, so a shorter TTL buys nothing.
2. **Fails soft.** On any upstream error it serves the last good snapshot, or an
   empty one, and says so via `stale`. An NRT outage must never degrade the
   Level 2 dashboard; it just means no badges.
3. **Their list, not the THREDDS catalog.** The `actris_nrt` THREDDS catalog is a
   strict subset of what their site lists, so sourcing from it would let us claim
   availability for a station whose link then lands on an empty page.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

import database

logger = logging.getLogger(__name__)

NRT_API = "https://ebas-nrt.nilu.no/api/stations"
NRT_STATION_URL = "https://ebas-nrt.nilu.no/?station={station_id}"

_TTL = timedelta(hours=1)
_TIMEOUT = 10.0
_USER_AGENT = "actris-monitor/0.2 (+https://github.com/jisosavi/actris-monitor)"

# The instrument token in the EBAS filename convention, mapped to our variable
# keys. Everything else NRT carries — pollen monitors, SMPS, GC, PTR-MS — is
# ignored: the badge should predict what the user finds, and this dashboard only
# shows these three.
INSTRUMENT_TO_VARIABLE: dict[str, str] = {
    "cpc": "N",
    "nephelometer": "scattering",
    "filter_absorption_photometer": "absorption",
}

_cache: tuple[dict[str, Any], datetime] | None = None
_lock = asyncio.Lock()


def _parse(payload: dict[str, Any], known_ids: set[str]) -> dict[str, dict[str, Any]]:
    """GeoJSON feature collection → {station_id: {...}} for our variables only.

    Station metadata is read defensively: this is an undocumented API, so a
    feature missing coordinates or a file list is skipped rather than raising.

    `known` says whether the station exists anywhere in our own record, across
    every year — which is what decides whether the map draws an extra marker for
    it. The frontend cannot work this out for itself: it only ever holds one
    year's stations, so a station of ours with no data for the selected year would
    otherwise be drawn as if it were a site we had never heard of.
    """
    stations: dict[str, dict[str, Any]] = {}

    for feature in payload.get("features", []):
        props = feature.get("properties") or {}
        station_id = props.get("id")
        if not station_id:
            continue

        variables = sorted(
            {
                INSTRUMENT_TO_VARIABLE[parts[3]]
                for name in props.get("files") or []
                if len(parts := name.split(".")) > 3 and parts[3] in INSTRUMENT_TO_VARIABLE
            }
        )
        if not variables:
            continue

        coords = (feature.get("geometry") or {}).get("coordinates") or []
        if len(coords) < 2:
            continue

        stations[station_id] = {
            "name": props.get("name") or station_id,
            "lon": round(float(coords[0]), 4),
            "lat": round(float(coords[1]), 4),
            "variables": variables,
            "known": station_id in known_ids,
            "url": NRT_STATION_URL.format(station_id=station_id),
        }

    return stations


def _snapshot(stations: dict[str, dict[str, Any]], *, stale: bool, fetched_at: str | None) -> dict[str, Any]:
    return {
        "fetched_at": fetched_at,
        "stale": stale,
        "source": NRT_API,
        "stations": stations,
    }


async def get_availability() -> dict[str, Any]:
    """Which stations have NRT data for our variables. Never raises."""
    global _cache

    now = datetime.now(timezone.utc)
    if _cache and now - _cache[1] < _TTL:
        return _cache[0]

    async with _lock:
        # Another request may have refreshed it while we waited for the lock.
        if _cache and datetime.now(timezone.utc) - _cache[1] < _TTL:
            return _cache[0]

        try:
            known_ids = set(await database.get_all_station_ids())
            async with httpx.AsyncClient(
                timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT}
            ) as client:
                response = await client.get(NRT_API)
                response.raise_for_status()
                stations = _parse(response.json(), known_ids)
        except Exception as exc:  # noqa: BLE001 — an outage must not propagate
            if _cache:
                logger.warning("NRT refresh failed (%s); serving cached snapshot", exc)
                stale = dict(_cache[0], stale=True)
                return stale
            logger.warning("NRT unavailable and nothing cached (%s)", exc)
            return _snapshot({}, stale=True, fetched_at=None)

        fetched = datetime.now(timezone.utc)
        snapshot = _snapshot(stations, stale=False, fetched_at=fetched.isoformat())
        _cache = (snapshot, fetched)
        logger.info("NRT availability refreshed: %d stations", len(stations))
        return snapshot
