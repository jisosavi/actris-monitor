from __future__ import annotations
import asyncio
import os as _os
import secrets
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ebas_thredds import EbasThreddsClient
from aggregation import compute_annual_stats, compute_network_stats
from variables import VARIABLES as VARIABLE_DEFS
from mcp_server.server import build_asgi_app as build_mcp_app, mcp
import actris_md
import database
import fetch_jobs
import nrt

# Label and unit come from variables.py; this keeps the {key: {"label", "unit"}}
# shape that the routes and fetch_jobs already read.
VARIABLES: dict[str, dict] = {
    k: {"label": v.label, "unit": v.unit} for k, v in VARIABLE_DEFS.items()
}

VariableKey = Literal["N", "scattering", "absorption"]

YEAR_MIN = 2000
YEAR_MAX = datetime.now().year

client = EbasThreddsClient()

# Built at import time because `mcp.session_manager` does not exist until the ASGI
# app has been constructed, and the lifespan below needs the manager.
mcp_app = build_mcp_app()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await client.start()
    db_path = _os.environ.get("DATABASE_PATH", "/data/actris.db")
    await database.init_db(db_path)
    # A mounted sub-application's own lifespan never runs, so the MCP session
    # manager has to be started here. Without this the first request to /mcp fails
    # with "RuntimeError: Task group is not initialized". The MCP tools also rely on
    # the init_db above: they must never call it themselves, because a second
    # init_db repoints the module-global connection and marks any running fetch job
    # as failed.
    async with mcp.session_manager.run():
        yield
    if fetch_jobs.is_job_running():
        fetch_jobs._active_task.cancel()  # type: ignore[attr-defined]
        try:
            await fetch_jobs._active_task  # type: ignore[attr-defined]
        except (asyncio.CancelledError, Exception):
            pass
    await client.close()
    await database.close_db()


# Every route carries exactly one of these tags, and `scripts/dump_openapi.py`
# publishes only the "Public" ones. Tagging rather than `include_in_schema=False`
# is deliberate: the flag would also hide the admin routes from this app's own
# /docs, and the operator running a fetch is precisely who needs them there.
TAGS_METADATA = [
    {
        "name": "Public",
        "description": (
            "Read-only endpoints serving the dashboard. No authentication, no "
            "upstream calls — every response comes from this service's own SQLite "
            "database or from an in-process cache."
        ),
    },
    {
        "name": "Admin",
        "description": (
            "Mutating operations, guarded by an `X-Admin-Token` header checked "
            "against the `ADMIN_TOKEN` environment variable. Fails closed: with "
            "the variable unset these return 503 rather than being open. Not "
            "published."
        ),
    },
    {
        "name": "Internal",
        "description": (
            "Operational endpoints for the dashboard's own plumbing, or debugging "
            "aids that reach out to NILU. Undocumented on purpose — they are not "
            "an interface anyone should build against. Not published."
        ),
    },
]

app = FastAPI(
    title="ACTRIS Monitor API",
    version="0.2.0",
    lifespan=lifespan,
    openapi_tags=TAGS_METADATA,
)

_ALLOWED_ORIGINS = _os.environ.get("ALLOWED_ORIGIN", "*")
_ORIGINS_LIST = [o.strip() for o in _ALLOWED_ORIGINS.split(",")] if _ALLOWED_ORIGINS != "*" else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ORIGINS_LIST,
    # DELETE and Mcp-Session-Id are for browser-based MCP clients on /mcp: Streamable
    # HTTP ends a session with DELETE, and a browser cannot read the session id back
    # unless CORS exposes that header by name.
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
    expose_headers=["Mcp-Session-Id"],
)


# ── Admin authentication ──────────────────────────────────────────────────────

ADMIN_TOKEN = _os.environ.get("ADMIN_TOKEN", "")


