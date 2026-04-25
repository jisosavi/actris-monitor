from __future__ import annotations
import asyncio
import logging
import time
import os as _os
from contextlib import asynccontextmanager
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from ebas_thredds import EbasThreddsClient
from aggregation import compute_annual_stats, compute_network_stats

logger = logging.getLogger(__name__)

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

WARMUP_YEARS = list(range(2024, 2012, -1))  # 2024..2013 — display years 2014–2024 plus prev-year for delta

client = EbasThreddsClient()

_warmup_progress = {"done": 0, "total": 0, "complete": False}
_warmup_task: asyncio.Task | None = None


async def _warmup_cache() -> None:
    combos = [(y, v) for v in VARIABLES for y in WARMUP_YEARS]
    _warmup_progress["total"] = len(combos)
    _warmup_progress["done"] = 0
    _warmup_progress["complete"] = False

    logger.info("Cache warmup starting: %d combinations", len(combos))
    ok = fail = 0

    for i, (year, var) in enumerate(combos, 1):
        t0 = time.monotonic()
        logger.info("Warmup [%d/%d] year=%d variable=%s ...", i, len(combos), year, var)
        try:
            await client.fetch_measurements(year, var)
            logger.info("Warmup [%d/%d] done in %.1fs", i, len(combos), time.monotonic() - t0)
            ok += 1
        except asyncio.CancelledError:
            logger.info("Warmup cancelled at [%d/%d]", i, len(combos))
            raise
        except Exception as exc:
            logger.warning("Warmup [%d/%d] failed: %s", i, len(combos), exc)
            fail += 1
        _warmup_progress["done"] = i

    _warmup_progress["complete"] = True
    logger.info("Warmup complete: %d ok, %d failed", ok, fail)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _warmup_task
    await client.start()
    _warmup_task = asyncio.create_task(_warmup_cache(), name="cache-warmup")
    yield
    if _warmup_task and not _warmup_task.done():
        _warmup_task.cancel()
        try:
            await _warmup_task
        except (asyncio.CancelledError, Exception):
            pass
    await client.close()


app = FastAPI(title="ACTRIS Monitor API", version="0.1.0", lifespan=lifespan)

_ALLOWED_ORIGINS = _os.environ.get("ALLOWED_ORIGIN", "*")
_ORIGINS_LIST = [o.strip() for o in _ALLOWED_ORIGINS.split(",")] if _ALLOWED_ORIGINS != "*" else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ORIGINS_LIST,
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


@app.get("/api/warmup-status")
async def get_warmup_status():
    return _warmup_progress


@app.get("/api/variables")
async def list_variables():
    return [{"key": k, **{f: v[f] for f in ("label", "unit")}} for k, v in VARIABLES.items()]


@app.get("/health")
async def health():
    return {"status": "ok"}


async def _fetch_pair(year: int, variable: str) -> tuple[list[dict], list[dict]]:
    raw, prev_raw = await asyncio.gather(
        client.fetch_measurements(year, variable),
        client.fetch_measurements(year - 1, variable),
    )
    return raw, prev_raw


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
