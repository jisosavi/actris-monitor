"""
Background fetch job management.

At most one fetch job runs at a time. Progress is tracked in the DB
so the frontend can poll /api/fetch-progress.
"""

from __future__ import annotations

import asyncio
import logging
import time

from aggregation import compute_annual_stats, compute_network_stats
import database

logger = logging.getLogger(__name__)

_active_task: asyncio.Task | None = None


def is_job_running() -> bool:
    return _active_task is not None and not _active_task.done()


async def start_fetch_job(
    combos: list[tuple[int, str]],
    client,           # EbasThreddsClient — avoid circular import
    variables: dict,  # VARIABLES dict from main
) -> None:
    global _active_task
    if _active_task and not _active_task.done():
        _active_task.cancel()
        try:
            await _active_task
        except (asyncio.CancelledError, Exception):
            pass
    _active_task = asyncio.create_task(
        _run(combos, client, variables),
        name="fetch-job",
    )


async def _run(
    combos: list[tuple[int, str]],
    client,
    variables: dict,
) -> None:
    job_id = await database.create_job(total=len(combos))
    logger.info("Fetch job %d started: %d combos", job_id, len(combos))
    ok = fail = 0

    for i, (year, var) in enumerate(combos, 1):
        desc = f"Fetching {year} / {var}  ({i}/{len(combos)})"
        await database.update_job_progress(job_id, done=i - 1, current_desc=desc)
        t0 = time.monotonic()
        try:
            raw = await client.fetch_measurements(year, var)
            prev_raw = await _get_prev_raw(year, var, client)
            unit = variables[var]["unit"]
            station_stats = compute_annual_stats(raw, prev_raw, unit)
            net_stats = compute_network_stats(station_stats, year, var)
            await database.upsert_station_records(year, var, raw)
            await database.upsert_network_stats(year, var, net_stats)
            logger.info("Job %d [%d/%d] %d/%s done in %.1fs",
                        job_id, i, len(combos), year, var, time.monotonic() - t0)
            ok += 1
        except asyncio.CancelledError:
            await database.finish_job(job_id, "failed", "Cancelled by user")
            logger.info("Fetch job %d cancelled at %d/%d", job_id, i, len(combos))
            raise
        except Exception as exc:
            logger.warning("Job %d [%d/%d] %d/%s failed: %s",
                           job_id, i, len(combos), year, var, exc)
            fail += 1

        await database.update_job_progress(job_id, done=i, current_desc=desc)

    status = "complete" if fail == 0 else "complete_with_errors"
    await database.finish_job(job_id, status)
    logger.info("Fetch job %d finished: %d ok, %d failed", job_id, ok, fail)


async def _get_prev_raw(year: int, variable: str, client) -> list[dict]:
    """Return prev-year raw records from DB if available, else fetch live."""
    rows = await database.get_station_records(year - 1, variable)
    if rows:
        return rows
    try:
        return await client.fetch_measurements(year - 1, variable)
    except Exception:
        return []
