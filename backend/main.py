from __future__ import annotations
import asyncio
import os as _os
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ebas_thredds import EbasThreddsClient
from aggregation import compute_annual_stats, compute_network_stats
import database
import fetch_jobs

VARIABLES: dict[str, dict] = {
    "N": {
        "label": "Particle Number Concentration",
        "unit": "cm⁻³",
    },
    "scattering": {
        "label": "Scattering Coefficient 550 nm",
        "unit": "Mm⁻¹",
    },
    "absorption": {
        "label": "Absorption Coefficient 550 nm",
        "unit": "Mm⁻¹",
    },
}

VariableKey = Literal["N", "scattering", "absorption"]

YEAR_MIN = 2000
YEAR_MAX = 2024

client = EbasThreddsClient()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await client.start()
    db_path = _os.environ.get("DATABASE_PATH", "/data/actris.db")
    await database.init_db(db_path)
    yield
    if fetch_jobs.is_job_running():
        fetch_jobs._active_task.cancel()  # type: ignore[attr-defined]
        try:
            await fetch_jobs._active_task  # type: ignore[attr-defined]
        except (asyncio.CancelledError, Exception):
            pass
    await client.close()
    await database.close_db()


app = FastAPI(title="ACTRIS Monitor API", version="0.2.0", lifespan=lifespan)

_ALLOWED_ORIGINS = _os.environ.get("ALLOWED_ORIGIN", "*")
_ORIGINS_LIST = [o.strip() for o in _ALLOWED_ORIGINS.split(",")] if _ALLOWED_ORIGINS != "*" else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ORIGINS_LIST,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ── Existing data endpoints (now DB-backed) ───────────────────────────────────

@app.get("/api/stations/{year}/{variable}")
async def get_stations(year: int, variable: VariableKey):
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


@app.get("/api/network-stats/{year}/{variable}")
async def get_network_stats(year: int, variable: VariableKey):
    if variable not in VARIABLES:
        raise HTTPException(400, f"Unknown variable '{variable}'")

    stats = await database.get_network_stats_row(year, variable)
    if stats is None:
        raise HTTPException(404, f"No stats in database for {year}/{variable}.")
    return stats


# ── Database status & fetch job endpoints ─────────────────────────────────────

@app.get("/api/db-status")
async def get_db_status():
    coverage = await database.get_db_coverage()
    return {"coverage": coverage, "is_empty": len(coverage) == 0}


@app.get("/api/fetch-progress")
async def get_fetch_progress():
    job = await database.get_latest_job()
    if job is None:
        return {"status": "idle"}
    return job


class FetchRequest(BaseModel):
    years: list[int]
    variables: list[str]


@app.post("/api/start-fetch")
async def start_fetch(body: FetchRequest):
    if fetch_jobs.is_job_running():
        raise HTTPException(409, "A fetch job is already running")

    valid_years = [y for y in body.years if YEAR_MIN <= y <= YEAR_MAX + 5]
    valid_vars = [v for v in body.variables if v in VARIABLES]
    if not valid_years or not valid_vars:
        raise HTTPException(400, "No valid year/variable combinations")

    combos = [(y, v) for v in valid_vars for y in sorted(valid_years, reverse=True)]
    await fetch_jobs.start_fetch_job(combos, client, VARIABLES)
    return {"started": True, "total": len(combos)}


@app.post("/api/db/reset")
async def reset_db():
    if fetch_jobs.is_job_running():
        raise HTTPException(409, "Cannot reset while a fetch job is running")
    await database.clear_db()
    return {"ok": True}


_backfill_running = False


@app.post("/api/backfill-networks")
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
        count = await database.update_station_networks_bulk(updates)
        return {"updated": count, "skipped": len(station_ids) - count}
    finally:
        _backfill_running = False


@app.get("/api/debug/station/{station_id}")
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


@app.get("/api/check-new-year")
async def check_new_year():
    years_by_var: dict[str, set[int]] = {}
    for var in VARIABLES:
        years_by_var[var] = await client.get_catalog_years(var)

    new_years = sorted(
        y for y in set().union(*years_by_var.values()) if y > YEAR_MAX
    )
    return {"new_years": new_years, "current_max": YEAR_MAX}


# ── Misc endpoints ─────────────────────────────────────────────────────────────

@app.get("/api/variables")
async def list_variables():
    return [{"key": k, **{f: v[f] for f in ("label", "unit")}} for k, v in VARIABLES.items()]


@app.get("/api/warmup-status")
async def get_warmup_status():
    return {"done": 1, "total": 1, "complete": True}


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
