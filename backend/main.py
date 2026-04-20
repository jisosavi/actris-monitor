from __future__ import annotations
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from ebas_thredds import EbasThreddsClient
from aggregation import compute_annual_stats, compute_network_stats

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

client = EbasThreddsClient()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await client.start()
    yield
    await client.close()


app = FastAPI(title="ACTRIS Monitor API", version="0.1.0", lifespan=lifespan)

_ALLOWED_ORIGINS = [
    "http://localhost:5173",
    "http://localhost:4173",
]
import os as _os
if _prod_origin := _os.environ.get("ALLOWED_ORIGIN"):
    _ALLOWED_ORIGINS.append(_prod_origin)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["GET"],
    allow_headers=["*"],
)


@app.get("/api/stations/{year}/{variable}")
async def get_stations(year: int, variable: VariableKey):
    if variable not in VARIABLES:
        raise HTTPException(400, f"Unknown variable '{variable}'")
    if not 2000 <= year <= 2100:
        raise HTTPException(400, "Year out of range")

    unit = VARIABLES[variable]["unit"]
    raw, prev_raw = await _fetch_pair(year, variable)
    return compute_annual_stats(raw, prev_raw, unit)


@app.get("/api/network-stats/{year}/{variable}")
async def get_network_stats(year: int, variable: VariableKey):
    if variable not in VARIABLES:
        raise HTTPException(400, f"Unknown variable '{variable}'")

    unit = VARIABLES[variable]["unit"]
    raw, _ = await _fetch_pair(year, variable)
    stations = compute_annual_stats(raw, None, unit)
    return compute_network_stats(stations, year, variable)


@app.get("/api/variables")
async def list_variables():
    return [{"key": k, **{f: v[f] for f in ("label", "unit")}} for k, v in VARIABLES.items()]


@app.get("/health")
async def health():
    return {"status": "ok"}


async def _fetch_pair(year: int, variable: str) -> tuple[list[dict], list[dict]]:
    import asyncio
    raw, prev_raw = await asyncio.gather(
        client.fetch_measurements(year, variable),
        client.fetch_measurements(year - 1, variable),
    )
    return raw, prev_raw


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
