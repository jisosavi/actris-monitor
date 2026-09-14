# ACTRIS Monitor: Aerosol In-Situ Network Dashboard

## What is ACTRIS Monitor?

ACTRIS Monitor is an interactive visualization dashboard for long-term aerosol measurement data from the ACTRIS/EBAS European atmospheric research network. It displays annual station averages, year-on-year concentration changes, and network-wide statistics for three key atmospheric variables across measurement stations spanning Europe and beyond.

Data is fetched on demand from the EBAS THREDDS OPeNDAP server at NILU (Norwegian Institute for Air Research) and stored locally in a SQLite database. The app supports fully quality-controlled Level 2 observations from 2000 onwards.

For inspiration, thanks to research professor Antti Hyvärinen / Finnish Meteorological Institute!

## Measured Variables

**Particle Number Concentration (N)** — Total aerosol particle count per cm³, measured by Condensation Particle Counters (CPC). Primary indicator of new particle formation events and anthropogenic pollution.

**Scattering Coefficient (σ_sp, 525 nm)** — Aerosol light scattering at 525 nm measured by nephelometers. Relates to aerosol optical depth and visibility reduction.

**Absorption Coefficient (σ_ap, 520 nm)** — Aerosol light absorption at 520 nm measured by filter absorption photometers. Indicator of black carbon and light-absorbing aerosol loading.

Wavelengths are the values the fetch targets (`backend/variables.py`); selection from each source file is nearest-neighbour, so an individual file may carry a nearby wavelength instead.

## Screenshots

![Map view showing station concentrations with network filter and hover tooltip](docs/Actris%20Monitor%20-%20Application%20UI.jpg)
*Main map view — station concentrations for 2011 N variable, all three network filters active, Pallas (Sammaltunturi) tooltip open*

![Data Setup panel for fetching and managing measurement data](docs/Actris%20Monitor%20-%20Data%20Setup%20View.jpg)
*Data Setup panel — year range selection, per-variable refresh, network metadata backfill*

## Interface

The dashboard renders a full-screen map (MapLibre GL + deck.gl ScatterplotLayer) where each station appears as a circle coloured either by absolute concentration value (low–high gradient) or by annual change (green = decrease, red = increase). Stations with unknown network affiliation are shown as grey when a network filter is active.

A control panel provides:
- Year selection and variable switching
- Network filter (ACTRIS / EMEP / GAW-WDCA) — stations are tagged by cross-referencing EBAS `.das` project fields and the ACTRIS Data Centre facility list
- Map colour mode toggle (absolute vs. year-on-year change)

A station ranking chart lists all stations from highest to lowest concentration. Network statistics cards show median, IQR, minimum, and maximum — each with a year-on-year percentage and absolute change indicator.

Hovering a station shows a tooltip with the station name, country, annual mean, year-on-year change, and data coverage.

## Data Setup

On first launch the database is empty. Open **Data Setup** (bottom of the left panel) to fetch data:

1. **Fetch data** — select a year range and variables; already-fetched combinations are skipped automatically
2. **Refresh variable** — re-fetch all years for a specific variable
3. **Check for new year** — query the THREDDS catalog to detect data for years beyond the current maximum
4. **Backfill network metadata** — re-fetch one `.das` file per instrument type per station to populate ACTRIS / EMEP / GAW-WDCA affiliations. Run this after a data fetch if the network filter shows stations as unknown
5. **Reset database** — delete all stored data

The app remains fully usable for any data already in the database while a fetch job runs in the background.

## Data Architecture

### Backend

The backend fetches the EBAS THREDDS catalog (~14,000 netCDF files) and filters to Level 2 files matching the selected instrument type. For each relevant file it estimates the year-slice index range from filename dates and retrieves only that slice via OPeNDAP ASCII constraint expressions — avoiding full file downloads.

Station coordinates, names, and network affiliations are read from each file's OPeNDAP `.das` attribute structure. The coordinate parser handles multiple formats found in the wild: signed decimal, unsigned decimal with inline hemisphere suffix, separate hemisphere attribute, and DMS notation.

