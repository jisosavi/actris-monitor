"""
SQLite persistence layer for ACTRIS Monitor.

All reads and writes go through this module.
WAL mode is used for concurrent reads during a write-heavy fetch job.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

import aiosqlite

logger = logging.getLogger(__name__)

_db: aiosqlite.Connection | None = None
_write_lock = asyncio.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS station_records (
    id            INTEGER PRIMARY KEY,
    year          INTEGER NOT NULL,
    variable      TEXT    NOT NULL,
    station_id    TEXT    NOT NULL,
    name          TEXT    NOT NULL,
    lat           REAL    NOT NULL,
    lon           REAL    NOT NULL,
    country       TEXT    NOT NULL,
    mean          REAL,
    data_coverage REAL    NOT NULL DEFAULT 0.0,
    networks      TEXT    NOT NULL DEFAULT '',
    fetched_at    TEXT    NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sr_lookup
    ON station_records (year, variable, station_id);
CREATE INDEX IF NOT EXISTS idx_sr_yv
    ON station_records (year, variable);
-- idx_sr_lookup leads with `year`, so a lookup by station code alone cannot use
-- it. Every MCP tool that starts from a station needs this one.
CREATE INDEX IF NOT EXISTS idx_sr_station
    ON station_records (station_id);

CREATE TABLE IF NOT EXISTS network_stats (
    id         INTEGER PRIMARY KEY,
    year       INTEGER NOT NULL,
    variable   TEXT    NOT NULL,
    median     REAL,
    q1         REAL,
    q3         REAL,
    min_val    REAL,
    max_val    REAL,
    n_stations INTEGER NOT NULL DEFAULT 0,
    fetched_at TEXT    NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_ns_yv
    ON network_stats (year, variable);

CREATE TABLE IF NOT EXISTS fetch_jobs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at   TEXT    NOT NULL,
    finished_at  TEXT,
    status       TEXT    NOT NULL DEFAULT 'running',
    total        INTEGER NOT NULL DEFAULT 0,
    done         INTEGER NOT NULL DEFAULT 0,
    current_desc TEXT,
    error_msg    TEXT
);

CREATE TABLE IF NOT EXISTS db_coverage (
    year       INTEGER NOT NULL,
    variable   TEXT    NOT NULL,
    fetched_at TEXT    NOT NULL,
    PRIMARY KEY (year, variable)
);
"""


async def _migrate_add_networks() -> None:
    assert _db
    async with _db.execute("PRAGMA table_info(station_records)") as cur:
        rows = await cur.fetchall()
    cols = {r["name"] for r in rows}
    if "networks" not in cols:
        async with _write_lock:
            await _db.execute(
                "ALTER TABLE station_records ADD COLUMN networks TEXT NOT NULL DEFAULT ''"
            )
            await _db.commit()
        logger.info("Migrated station_records: added networks column")


async def init_db(path: str) -> None:
    global _db
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    _db = await aiosqlite.connect(path)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.execute("PRAGMA synchronous=NORMAL")
    for stmt in _SCHEMA.strip().split(";"):
        stmt = stmt.strip()
        if stmt:
            await _db.execute(stmt)
    await _db.commit()
    await _migrate_add_networks()
    await _mark_orphaned_jobs_failed()
    logger.info("Database initialised at %s", path)


async def close_db() -> None:
    global _db
    if _db:
        await _db.close()
        _db = None


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _mark_orphaned_jobs_failed() -> None:
    assert _db
    async with _write_lock:
        await _db.execute(
            "UPDATE fetch_jobs SET status='failed', finished_at=?, error_msg=? "
            "WHERE status='running'",
            (_now(), "Interrupted by server restart"),
        )
        await _db.commit()


# ── Read helpers ──────────────────────────────────────────────────────────────

async def get_station_records_for_id(station_id: str) -> list[dict]:
    assert _db
    async with _db.execute(
        "SELECT station_id, name, lat, lon, country, networks "
        "FROM station_records WHERE station_id = ? LIMIT 1",
        (station_id,),
    ) as cur:
        rows = await cur.fetchall()
    return [{"id": r["station_id"], "name": r["name"], "lat": r["lat"],
             "lon": r["lon"], "country": r["country"], "networks": r["networks"]}
            for r in rows]


