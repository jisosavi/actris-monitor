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
  main.py         routes, lifespan, /mcp mount (must stay last — see below)
  variables.py    the three variables, defined once: label, unit, instrument, wavelength
  ebas_thredds.py THREDDS catalog + OPeNDAP client  ← the valuable, subtle part
  database.py     all SQLite reads/writes go through here
  aggregation.py  station records → annual stats / network stats
  fetch_jobs.py   single background fetch job, progress tracked in DB
  actris_md.py    ACTRIS metadata API v3 — facility registry, hourly cache, never stored
  nrt.py          EBAS near-real-time availability, hourly cache, never stored
  mcp_server/     MCP endpoint at /mcp
    server.py       the MCPServer instance, registration, transport security
    tools.py        tools (model calls these)
    resources.py    resources (the client attaches these)
    prompts.py      prompts (a person picks these from a menu)
    formatting.py   response envelope, provenance, shared rendering
    limits.py       rate limit + concurrency cap (stands in for auth)
  scripts/dump_mcp_tools.py      regenerates docs/mcp-reference.md
frontend/src/
  composables/useStationData.ts  axios instance + all TanStack Query hooks
  stores/stations.ts             Pinia UI state (year, variable, filters)
  components/                    StationMap, RankingChart, StatsCards, AdminPanel
docs/mcp-server-plan.md          MCP: what exists, what might still be done, why
docs/mcp-reference.md            generated MCP surface reference — do not hand-edit
docs/nrt-integration-plan.md     plan for linking EBAS near-real-time data to the map
docs/actris-metadata-api-plan.md  plan for moving to the ACTRIS metadata API v3
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
- **A station-year's mean can mix different measurands.** `fetch_measurements`
  averages every lev2 file overlapping the year, unweighted — and in 2019 that was
  more than one file for 99 of 164 station-variable pairs, mixing size cuts for 54
  of them. Hyytiälä's 2019 scattering averages six files: pm1, pm10 and four with
  no cut. A year-to-year step can therefore come from a file
  appearing rather than from the atmosphere. Disclosed in every MCP payload via
  `provenance.mean_method`. **Do not "fix" this.** It looks like a bug and is not:
  the question was put to Antti Hyvärinen (FMI) in September 2026, who described a
  stricter stepwise method and then concluded the current model is fine for a
  network overview. The disclosure is the mitigation, permanently. Read
  *The aggregation question* in the plan doc before touching `fetch_measurements`.
- The filename's field `[3]` is the instrument *class* and never varies within a
  variable — `INSTRUMENT_MAP` selects on it. The instrument id is field `[8]` and
  the size cut is `[5]`.
- **Humidified files are excluded** in `_parse_catalog`, matched as a substring of
  field `[5]` because the catalogue spells it three ways (`pm10_humidified`,
  `pm1_humidified`, `aerosol_humidified`). Confirmed with Antti Hyvärinen (FMI);
  scattering only, 24 files. It changed no values — those files were already
  failing silently, see below — so the exclusion makes an accident deliberate.
- **A file whose netCDF lacks the exact `NC_VAR` name is silently skipped.**
  `_compute_annual_mean` ends in a bare `except Exception: return None`, so a file
  storing `aerosol_light_scattering_coefficient` rather than
  `..._amean` contributes nothing and logs nothing. In a 21-file sample, 1 was
  affected. This is how humidified files were already being dropped before anyone
  decided to drop them, and it may be discarding legitimate data elsewhere.
- **A fetch skips combinations already in `db_coverage` unless `force` is set.**
  Without it a refresh is a silent no-op on a populated database, which is what
  "Refresh variable" was until the flag existed. Any change to selection or
  aggregation needs a forced re-fetch to reach stored values.
- ~~`TARGET_WAVELENGTH` vs the 550 nm labels~~ — resolved: the constants (525 nm
  scattering, 520 nm absorption) were right and the labels were wrong. Both now
  come from `variables.py`, which is the single definition of a variable's label,
  unit, instrument, netCDF name and target wavelength.
- Wavelength selection is nearest-neighbour with **no tolerance check**, so a file
  offering only a distant wavelength is silently accepted.

**The mutating endpoints require an admin token.** `POST /api/db/reset`,
`/api/start-fetch` and `/api/backfill-networks` are guarded by `require_admin`,
which checks an `X-Admin-Token` header against the `ADMIN_TOKEN` environment
variable. It **fails closed**: with `ADMIN_TOKEN` unset the endpoints return 503
rather than being open, so a missing variable cannot silently reopen the hole.

The token is never part of the frontend build. The Data Setup panel prompts for
it, validates it against `GET /api/admin/check`, and keeps it in the operator's
own `localStorage`. Visitors read the dashboard with no token; the management
controls stay disabled for them.

