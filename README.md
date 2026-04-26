# ACTRIS Monitor: Aerosol In-Situ Network Dashboard

## What is ACTRIS Monitor?

ACTRIS Monitor is an interactive visualization dashboard for long-term aerosol measurement data from the ACTRIS/EBAS European atmospheric research network. It displays annual station averages, year-on-year concentration changes, and network-wide statistics for three key atmospheric variables across measurement stations spanning Europe and beyond.

Data is fetched on demand from the EBAS THREDDS OPeNDAP server at NILU (Norwegian Institute for Air Research) and stored locally in a SQLite database. The app supports fully quality-controlled Level 2 observations from 2000 onwards.

For inspiration, thanks to research professor Antti Hyvärinen / Finnish Meteorological Institute!

## Measured Variables

**Particle Number Concentration (N)** — Total aerosol particle count per cm³, measured by Condensation Particle Counters (CPC). Primary indicator of new particle formation events and anthropogenic pollution.

**Scattering Coefficient (σ_sp, 550 nm)** — Aerosol light scattering at 550 nm measured by nephelometers. Relates to aerosol optical depth and visibility reduction.

**Absorption Coefficient (σ_ap, 550 nm)** — Aerosol light absorption at 550 nm measured by filter absorption photometers. Indicator of black carbon and light-absorbing aerosol loading.

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

## Technical Stack

**Frontend** — Vue 3, TypeScript, Pinia, TanStack Vue Query, MapLibre GL, deck.gl, Apache ECharts, shadcn-vue (Radix UI), Tailwind CSS, Vite

**Backend** — FastAPI, uvicorn, httpx, aiosqlite, NumPy

**Database** — SQLite (WAL mode) via aiosqlite

**Data sources** — EBAS THREDDS OPeNDAP (`thredds.nilu.no`), ACTRIS Data Centre API (`dc.actris.nilu.no`)

## Running Locally

```bash
# Backend
cd backend
pip install -r requirements.txt
python main.py
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

The backend is deployed on Railway (auto-deploys on push to `main`). The frontend is built with `npm run build` and served as static files. The `ALLOWED_ORIGIN` environment variable controls CORS (comma-separated list or `*`).

## Live Demo

[https://www.isosavi.com/test/actris-monitor/](https://www.isosavi.com/test/actris-monitor/)

## License

GPL v3
