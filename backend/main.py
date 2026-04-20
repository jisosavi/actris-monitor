from __future__ import annotations
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from actris_client import ActrisClient
from aggregation import compute_annual_stats, compute_network_stats

# ── Variable definitions ──────────────────────────────────────────────────────
# actris_param values must match the parameter identifiers used by the ACTRIS API.
# TODO: Verify exact parameter strings against the API swagger / documentation.
VARIABLES: dict[str, dict] = {
    "N": {
        "label": "Particle Number Concentration",
        "unit": "cm-3",
        "actris_param": "particle_number_size_distribution",
    },
    "scattering": {
        "label": "Scattering Coefficient 525 nm",
        "unit": "Mm-1",
        "actris_param": "aerosol_light_scattering_coefficient",
        # TODO: add wavelength filter (525 nm) once confirmed in API
    },
    "absorption": {
        "label": "Absorption Coefficient 520 nm",
        "unit": "Mm-1",
        "actris_param": "aerosol_light_absorption_coefficient",
        # TODO: add wavelength filter (520 nm) once confirmed in API
    },
}

VariableKey = Literal["N", "scattering", "absorption"]

# ── App setup ─────────────────────────────────────────────────────────────────
client = ActrisClient()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await client.start()
    yield
    await client.close()


app = FastAPI(title="ACTRIS Monitor API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

# ── Routes ────────────────────────────────────────────────────────────────────

@app.get("/api/stations/{year}/{variable}")
async def get_stations(year: int, variable: VariableKey):
    """Annual mean per station + YoY delta for the requested year and variable."""
    if variable not in VARIABLES:
        raise HTTPException(400, f"Unknown variable '{variable}'")
    if not 2000 <= year <= 2100:
        raise HTTPException(400, "Year out of range")

    cfg = VARIABLES[variable]
    raw, prev_raw = await _fetch_pair(year, cfg["actris_param"])
    return compute_annual_stats(raw, prev_raw, cfg["unit"])


@app.get("/api/network-stats/{year}/{variable}")
async def get_network_stats(year: int, variable: VariableKey):
    """Network-wide statistics (median, IQR, min, max) for the requested year."""
    if variable not in VARIABLES:
        raise HTTPException(400, f"Unknown variable '{variable}'")

    cfg = VARIABLES[variable]
    raw, _ = await _fetch_pair(year, cfg["actris_param"])
    stations = compute_annual_stats(raw, None, cfg["unit"])
    return compute_network_stats(stations, year, variable)


@app.get("/api/variables")
async def list_variables():
    return [{"key": k, **{f: v[f] for f in ("label", "unit")}} for k, v in VARIABLES.items()]


@app.get("/health")
async def health():
    return {"status": "ok"}


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _fetch_pair(year: int, param: str) -> tuple[list[dict], list[dict]]:
    """Fetch current and previous year in parallel."""
    import asyncio
    raw, prev_raw = await asyncio.gather(
        client.fetch_measurements(year, param),
        client.fetch_measurements(year - 1, param),
    )
    return raw, prev_raw


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