async def get_station_records(year: int, variable: str) -> list[dict]:
    assert _db
    async with _db.execute(
        "SELECT station_id, name, lat, lon, country, mean, data_coverage, networks "
        "FROM station_records WHERE year=? AND variable=?",
        (year, variable),
    ) as cur:
        rows = await cur.fetchall()
    return [
        {
            "id":            r["station_id"],
            "name":          r["name"],
            "lat":           r["lat"],
            "lon":           r["lon"],
            "country":       r["country"],
            "mean":          r["mean"],
            "data_coverage": r["data_coverage"],
            "networks":      r["networks"],
        }
        for r in rows
    ]


async def get_network_stats_row(year: int, variable: str) -> dict | None:
    assert _db
    async with _db.execute(
        "SELECT median, q1, q3, min_val, max_val, n_stations "
        "FROM network_stats WHERE year=? AND variable=?",
        (year, variable),
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return None
    return {
        "median":     row["median"],
        "q1":         row["q1"],
        "q3":         row["q3"],
        "min":        row["min_val"],
        "max":        row["max_val"],
        "n_stations": row["n_stations"],
        "year":       year,
        "variable":   variable,
    }


async def get_db_coverage() -> list[dict]:
    assert _db
    async with _db.execute(
        "SELECT year, variable, fetched_at FROM db_coverage ORDER BY variable, year"
    ) as cur:
        rows = await cur.fetchall()
    return [{"year": r["year"], "variable": r["variable"], "fetched_at": r["fetched_at"]} for r in rows]


async def get_station_catalog() -> list[dict]:
    """Every distinct station with its metadata and which years hold data.

    Backs the MCP `actris://catalog/stations` resource. Two queries rather than a
    join because the second one fans out to one row per (station, variable, year)
    and would multiply the metadata.

    **Metadata is picked from the station's most recent year.** It is denormalized
    onto every (year, variable) row and the rows can disagree — `update_station_meta_bulk`
    rewrites lat/lon/networks for all of a station's rows but leaves `name` and
    `country` as whatever each fetch wrote. The `MAX(year)` below is what makes the
    choice deterministic: SQLite guarantees that bare columns selected alongside a
    `MAX()` come from the row that produced the maximum.

    Coverage counts a year only when it holds a usable mean (`> 0`), matching what
    `compute_annual_stats` treats as data — a station-year with a null or zero mean
    is not something a caller can plot.
    """
    assert _db
    async with _db.execute(
        "SELECT station_id, name, lat, lon, country, networks, MAX(year) AS latest_year "
        "FROM station_records GROUP BY station_id ORDER BY station_id"
    ) as cur:
        meta_rows = await cur.fetchall()

    async with _db.execute(
        "SELECT station_id, variable, year FROM station_records "
        "WHERE mean IS NOT NULL AND mean > 0 "
        "ORDER BY station_id, variable, year"
    ) as cur:
        coverage_rows = await cur.fetchall()

    years: dict[str, dict[str, list[int]]] = {}
    for r in coverage_rows:
        years.setdefault(r["station_id"], {}).setdefault(r["variable"], []).append(r["year"])

    return [
        {
            "id":           r["station_id"],
            "name":         r["name"],
            "lat":          r["lat"],
            "lon":          r["lon"],
            "country":      r["country"],
            "networks":     r["networks"],
            "latest_year":  r["latest_year"],
            "years":        years.get(r["station_id"], {}),
        }
        for r in meta_rows
    ]


async def get_series_rows(
    station_ids: list[str], variables: list[str], year_from: int, year_to: int
) -> list[dict]:
    """Stored means for a set of stations and variables across a year range.

    Returns only the rows that exist. Filling the gaps is the caller's job — the
    MCP layer emits every requested period with a null mean, because a period
    missing from a list tells a reader nothing while an explicit null tells them
    it was asked for and not found.
    """
    assert _db
    if not station_ids or not variables:
        return []

    station_slots = ",".join("?" for _ in station_ids)
    variable_slots = ",".join("?" for _ in variables)
    async with _db.execute(
        "SELECT station_id, name, variable, year, mean FROM station_records "
        f"WHERE station_id IN ({station_slots}) AND variable IN ({variable_slots}) "
        "AND year BETWEEN ? AND ? "
        "ORDER BY station_id, variable, year",
        (*station_ids, *variables, year_from, year_to),
    ) as cur:
        rows = await cur.fetchall()

    return [
        {
            "station_id": r["station_id"],
            "name":       r["name"],
            "variable":   r["variable"],
            "year":       r["year"],
            "mean":       r["mean"],
        }
        for r in rows
    ]


async def get_coverage_matrix() -> list[dict]:
    """Coverage rows joined to their station count, for the MCP get_coverage tool.

    `db_coverage` records which (year, variable) pairs have been fetched;
    `network_stats.n_stations` is the count of stations that produced a usable mean
    for that pair. LEFT JOIN because a fetch that stored records but no stats would
    otherwise vanish from the matrix, which is exactly the gap an agent needs to see.
    """
    assert _db
    async with _db.execute(
        "SELECT c.year, c.variable, c.fetched_at, s.n_stations "
        "FROM db_coverage c "
        "LEFT JOIN network_stats s ON s.year = c.year AND s.variable = c.variable "
        "ORDER BY c.variable, c.year"
    ) as cur:
        rows = await cur.fetchall()
    return [
        {
            "year":        r["year"],
            "variable":    r["variable"],
            "fetched_at":  r["fetched_at"],
            "n_stations":  r["n_stations"],
        }
        for r in rows
    ]


async def get_latest_job() -> dict | None:
    assert _db
    async with _db.execute(
        "SELECT * FROM fetch_jobs ORDER BY id DESC LIMIT 1"
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        return None
    return dict(row)


# ── Write helpers ─────────────────────────────────────────────────────────────

async def upsert_station_records(year: int, variable: str, records: list[dict]) -> None:
    assert _db
    now = _now()
    async with _write_lock:
        await _db.executemany(
            "INSERT OR REPLACE INTO station_records "
            "(year, variable, station_id, name, lat, lon, country, mean, data_coverage, networks, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (year, variable, r["id"], r["name"], r["lat"], r["lon"],
                 r["country"], r.get("mean"), r.get("data_coverage", 0.0),
                 r.get("networks", ""), now)
                for r in records
            ],
        )
        await _db.execute(
            "INSERT OR REPLACE INTO db_coverage (year, variable, fetched_at) VALUES (?, ?, ?)",
            (year, variable, now),
        )
        await _db.commit()


