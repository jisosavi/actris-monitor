# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

An interactive dashboard for long-term aerosol measurements from the ACTRIS/EBAS
European atmospheric research network. Data is pulled on demand from the EBAS
THREDDS OPeNDAP server at NILU and cached in SQLite. Three variables, Level 2
(fully QC'd) only, 2000 onwards.

- Frontend: Vue 3 + TypeScript, deployed as a static build to isosavi.com/test/actris-monitor
- Backend: FastAPI + SQLite, deployed on Railway

## Layout

```
backend/          FastAPI app
  main.py         routes, VARIABLES dict, lifespan
  ebas_thredds.py THREDDS catalog + OPeNDAP client  ← the valuable, subtle part
  database.py     all SQLite reads/writes go through here
  aggregation.py  station records → annual stats / network stats
  fetch_jobs.py   single background fetch job, progress tracked in DB
frontend/src/
  composables/useStationData.ts  axios instance + all TanStack Query hooks
  stores/stations.ts             Pinia UI state (year, variable, filters)
  components/                    StationMap, RankingChart, StatsCards, AdminPanel
docs/mcp-server-plan.md          design plan for an MCP server (not implemented)
```

## Things that are easy to get wrong

**Data is annual only.** `station_records` holds **one row per (year, variable,
station)** with a single `mean`. `_fetch_file_mean` in `ebas_thredds.py` downloads
a year slice and collapses it to one float immediately — no sub-annual data is
persisted. Any request for monthly/daily figures needs a schema change, not a
query change. See `docs/mcp-server-plan.md`.

**Only `lev2` files are used.** The THREDDS catalog has ~14,000 netCDF files;
`ebas_thredds.py` filters to Level 2 and to the instruments mapped in
`INSTRUMENT_MAP` (`N`→cpc, `scattering`→nephelometer,
`absorption`→filter_absorption_photometer).

**Year slices are estimated from filenames, not from the time array.** The client
decodes start/end dates from the dot-separated filename convention and computes
index ranges, then fetches only that slice over the OPeNDAP ASCII endpoint
(~130 KB instead of a whole file). Don't "simplify" this into a full download —
it is the reason the app is usable.

**Known data-quality caveats** (documented, not yet fixed — see the plan doc):
- `data_coverage` is set to `1.0 if values else 0.0`. It is a has-data flag, not
  a coverage fraction, despite the name.
- Stations with several files in a year use `np.mean(values)`: an unweighted mean
  of per-file means.
- `TARGET_WAVELENGTH` is 525 nm (scattering) and 520 nm (absorption) while the
  labels in `main.py` and the README say 550 nm. Unresolved.

**The mutating endpoints are unauthenticated.** `POST /api/db/reset`,
`/api/start-fetch` and `/api/backfill-networks` have no auth, and CORS defaults to
`*`. This is a known issue to fix, not a pattern to copy.

**Be polite to NILU.** Their THREDDS server is a shared research resource. Results
are cached 24 h and concurrency is capped at `_MAX_CONCURRENT = 20`. Don't raise
that or add retry loops without a good reason.

## Running locally

Docker (both services, DB persists in the `actris-db` volume):

```bash
docker compose up
```

Native backend — **`DATABASE_PATH` must be set**, because the code default is
`/data/actris.db` and `/data` is not writable on macOS:

```bash
cd backend && DATABASE_PATH=./data/actris.db uvicorn main:app --reload
```

`.vscode/launch.json` has a debug configuration that sets this. Frontend:

```bash
cd frontend && npm run dev
```

The Vite dev server proxies `/api` to `localhost:8000`.

## Environment variables

See `backend/.env.example` and `frontend/.env.example`. Nothing auto-loads `.env`
— these are set in the run configuration, docker-compose, or the build
environment. `VITE_API_BASE_URL` and `VITE_BASE_PATH` must be set for the
production build, or the deployed frontend will call `/api` on the static host.

## Python version

The container is `python:3.12-slim` and Railway builds from it, so **3.12 is
production**. Keep the local virtualenv on 3.12 too; the MCP SDK resolves
different `starlette`/`anyio` versions on 3.14 than on 3.12, which is exactly the
kind of divergence that only shows up after deploy.

## Conventions

- Backend: `from __future__ import annotations`, PEP 604 unions (`X | None`),
  async throughout, module-level docstrings explaining *why*.
- All DB access goes through `database.py` — no ad-hoc SQL elsewhere.
- Frontend: `<script setup>` + TypeScript, shadcn-vue components in
  `components/ui/` are generated (don't hand-edit), Tailwind for styling.
- Server state lives in TanStack Query; UI state lives in the Pinia store.

Frontend checks before committing:

```bash
cd frontend && npm run type-check && npm run lint
```