def require_admin(x_admin_token: str | None = Header(default=None)) -> None:
    """Guard the mutating endpoints with a shared secret.

    Fails closed: with no ADMIN_TOKEN configured the endpoints are unavailable
    rather than open, so a missing environment variable cannot silently leave
    the database writable from the public internet.

    The token is never shipped in the frontend bundle — the Data Setup panel
    prompts for it and keeps it in the operator's own browser storage.
    """
    if not ADMIN_TOKEN:
        raise HTTPException(
            503, "Admin endpoints are disabled: ADMIN_TOKEN is not configured."
        )
    if not x_admin_token or not secrets.compare_digest(x_admin_token, ADMIN_TOKEN):
        raise HTTPException(401, "Invalid or missing admin token.")


@app.get("/api/admin/check", tags=["Admin"])
async def admin_check(_: None = Depends(require_admin)):
    """Validate an admin token without side effects, so the UI can unlock itself."""
    return {"ok": True}


# ── Existing data endpoints (now DB-backed) ───────────────────────────────────

@app.get(
    "/api/stations/{year}/{variable}",
    tags=["Public"],
    summary="Annual means for every station in one year",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": [
                        {
                            "id": "FI0050R",
                            "name": "Hyytiala",
                            "lat": 61.847,
                            "lon": 24.295,
                            "country": "FI",
                            "mean": 1743.281,
                            "unit": "cm-3",
                            "delta_pct": -4.12,
                            "prev_mean": 1818.19,
                            "data_coverage": 1.0,
                            "networks": "ACTRIS,EMEP,GAW-WDCA",
                        }
                    ]
                }
            }
        },
        404: {"description": "No data stored for that year and variable."},
    },
)
async def get_stations(year: int, variable: VariableKey):
    """One annual mean per station, sorted highest to lowest.

    `delta_pct` and `prev_mean` compare against the previous calendar year, and are
    `null` where that year has no value for the station — which is common, since
    coverage is uneven.

    Two caveats that the numbers themselves do not carry:

    - **The mean is unweighted across a station's files for the year.** Where a
      station published more than one Level 2 file, they are averaged flat, and
      those files may use different size cuts. A step between years can therefore
      come from a file appearing rather than from the atmosphere.
    - **`data_coverage` is a has-data flag, not a fraction.** It is `1.0` where any
      value was found and `0.0` otherwise, despite the name.
    """
    if variable not in VARIABLES:
        raise HTTPException(400, f"Unknown variable '{variable}'")
    if not 2000 <= year <= 2100:
        raise HTTPException(400, "Year out of range")

    raw = await database.get_station_records(year, variable)
    if not raw:
        raise HTTPException(404, f"No data in database for {year}/{variable}. Use the Data panel to fetch it.")

    prev_raw = await database.get_station_records(year - 1, variable)
    unit = VARIABLES[variable]["unit"]
    return compute_annual_stats(raw, prev_raw, unit)


@app.get(
    "/api/network-stats/{year}/{variable}",
    tags=["Public"],
    summary="Distribution across all stations in one year",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "median": 1284.5,
                        "q1": 743.02,
                        "q3": 2260.15,
                        "min": 92.4,
                        "max": 8871.3,
                        "n_stations": 47,
                    }
                }
            }
        },
        404: {"description": "No statistics stored for that year and variable."},
    },
)
async def get_network_stats(year: int, variable: VariableKey):
    """Median, quartiles, range and station count across the network.

    Computed over the stations that have a value, so `n_stations` is a count of
    contributors rather than of the network — it moves year to year as coverage
    changes, which matters when comparing one year's spread against another's.
    """
    if variable not in VARIABLES:
        raise HTTPException(400, f"Unknown variable '{variable}'")

    stats = await database.get_network_stats_row(year, variable)
    if stats is None:
        raise HTTPException(404, f"No stats in database for {year}/{variable}.")
    return stats


# ── Database status & fetch job endpoints ─────────────────────────────────────