async def upsert_network_stats(year: int, variable: str, stats: dict) -> None:
    assert _db
    async with _write_lock:
        await _db.execute(
            "INSERT OR REPLACE INTO network_stats "
            "(year, variable, median, q1, q3, min_val, max_val, n_stations, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (year, variable, stats.get("median"), stats.get("q1"), stats.get("q3"),
             stats.get("min"), stats.get("max"), stats.get("n_stations", 0), _now()),
        )
        await _db.commit()


async def create_job(total: int) -> int:
    assert _db
    async with _write_lock:
        cur = await _db.execute(
            "INSERT INTO fetch_jobs (started_at, status, total, done) VALUES (?, 'running', ?, 0)",
            (_now(), total),
        )
        await _db.commit()
        return cur.lastrowid


async def update_job_progress(job_id: int, done: int, current_desc: str) -> None:
    assert _db
    async with _write_lock:
        await _db.execute(
            "UPDATE fetch_jobs SET done=?, current_desc=? WHERE id=?",
            (done, current_desc, job_id),
        )
        await _db.commit()


async def finish_job(job_id: int, status: str, error_msg: str | None = None) -> None:
    assert _db
    async with _write_lock:
        await _db.execute(
            "UPDATE fetch_jobs SET status=?, finished_at=?, error_msg=? WHERE id=?",
            (status, _now(), error_msg, job_id),
        )
        await _db.commit()


async def clear_db() -> None:
    """Delete all measurement data and job history, leaving schema intact."""
    assert _db
    async with _write_lock:
        for table in ("station_records", "network_stats", "fetch_jobs", "db_coverage"):
            await _db.execute(f"DELETE FROM {table}")
        await _db.commit()
    logger.info("Database cleared")


async def get_all_station_ids() -> list[str]:
    """Return all distinct station_ids in the database."""
    assert _db
    async with _db.execute(
        "SELECT DISTINCT station_id FROM station_records"
    ) as cur:
        rows = await cur.fetchall()
    return [r["station_id"] for r in rows]


async def update_station_meta_bulk(updates: dict[str, dict]) -> int:
    """Update lat, lon and networks for multiple station_ids from .das metadata.
    Returns number of station_ids updated."""
    if not updates:
        return 0
    assert _db
    async with _write_lock:
        for station_id, meta in updates.items():
            await _db.execute(
                "UPDATE station_records SET lat=?, lon=?, networks=? WHERE station_id=?",
                (meta["lat"], meta["lon"], meta.get("networks", ""), station_id),
            )
        await _db.commit()
    return len(updates)
