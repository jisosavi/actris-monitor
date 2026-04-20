# ACTRIS Monitor: Aerosol In-Situ Network Dashboard

## What is ACTRIS Monitor?

ACTRIS Monitor is an interactive visualization dashboard for long-term aerosol measurement data from the ACTRIS/EBAS European research network. It displays annual station averages, year-on-year concentration changes, and network-wide statistics for three key atmospheric variables across measurement stations spanning Europe and beyond.

Data is fetched directly from the EBAS THREDDS OPeNDAP server at NILU (Norwegian Institute for Air Research), covering fully quality-controlled Level 2 observations from 2011 to 2022.

For inspiration, thanks to research professor Antti Hyvärinen / Finnish Meteorological Institute!

## Measured Variables

**Particle Number Concentration (N)** — Total aerosol particle count per cm³, measured by Condensation Particle Counters (CPC). Primary indicator of new particle formation events and anthropogenic pollution.

**Scattering Coefficient (σ_sp, 525 nm)** — Aerosol light scattering at 525 nm measured by nephelometers. Relates to aerosol optical depth and visibility reduction.

**Absorption Coefficient (σ_ap, 520 nm)** — Aerosol light absorption at 520 nm measured by filter absorption photometers. Indicator of black carbon and light-absorbing aerosol loading.

## Interface

The dashboard renders a full-screen dark map using MapLibre GL with a deck.gl ScatterplotLayer. Each station appears as a circle scaled by concentration magnitude and coloured either by absolute value (low–high gradient) or by annual change (green = decrease, red = increase).

A control panel provides year selection (2011–2022), variable switching, and map colour mode toggle. A station ranking chart lists all stations from highest to lowest for the selected year and variable. Network statistics display the median, interquartile range, minimum, and maximum across all reporting stations.

Hovering a station shows a tooltip with the station name, country, annual mean with unit, year-on-year percentage change, and data coverage.

## Data Architecture

The backend fetches the EBAS THREDDS catalog (~14,000 netCDF files) and filters to Level 2 files matching the selected instrument type and year range. For each relevant file, it estimates the year-slice index range from filename dates and retrieves only that slice via OPeNDAP ASCII constraint expressions — avoiding full file downloads of several GB per file.

Station coordinates and names are read from each file's OPeNDAP `.das` attribute structure. All results are cached in-memory for 24 hours.

The pydap library is not used. OPeNDAP ASCII endpoint access via `urllib` is used throughout, as pydap/webob returns HTTP 503 from the NILU THREDDS server.

## Technical Stack

**Frontend** — Vue 3, Pinia, TanStack Query, MapLibre GL, deck.gl, Apache ECharts, Tailwind CSS, Vite

**Backend** — FastAPI, uvicorn, httpx, NumPy, pandas

**Data source** — EBAS THREDDS OPeNDAP (`thredds.nilu.no`), ACTRIS Level 2 in-situ aerosol data

## Running Locally

```bash
# Backend
cd backend
pip install -r requirements.txt
python main.py

# Frontend
cd frontend
npm install
npm run dev
```

The frontend dev server runs on `localhost:5173`, the backend on `localhost:8000`.

First data load takes 30–90 seconds while the THREDDS catalog and file slices are fetched from NILU servers. Results are cached for 24 hours.

## Live Demo

[https://www.isosavi.com/test/actris-monitor/](https://www.isosavi.com/test/actris-monitor/)

## License

GPL v3