@app.get(
    "/api/db-status",
    tags=["Public"],
    summary="Which year and variable combinations hold data",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "coverage": [
                            {"year": 2023, "variable": "N", "fetched_at": "2026-09-14T09:12:44Z"},
                            {"year": 2024, "variable": "N", "fetched_at": "2026-09-14T09:13:02Z"},
                        ],
                        "is_empty": False,
                    }
                }
            }
        }
    },
)
async def get_db_status():
    """The availability matrix: what has been fetched, and when.

    Worth reading before anything else. A year and variable missing from
    `coverage` has no data at all rather than data worth retrying for, and the
    most recent year or two is normally absent — Level 2 publication lags.
    """
    coverage = await database.get_db_coverage()
    return {"coverage": coverage, "is_empty": len(coverage) == 0}


@app.get("/api/fetch-progress", tags=["Internal"])
async def get_fetch_progress():
    job = await database.get_latest_job()
    if job is None:
        return {"status": "idle"}
    return job


class FetchRequest(BaseModel):
    years: list[int]
    variables: list[str]
    # Re-fetch combinations already in the database. Needed whenever the selection
    # or aggregation changes — without it a refresh silently does nothing, because
    # every requested combination is already covered.
    force: bool = False


@app.post("/api/start-fetch", dependencies=[Depends(require_admin)], tags=["Admin"])
async def start_fetch(body: FetchRequest):
    if fetch_jobs.is_job_running():
        raise HTTPException(409, "A fetch job is already running")

    valid_years = [y for y in body.years if YEAR_MIN <= y <= YEAR_MAX + 5]
    valid_vars = [v for v in body.variables if v in VARIABLES]
    if not valid_years or not valid_vars:
        raise HTTPException(400, "No valid year/variable combinations")

    combos = [(y, v) for v in valid_vars for y in sorted(valid_years, reverse=True)]
    await fetch_jobs.start_fetch_job(combos, client, VARIABLES, force=body.force)
    return {"started": True, "total": len(combos), "force": body.force}


@app.post("/api/db/reset", dependencies=[Depends(require_admin)], tags=["Admin"])
async def reset_db():
    if fetch_jobs.is_job_running():
        raise HTTPException(409, "Cannot reset while a fetch job is running")
    await database.clear_db()
    return {"ok": True}


_backfill_running = False


@app.post("/api/backfill-networks", dependencies=[Depends(require_admin)], tags=["Admin"])
async def backfill_networks():
    global _backfill_running
    if _backfill_running:
        raise HTTPException(409, "Backfill already running")
    if fetch_jobs.is_job_running():
        raise HTTPException(409, "Cannot backfill while a fetch job is running")

    station_ids = await database.get_all_station_ids()
    if not station_ids:
        return {"updated": 0, "skipped": 0}

    _backfill_running = True
    try:
        updates = await client.backfill_networks(station_ids)
        count = await database.update_station_meta_bulk(updates)
        return {"updated": count, "skipped": len(station_ids) - count}
    finally:
        _backfill_running = False


@app.get("/api/debug/station/{station_id}", tags=["Internal"])
async def debug_station(station_id: str):
    """Return stored DB coordinates + raw .das geographic attributes for a station."""
    rows = await database.get_station_records_for_id(station_id)
    if not rows:
        raise HTTPException(404, f"Station '{station_id}' not in database")

    catalog = await client._get_catalog()
    fi = next((f for f in catalog if f.station == station_id), None)

    das_info: dict = {}
    if fi and client._http:
        from ebas_thredds import OPENDAP_BASE
        url = f"{OPENDAP_BASE}/{fi.name}.das"
        try:
            resp = await client._http.get(url, timeout=30.0)
            # Extract just the geographic lines from the DAS
            geo_lines = [
                l.strip() for l in resp.text.splitlines()
                if any(k in l.lower() for k in ("lat", "lon", "title", "project"))
            ]
            das_info = {"url": url, "geo_lines": geo_lines}
        except Exception as e:
            das_info = {"url": url, "error": str(e)}

    return {
        "stored": {"name": rows[0]["name"], "lat": rows[0]["lat"], "lon": rows[0]["lon"],
                   "country": rows[0]["country"], "networks": rows[0]["networks"]},
        "catalog_file": fi.name if fi else None,
        "das": das_info,
    }


