"""
ACTRIS metadata API v3 — facility records.

The ACTRIS Data Portal moved to v2.0.0 in August 2026 and with it to this API
(`DVAS API`, <https://prod-actris-md.nilu.no>). We use one endpoint: the facility
list, which carries `extra_metadata.insitu.ebas_station_code` and so joins to our
stations on an identifier rather than on a lowercased station name, which is what
the superseded `dc.actris.nilu.no` list forced.

Nothing here is stored. Two of the fields — the labelling status and `active` —
are **current-state facts that change over time**, while `station_records` is keyed
by year, so writing them there would assert that a station was "initially accepted"
*in 2011*. A cached read-through gives the current answer every time and cannot go
stale. See `docs/actris-metadata-api-plan.md`.

Same discipline as `nrt.py`: one upstream request per hour per container, last-good
snapshot on failure, never an error. An ACTRIS outage must cost the labelling status
and nothing else.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

logger = logging.getLogger(__name__)

FACILITIES_URL = "https://prod-actris-md.nilu.no/api/facilities"

# The payload is ~840 KB, so give it room; it is fetched once an hour, not per
# request, and never per station.
_TTL = timedelta(hours=1)
_TIMEOUT = 30.0
_USER_AGENT = "actris-monitor/0.2 (+https://github.com/jisosavi/actris-monitor)"

# `actris_national_facility` replaced the old boolean `is_actris_nf` with a
# six-value labelling status, set on every facility. Anything past this value means
# the site is somewhere in the ACTRIS labelling process; only this value means it is
# not. Applying that rule moves 4 of 145 stations into the ACTRIS tag and moves none
# out, measured 2026-09-15.
NOT_LABELLED = "not labelled"

_cache: tuple[dict[str, Any], datetime] | None = None
_lock = asyncio.Lock()


def _prefer(existing: dict[str, Any], candidate: dict[str, Any]) -> dict[str, Any]:
    """Resolve two facilities claiming the same EBAS station code.

    1,452 facilities carry a code and 1,451 of them are distinct, so this fires
    once — but silently picking whichever arrived first would make the choice
    invisible the next time it happens.
    """
    if bool(candidate.get("active")) and not bool(existing.get("active")):
        return candidate
    if bool(existing.get("active")) == bool(candidate.get("active")):
        return min((existing, candidate), key=lambda f: str(f.get("identifier") or ""))
    return existing


def _parse(payload: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Facility array → {ebas_station_code: {...}}, keeping only what we show."""
    facilities: dict[str, dict[str, Any]] = {}

    for record in payload:
        insitu = (record.get("extra_metadata") or {}).get("insitu") or {}
        code = insitu.get("ebas_station_code")
        if not code:
            continue

        coords = (record.get("location") or {}).get("coordinates") or []
        entry = {
            "identifier": record.get("identifier"),
            "name": record.get("name") or insitu.get("ebas_station_name") or code,
            "country_code": record.get("country_code") or insitu.get("ebas_country_code"),
            "altitude_m": insitu.get("ebas_station_alt") or (coords[2] if len(coords) > 2 else None),
            "labelling_status": record.get("actris_national_facility"),
            # Whether the facility is currently registered as operating. It is NOT
            # a statement about whether data exists: 17 inactive stations still
            # have measurements through 2022 or later, because a site can keep
            # submitting to EBAS after leaving the ACTRIS registry.
            "active": bool(record.get("active")),
            "uri": record.get("uri"),
        }

        if code in facilities:
            chosen = _prefer(facilities[code], entry)
            logger.info(
                "Two ACTRIS facilities share EBAS code %s (%s, %s); keeping %s",
                code, facilities[code]["identifier"], entry["identifier"], chosen["identifier"],
            )
            facilities[code] = chosen
        else:
            facilities[code] = entry

    return facilities


def _snapshot(facilities: dict[str, dict[str, Any]], *, stale: bool, fetched_at: str | None) -> dict[str, Any]:
    return {
        "fetched_at": fetched_at,
        "stale": stale,
        "source": FACILITIES_URL,
        "facilities": facilities,
    }


async def get_facilities() -> dict[str, Any]:
    """Facility metadata keyed by EBAS station code. Never raises."""
    global _cache

    now = datetime.now(timezone.utc)
    if _cache and now - _cache[1] < _TTL:
        return _cache[0]

    async with _lock:
        if _cache and datetime.now(timezone.utc) - _cache[1] < _TTL:
            return _cache[0]

        try:
            async with httpx.AsyncClient(
                timeout=_TIMEOUT, headers={"User-Agent": _USER_AGENT}
            ) as client:
                response = await client.get(FACILITIES_URL)
                response.raise_for_status()
                facilities = _parse(response.json())
        except Exception as exc:  # noqa: BLE001 — an outage must not propagate
            if _cache:
                logger.warning("ACTRIS refresh failed (%s); serving cached snapshot", exc)
                return dict(_cache[0], stale=True)
            logger.warning("ACTRIS metadata unavailable and nothing cached (%s)", exc)
            return _snapshot({}, stale=True, fetched_at=None)

        fetched = datetime.now(timezone.utc)
        snapshot = _snapshot(facilities, stale=False, fetched_at=fetched.isoformat())
        _cache = (snapshot, fetched)
        logger.info("ACTRIS facilities refreshed: %d with an EBAS code", len(facilities))
        return snapshot


async def actris_labelled_codes() -> set[str]:
    """EBAS codes of facilities somewhere in the ACTRIS labelling process.

    Used to add the ACTRIS network tag to stations whose EBAS `project` field did
    not already carry it. Returns an empty set when the API is unreachable, so an
    outage means no augmentation rather than a station losing its tag.
    """
    snapshot = await get_facilities()
    return {
        code
        for code, facility in snapshot["facilities"].items()
        if facility.get("labelling_status") and facility["labelling_status"] != NOT_LABELLED
    }
