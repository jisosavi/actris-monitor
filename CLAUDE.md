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
  scripts/dump_openapi.py        regenerates docs/public/openapi.json (Public routes only)
frontend/src/
  composables/useStationData.ts  axios instance + all TanStack Query hooks
  stores/stations.ts             Pinia UI state (year, variable, filters)
  components/                    StationMap, RankingChart, StatsCards, AdminPanel
docs/README.md                   what lives in docs/ and which files are generated
docs/.vitepress/                 VitePress site: config, theme, Scalar component
docs/index.md                    site landing page
docs/mcp-getting-started.md      site page: connecting an MCP client
docs/api.md                      site page: the Scalar REST reference
docs/mcp-reference.md            generated MCP surface reference — do not hand-edit
docs/public/openapi.json         generated public REST surface — do not hand-edit
docs/public/examples/            a real captured MCP exchange, embedded and tested
docs/docs-site-plan.md           the docs site: decisions, build order, what is live
docs/scientist-feedback-plan.md  planned UI changes + real data-coverage percentage
docs/year-slicing-plan.md        FILE EXTENTS ARE MIS-PARSED — missing and mislabelled years
docs/mcp-server-plan.md          MCP: what exists, what might still be done, why
docs/nrt-integration-plan.md     plan for linking EBAS near-real-time data to the map
docs/actris-metadata-api-plan.md  plan for moving to the ACTRIS metadata API v3
.github/workflows/ci.yml         tests, both --check gates, and the deployable build
.github/assets/                  screenshots the README uses (not part of the site)
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

**Year slices come from the file's own time coordinate.** They used to be
estimated from the filename, and both halves of that estimate were wrong: `parts[2]`
is the file's *revision* date rather than its end (96% of the catalogue, median 7.9
years out), and index was assumed to equal hour-offset, which only holds for a
gapless grid. Together they lost the tail year of every multi-year file to a silent
HTTP 400, and shifted the values of every year after an internal gap — Pallas
scattering's stored "2004" was 2005's data. See `docs/year-slicing-plan.md`.

Now `_fetch_time_axis` reads the length, the time units and a strided sample of the
time values **once per file** (cached — a seven-year file serves seven years from
one read). `_TimeAxis.bracket` brackets the year in that sample, the data and its
timestamps are fetched for the widened bracket, and the window is trimmed by the
timestamps themselves. Nothing infers a date from an index.

`parts[6]`, the duration field, gives the nominal extent and is used only to decide
which files to *consider* for a year. It is not accurate enough to slice with: `7y`
implies 61,368 samples on a file holding 51,674.

Still fetch slices, not whole files — that is the reason the app is usable.

**Known data-quality caveats** (documented, not yet fixed — see the plan doc):
- ~~`data_coverage` is a has-data flag despite the name~~ — resolved. It is now
  `observed_fraction`: the share of the year's hours holding a usable value,
  **unioned** across a station's files rather than summed, because files overlap in
  time. `NULL` means it could not be determined and is **not** the same as `0.0`;
  nothing may collapse the two. A file whose sample count contradicts the
  filename-derived slice length is excluded from the union rather than guessed at —
  see `union_observed_hours`. Rows written before this change read as `NULL` until
  a forced re-fetch.
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
- ~~**A file whose netCDF lacks the exact `NC_VAR` name is silently skipped**~~ —
  the skipping remains, the silence does not. That bare `except Exception: return
  None` was filed here as a rare problem about variable names; it was in fact
  hiding the year-slicing defect above, on most multi-year files, for months. Every
  failed fetch now logs the file, the index range, the year and the error. **Do not
  reintroduce a silent `return None` on a network path** — it is the single change
  that would have turned months of missing data into an afternoon's work.
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

**Every route carries exactly one tag** — `Public`, `Admin` or `Internal` — and
`scripts/dump_openapi.py` publishes only the `Public` ones to
`docs/public/openapi.json`, which the documentation site's Scalar page reads. A new
route without a tag is published nowhere and appears in no reference; **tag it when
you add it**. The tags are not `include_in_schema=False` on purpose: that flag
would also hide the admin routes from this app's own `/docs`, and the operator
running a fetch is exactly who needs them there. `--check` exits 1 when the
committed document is stale, same as the MCP one.

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