@app.get("/api/check-new-year", tags=["Internal"])
async def check_new_year():
    years_by_var: dict[str, set[int]] = {}
    for var in VARIABLES:
        years_by_var[var] = await client.get_catalog_years(var)

    new_years = sorted(
        y for y in set().union(*years_by_var.values()) if y > YEAR_MAX
    )
    return {"new_years": new_years, "current_max": YEAR_MAX}


# ── Misc endpoints ─────────────────────────────────────────────────────────────

@app.get(
    "/api/variables",
    tags=["Public"],
    summary="The three measured variables",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": [
                        {"key": "N", "label": "Particle number concentration", "unit": "cm-3"},
                        {"key": "scattering", "label": "Light scattering coefficient", "unit": "Mm-1"},
                        {"key": "absorption", "label": "Light absorption coefficient", "unit": "Mm-1"},
                    ]
                }
            }
        }
    },
)
async def list_variables():
    """Key, label and unit for each variable this service covers.

    The `key` is what every other endpoint takes in its path. There are three and
    there is no mechanism for adding a fourth at runtime — they are defined in
    `variables.py`, which is also where the instrument and target wavelength for
    each one lives.
    """
    return [{"key": k, **{f: v[f] for f in ("label", "unit")}} for k, v in VARIABLES.items()]


@app.get(
    "/api/actris/facilities",
    tags=["Public"],
    summary="ACTRIS facility metadata, by EBAS station code",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "fetched_at": "2026-09-16T08:00:11Z",
                        "stale": False,
                        "facilities": {
                            "FI0050R": {
                                "identifier": "FI0050R",
                                "name": "Hyytiala",
                                "country_code": "FI",
                                "altitude_m": 181.0,
                                "labelling_status": "labelled",
                                "active": True,
                                "uri": "https://data.actris.eu/facility/...",
                            }
                        },
                    }
                }
            }
        }
    },
)
async def get_actris_facilities():
    """ACTRIS facility metadata, keyed by EBAS station code.

    Altitude, labelling status, `active` and the portal URI. Served live from an
    hourly cache rather than stored: the status and `active` are current-state
    facts that change as stations move through certification, while
    `station_records` is keyed by year. Fails soft — an ACTRIS outage returns an
    empty map with `stale: true`, and costs the metadata, nothing else.
    """
    return await actris_md.get_facilities()


@app.get(
    "/api/nrt/stations",
    tags=["Public"],
    summary="Stations with EBAS near-real-time data",
    responses={
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "fetched_at": "2026-09-16T08:00:11Z",
                        "stale": False,
                        "stations": [
                            {"id": "FI0050R", "name": "Hyytiala", "variables": ["N", "scattering"]}
                        ],
                    }
                }
            }
        }
    },
)
async def get_nrt_stations():
    """Which stations have EBAS near-real-time data for our three variables.

    A proxy, because ebas-nrt.nilu.no sends no CORS headers and the browser
    therefore cannot ask it directly. Cached an hour upstream of this handler and
    fails soft: an NRT outage returns an empty list with `stale: true` rather than
    an error, so the dashboard renders normally with no badges.
    """
    return await nrt.get_availability()


@app.get("/api/warmup-status", tags=["Internal"])
async def get_warmup_status():
    return {"done": 1, "total": 1, "complete": True}


@app.get("/health", tags=["Internal"])
async def health():
    return {"status": "ok"}


# ── MCP endpoint ──────────────────────────────────────────────────────────────
#
# Must stay BELOW every route above it: Starlette tries routes in order and a
# root mount matches every path, so anything declared after this line is
# unreachable. Mounting at "/" with the SDK's default streamable_http_path serves
# the endpoint at exactly /mcp — mounting at "/mcp" would instead serve /mcp/ and
# answer /mcp with a 307 that MCP clients do not follow.
app.mount("/", app=mcp_app)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
