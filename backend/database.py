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
    fetched_at    TEXT    NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_sr_lookup
    ON station_records (year, variable, station_id);
CREATE INDEX IF NOT EXISTS idx_sr_yv
    ON station_records (year, variable);

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

async def get_station_records(year: int, variable: str) -> list[dict]:
    assert _db
    async with _db.execute(
        "SELECT station_id, name, lat, lon, country, mean, data_coverage "
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
            "(year, variable, station_id, name, lat, lon, country, mean, data_coverage, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (year, variable, r["id"], r["name"], r["lat"], r["lon"],
                 r["country"], r.get("mean"), r.get("data_coverage", 0.0), now)
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