The axios interceptor in `useStationData.ts` attaches the header **only** to the
admin paths. Don't widen that — sending a custom header on ordinary GETs makes
them non-simple and costs a CORS preflight round trip on every read.

`ALLOWED_ORIGIN` should be set to the real frontend origin in production. Note
CORS only constrains browsers; it does nothing against `curl`, which is why the
token is the actual protection.

**Current-state facts are cached, never stored.** ACTRIS labelling status, facility
`active`, and NRT availability all change over time, while `station_records` is
keyed by year — writing them there would assert a station was "initially accepted"
*in 2011*. `actris_md.py` and `nrt.py` both serve them from an hourly cache that
fails soft. The ACTRIS network tag joins on the **EBAS station code** from the
facility record, not on station name as the superseded `dc.actris.nilu.no` list
forced; it only takes effect when `backfill_networks` runs.

**Be polite to NILU.** Their THREDDS server is a shared research resource. Results
are cached 24 h and concurrency is capped at `_MAX_CONCURRENT = 20`. Don't raise
that or add retry loops without a good reason.

## The MCP endpoint (`/mcp`)

Same process, same FastAPI app, same SQLite connection as `/api/*`; agents speak
Streamable HTTP. `backend/mcp_server/` holds it and `docs/mcp-server-plan.md` has
the design and the roadmap. Live today: **all six tools** (`get_coverage`,
`find_station`, `get_series`, `get_ranking`, `get_network_stats`, `get_change`),
**two resources** (`actris://catalog/stations`, `actris://citation`) and **one
prompt** (`data_availability_briefing`).

**Tests:** `cd backend && pytest` (install `requirements-dev.txt` first). They drive
the tools through the SDK's in-process client — no HTTP, no port — and target the
conventions that fail *silently*: gaps as explicit nulls, truncation by whole
station, a search that never returns nothing, and stations that vanish from a
change ranking. Add a case beside each new tool rather than after five of them.

**`docs/mcp-reference.md` is generated — never edit it by hand.** After adding or
changing a tool, run `cd backend && python scripts/dump_mcp_tools.py`.
`--check` exits 1 if the committed doc is stale, for CI. A tool's docstring *is*
the description the model reads, so a hand-written second copy could disagree with
the agent's own instructions and nothing would notice.

Five things that break it, all of them silently:

**The mount must stay at the bottom of `main.py`.** It is mounted at `/` so the
endpoint path is exactly `/mcp`, and Starlette tries routes in order — a root mount
matches everything, so any route declared after it is unreachable. (Mounting at
`/mcp` instead would serve `/mcp/` and answer `/mcp` with a 307 that MCP clients
don't follow.)

**The host app owns the session manager.** A mounted sub-app's lifespan never runs,
so `main.py`'s lifespan enters `mcp.session_manager.run()`. Without it the first
request dies with `RuntimeError: Task group is not initialized`. The manager only
exists after `streamable_http_app()` has been called, which is why `mcp_app` is
built at import time.

**`MCP_ALLOWED_HOSTS` is required in deployment.** The SDK arms DNS-rebinding
protection with a localhost-only allowlist by default, so behind a real hostname
every request gets `421 Misdirected Request` and the reason appears only in the
server log. A bare hostname automatically also allows `<host>:*`.

**Never call `database.init_db()` from the MCP layer.** It repoints the
module-global connection without closing the old one *and* flips every
`status='running'` fetch job to `'failed'`. The tools rely on the lifespan having
done it once.

**A new tool, resource or prompt is invisible to already-connected clients.** The
server advertises `listChanged: true` on all three surfaces, but that promises a
*push*, and the stateless 2026-07-28 transport has no server-to-client channel to
push down — there is no session to notify. A client discovers the surface once, via
`server/discover`, when its connection is established: adding the connector, app
launch, toggling it off and on, or reconnecting after a network drop. Opening a new
conversation re-probes nothing. So after deploying a new tool, **reconnect the
connector** — otherwise you will be looking for something the client has no way to
know exists.

Two design rules worth keeping: `mcp_server/tools.py` imports `database` and
`variables` only — never FastAPI, never `main` — which is what would make a
standalone stdio package cheap later. And the surface is **read-only**: no
`start_fetch`, no `reset`, no `backfill-networks`, because agents retry on
ambiguity and a retried reset is unrecoverable.

The endpoint is **unauthenticated by design** — it serves public EBAS data from our
own database, so a token would protect the container, not the data. The protection
is instead `MCP_RATE_LIMIT_PER_MINUTE` (per address) and `MCP_MAX_CONCURRENT`, both
in-process counters: replicating the service multiplies the effective limit.
Nothing in the MCP path may reach NILU — a tool call serves from SQLite or reports
the data as absent.

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