Network affiliation is determined from two sources:
- The `String project` field in each `.das` file (reflects the submission framework)
- The [ACTRIS Data Centre](https://dc.actris.nilu.no) facility API, which is queried to supplement stations that are ACTRIS National Facilities but whose EBAS files only list other frameworks

For backfill, one file per unique instrument type per station is processed (up to 5) so that all submission frameworks are captured by set union.

All fetched data is persisted in a **SQLite database** (WAL mode, aiosqlite). Fetch jobs run as background asyncio tasks with per-combination progress tracking stored in the database.

The pydap library is not used. All OPeNDAP access goes through httpx against the ASCII endpoint, as pydap/webob returns HTTP 503 from the NILU THREDDS server.

### Frontend

The frontend uses TanStack Vue Query (1 h stale time) for data fetching and Pinia for UI state. On variable or year change the query cache is checked before making a backend request.

## For AI agents (MCP)

The same backend exposes its data over the [Model Context Protocol](https://modelcontextprotocol.io) at `/mcp` (Streamable HTTP), so an agent can query the network directly instead of scraping the dashboard:

```
https://actris-monitor-production.up.railway.app/mcp
```

`.mcp.json` in this repository points at it, so Claude Code offers the connector when you open the project (it asks before enabling it). For other clients, add the URL as an HTTP/Streamable-HTTP MCP server.

**Open, and rate-limited rather than authenticated.** The tools are read-only over public EBAS data served from this project's own database, so there is no credential to hand out — but there is a shared container behind the URL. Requests are limited per address (60/minute) with a cap on concurrency; over either, you get `429`/`503` with `Retry-After`. Batch related questions instead of polling. Authentication may be introduced later if the endpoint attracts abuse or needs per-user quota — see `docs/mcp-server-plan.md`.

**Please cite the data.** Every tool response carries a `provenance` block naming EBAS/ACTRIS and the citation expectation. The measurements are contributed by station principal investigators; acknowledge them and EBAS/ACTRIS in any published use.

**What's there today** — six tools, two resources and one prompt:

- `get_coverage` — the period × variable availability matrix plus each variable's definition; `find_station` — resolve a name or code, or browse by country and network; `get_series` — annual means per station over a period range; `get_ranking` — stations highest to lowest for one period; `get_network_stats` — median, quartiles and range across stations; `get_change` — change between two periods, steepest decline first. The model calls these itself.
- `actris://catalog/stations` — all 144 stations with coordinates, networks and per-variable coverage; `actris://citation` — attribution to paste into a manuscript. Resources are *attached by you*, from the composer's connector menu.
- **Data availability briefing** — a prompt you pick from that same menu; it reports what exists, names the gaps, and repeats the caveats.

The full reference, including the instructions the model receives, is in [docs/mcp-reference.md](docs/mcp-reference.md) — generated from the server, so it cannot drift from what the agent is actually told. What remains — monthly resolution, and prompts for trend reports and network comparisons — is in [docs/mcp-server-plan.md](docs/mcp-server-plan.md).

Two caveats the responses state explicitly and any consumer should repeat: means are unweighted across a station's files within a year, and no figure says what fraction of a period was actually observed.

## Technical Stack

**Frontend** — Vue 3, TypeScript, Pinia, TanStack Vue Query, MapLibre GL, deck.gl, Apache ECharts, shadcn-vue (Radix UI), Tailwind CSS, Vite

**Backend** — FastAPI, uvicorn, httpx, aiosqlite, NumPy, pandas, MCP Python SDK (`mcp`)

**Database** — SQLite (WAL mode) via aiosqlite

**Data sources** — EBAS THREDDS OPeNDAP (`thredds.nilu.no`), ACTRIS Data Centre API (`dc.actris.nilu.no`)

## Running Locally

```bash
# Backend — DATABASE_PATH must be set when running natively: the code default is
# /data/actris.db, which is not writable on macOS (it is the container's volume path).
cd backend
pip install -r requirements.txt
DATABASE_PATH=./data/actris.db python main.py
# Runs on localhost:8000

# Frontend
cd frontend
npm install
npm run dev
# Runs on localhost:5173
```

Or with Docker Compose:

```bash
docker compose up
```

On first run, open the app and use **Data Setup** to fetch measurement data from NILU servers. A fetch of 5 years × 3 variables typically takes a few minutes.

The database file defaults to `/data/actris.db` and can be overridden with the `DATABASE_PATH` environment variable.

## Deployment

The backend is deployed on Railway (auto-deploys on push to `main`). The frontend is built with `npm run build` and served as static files.

Environment variables that matter in production (all documented in `backend/.env.example`):

| Variable | Why |
|---|---|
| `ALLOWED_ORIGIN` | CORS allowlist — comma-separated, or `*`. Should be the real frontend origin |
| `ADMIN_TOKEN` | Guards the three mutating endpoints. **Fails closed**: unset means they return 503 |
| `MCP_ALLOWED_HOSTS` | **Required, or `/mcp` returns `421` to everything.** The MCP SDK arms DNS-rebinding protection with a localhost-only allowlist by default, and the rejection is logged server-side and reported nowhere else. Set it to the deployed hostname |
| `MCP_RATE_LIMIT_PER_MINUTE`, `MCP_MAX_CONCURRENT` | Defaults 60 and 8. Per-process counters, so replicas multiply the effective limit |
| `DATABASE_PATH` | Defaults to `/data/actris.db`, the mounted volume |

## Live Demo

[https://www.isosavi.com/test/actris-monitor/](https://www.isosavi.com/test/actris-monitor/)

## License

GPL v3