## The documentation site (`docs/`)

VitePress, its own npm project (`cd docs && npm run build`), published to
`isosavi.com/test/actris-monitor/docs/`. `docs/docs-site-plan.md` has the decisions
and what is still open. Three things bite:

**Build the frontend first.** `outDir` is `../frontend/dist/docs`, so one upload
carries the dashboard and its docs together — but `vite build` empties
`frontend/dist`, which takes the docs with it if the order is reversed.

**The Scalar page needs `vp-raw` on its container.** VitePress installs a click
handler on `window` with `{ capture: true }` and calls `preventDefault()` on every
same-origin link, then resolves the hash itself. Scalar's endpoint links are hashes
like `#GET/api/stations/{year}/{variable}`, which is not a valid selector — so the
click is cancelled, nothing scrolls, and the URL and sidebar highlight still update
because those happen first. It looks like a rendering bug. `router.js` skips links
inside `.vp-raw`, which hands the click back. Stopping propagation in the container
cannot work: capture on `window` runs before any listener inside it.

**`cleanUrls` and `ignoreDeadLinks` both stay off.** The dashboard's directory on
the server carries a catch-all rewrite, so a URL with no file behind it renders the
map rather than 404ing — clean URLs would break every deep link, and a dead link in
production would be invisible. `docs/public/.htaccess` turns that rewrite off inside
the docs directory. VitePress validates file links but **not anchors**, so a wrong
`#section` still ships silently.

## The MCP endpoint (`/mcp`)

Same process, same FastAPI app, same SQLite connection as `/api/*`; agents speak
Streamable HTTP. `backend/mcp_server/` holds it and `docs/mcp-server-plan.md` has
the design and the roadmap. Live today: **all six tools** (`get_coverage`,
`find_station`, `get_series`, `get_ranking`, `get_network_stats`, `get_change`),
**two resources** (`actris://catalog/stations`, `actris://citation`) and **one
prompt** (`data_availability_briefing`).

**CI:** `.github/workflows/ci.yml` runs the backend tests, both `--check` gates,
the frontend type-check and lint, and builds the deployable site — which it uploads
as a run artifact, so a deploy comes from a known commit rather than from whatever
`frontend/dist` happens to hold. It also asserts `api.html` still renders without
JavaScript.

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

**The protocol era is chosen by a request header, and silently.** The SDK's
`streamable_http_manager` routes on `MCP-Protocol-Version` **alone** — it never
inspects the body, so putting the version in `params._meta` does nothing. A request
without that header is served on the legacy leg, where the 2026-07-28 methods do not
exist: `server/discover` answers `-32601` and capabilities report
`listChanged: false`. Nothing errors; the client just gets an older protocol than the
documentation describes. With the header, plus an `Mcp-Method` matching the body and
the `_meta` envelope, the same server answers `listChanged: true` throughout. This
cost an afternoon and produced a confident, wrong report that three documented claims
were false — the claims were fine, the request was malformed. Verified curls for both
paths are on the *Connecting a client* page.

**Never call `database.init_db()` from the MCP layer.** It repoints the
module-global connection without closing the old one *and* flips every
`status='running'` fetch job to `'failed'`. The tools rely on the lifespan having
done it once.

**A new tool, resource or prompt is invisible to already-connected clients.** An
earlier version of this note claimed the stateless transport had no server-to-client
channel at all. That was wrong: 2026-07-28 replaced the HTTP GET endpoint with
`subscriptions/listen`, a long-lived POST-response stream that clients opt into per
notification type (`toolsListChanged` and friends), and the SDK implements it. The
reason is simpler and unchanged in effect:

- **We never push**, because our tool list cannot change within a process lifetime.
  It changes by redeploying, which drops every stream anyway.
- **A client may not be listening.** `subscriptions/listen` is opt-in, and a client
  that never opens the stream learns nothing.
- **A client may be holding a cached list.** List results now carry `ttlMs` and
  `cacheScope`, and a client may reuse `tools/list` until the TTL expires.

So after deploying a new tool, **reconnect the connector**. Opening a new
conversation re-probes nothing.

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
