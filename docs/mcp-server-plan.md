# MCP Server Plan

Design plan for exposing ACTRIS Monitor's data to AI agents over the Model Context
Protocol (MCP). Written 2026-09-10. Nothing here is implemented yet.

## Decisions already made

| Question | Decision | Why |
|---|---|---|
| Granularity | **Annual only in v1**, monthly on the roadmap | Ships in days; the forward-compat work below makes monthly additive rather than breaking |
| Hosting | **Remote, on the existing Railway service** | The backend is already running with a populated DB; a `/mcp` mount is close to free |
| Codebase | **Same repo, second entrypoint** | Same deploy, same container, same SQLite volume. A separate repo means a second Railway service and either a duplicated DB or a network hop |
| Output | **Data only, no rendered visuals** | Token-efficient, and agents render their own charts well from clean tabular data |

Deliberately *not* chosen (revisit later, don't relitigate without new information):

- Local stdio package on PyPI — possible in future; see "Keep the core decoupled".
- Server-rendered PNGs or deep links into the dashboard — the frontend has no URL
  state today, so deep links would require adding it.
- Building on the ACTRIS Data Centre REST API instead of THREDDS — would discard
  the catalog logic in `ebas_thredds.py`, which is the main asset here.

## Where the data stands today

Grounding facts a new session needs before touching anything:

- `backend/ebas_thredds.py` holds the valuable part: parsing the ~14k-file THREDDS
  catalog, decoding instrument and date from filenames, reading `.das` metadata for
  station coordinates and network tags, and fetching only a year slice over OPeNDAP
  ASCII (~130 KB) instead of whole netCDF files.
- `station_records` stores **one row per (year, variable, station)** with a single
  `mean`. `_fetch_file_mean` collapses the year slice to one float immediately —
  sub-annual data is downloaded and discarded.
- `network_stats` stores median/q1/q3/min/max/n per (year, variable).
- Three variables (`N`, `scattering`, `absorption`), Level 2 only, 2000 onwards.
- Fetching is on demand via the Data Setup panel — correct for a single-user
  dashboard, wrong for a shared agent endpoint (see "Pre-populate").

## Target architecture

One Railway container, one process, one SQLite file:

```
FastAPI app (Railway)
├── /api/*      existing REST  → dashboard on isosavi.com
├── /mcp        Streamable HTTP → AI agents
└── shared: database.py, ebas_thredds.py, aggregation.py
    └── /data/actris.db (volume)
```

Layout inside `backend/`:

```
backend/
├── main.py            # mounts /mcp alongside /api
├── mcp/
│   ├── server.py      # tool + resource registration
│   ├── tools.py       # the 8 tools
│   └── formatting.py  # truncation, provenance, error messages
├── database.py        # unchanged, imported by both
└── ebas_thredds.py    # unchanged, imported by both
```

Add the MCP dependency to `backend/requirements.txt`; `backend/Dockerfile` should
need no change. Work on a `feat/mcp-server` branch so `main` stays deployable
during the schema migration.

**Run the MCP transport stateless.** Railway restarts and redeploys containers
freely; stateless Streamable HTTP needs no session affinity and loses nothing on a
cold start.

**The MCP surface is read-only.** Do not expose `start_fetch`, `reset`, or
`backfill_networks` as tools. Agents retry on ambiguity and a retried reset is
unrecoverable. Those stay on the authenticated REST side for admin use.

### Pre-populate

Because the DB is now shared across agents, fill it completely — all years, all
three variables — so no agent request can trigger a fetch job. Fetch-on-demand
latency is acceptable in a dashboard where the user chose to press the button; it
is not acceptable inside a tool call.

## Tool surface (v1)

Eight tools. None are named or shaped around "annual" — resolution is a parameter
and periods are ISO dates, so monthly slots in without breaking anything.

| Tool | Purpose |
|---|---|
| `find_station(query, limit)` | Fuzzy resolution: "Hyytiälä", "SMEAR II", "Finnish forest site" → `FI0050R`. Returns candidates with code, name, country, networks, and which variables/years they cover. |
| `list_stations(country?, network?, bbox?, has_data_for?)` | Filtered catalog browse, compact rows. |
| `list_variables()` | Key, label, unit, instrument, wavelength, QC level. |
| `get_series(stations[], variables[], start, end, resolution)` | The workhorse. `resolution` enum is `["annual"]` in v1, gains `"monthly"` in v2. |
| `get_ranking(period, variable, network?, country?, limit)` | Highest-to-lowest — the ranking chart as data. |
| `get_network_stats(period_range, variable, network?)` | median / q1 / q3 / min / max / n_stations. |
| `get_change(variable, from_period, to_period, scope)` | Computed deltas, absolute and %, rankable. Its own tool because "which stations declined most 2005→2020" across ~200 stations is where agents fumble doing arithmetic by hand. |
| `get_coverage()` | The period × variable availability matrix, so an agent can check instead of discovering gaps through failures. |

`find_station` is the highest-value tool in the list. Agents never say `FI0050R`.
Without fuzzy resolution, most sessions open with a failed call.

## Response conventions

Cross-cutting rules for every tool. These matter more than the tool list.

**Caps with explicit truncation.** Never truncate silently:

```json
{ "rows": [...], "truncated": true, "n_remaining": 340,
  "hint": "narrow by country or network" }
```

**Provenance in the payload, not the docs.** Every response carries `unit`,
`level`, `instrument`, `wavelength_nm`, `coverage`, and source filenames. A model
cites only what is in the tool result.

**Errors that teach.** Today `/api/stations/{year}/{variable}` returns
`404 No data in database for 2024/absorption`. For an agent, return the recovery
path instead:

```json
{ "error": "no_data",
  "message": "No data for 2024/absorption.",
  "available_years": [2000, 2023],
  "suggestion": "Nearest available period is 2023." }
```

Agents recover from that; they loop on a bare 404. This is probably the single
largest lever on real-world success rate.

## Resources and prompts

Cheap to add, disproportionately useful:

- **Resources** — the station catalog (loaded once instead of a tool call per
  session), variable definitions with instrument and method notes, and an
  EBAS attribution + citation document.
- **Prompts** — `station_trend_report`, `network_comparison`, `anomaly_check`.
  These encode the analyses we already know how to do properly, including the
  caveats about coverage and instrument changes an agent won't apply unprompted.

## Auth and hardening

**Fix independently of MCP, and first:** `backend/main.py` defaults to
`allow_origins=["*"]` and exposes three unauthenticated mutating POSTs —
`/api/db/reset`, `/api/start-fetch`, `/api/backfill-networks`. Anyone who finds the
Railway URL can wipe the database or pin the instance against NILU's server.

For `/mcp` itself, the choice depends on distribution:

- **Bearer token header** — pragmatic for a handful of known users, roughly an
  hour of work, and supported by Claude Desktop/Code custom connectors.
- **OAuth 2.1** — what the MCP spec points at, and what a publicly listed
  connector needs. Meaningfully more work.

Plus a per-token rate limit and a global concurrency cap on anything that can
reach NILU.

## Forward-compatibility for monthly

Four things, cheap now and annoying to retrofit:

1. `resolution` as an enum parameter from day one, even with a single value.
2. `period_start` / `period_end` as ISO dates in every response — never a bare
   `year` integer.
3. New table shaped for it:

   ```sql
   CREATE TABLE station_series (
       station_id   TEXT    NOT NULL,
       variable     TEXT    NOT NULL,
       period_start TEXT    NOT NULL,   -- ISO date
       resolution   TEXT    NOT NULL,   -- 'annual' | 'monthly'
       mean         REAL,
       n_valid      INTEGER,
       coverage     REAL,
       PRIMARY KEY (station_id, variable, period_start, resolution)
   );
   ```

   The existing `station_records` becomes rows where `resolution='annual'`;
   migration is a straight insert-select.
4. Have `_fetch_file_mean` **return** the binned sub-annual array even while v1
   reduces it to one number. The OPeNDAP round trip is the expensive part and
   we're already paying for it.

## Pre-flight data-quality fixes

A dashboard draws a circle; an agent states the number as prose fact, possibly
into someone's paper. That raises the bar:

1. **`data_coverage` is a boolean in disguise.** `ebas_thredds.py` sets
   `1.0 if values else 0.0`. An agent reading `data_coverage: 1.0` will report
   full-year coverage for a station with two months of data. Either compute it
   properly or rename the field to `has_data` in the MCP layer. **Blocking for v1.**
2. **Unweighted mean of means.** Multi-file stations use `np.mean(values)` over
   per-file means without weighting by valid sample count. **Blocking for v1.**
3. **Wavelength discrepancy.** `TARGET_WAVELENGTH` is `{"scattering": 525.0,
   "absorption": 520.0}` while the labels in `main.py` and the README say 550 nm.
   Whichever is right, an agent repeats the label verbatim. Needs an answer;
   may not need a code change.
4. **QC flags.** Confirm what `lev2` selection already guarantees and whether any
   further EBAS flag filtering is warranted.

## Phasing

- **v1 — annual, remote, authed:** ~3–5 days including hardening and
  pre-population.
- **v2 — monthly:** ~1 week, mostly wall-clock time re-running the fetch job
  against NILU rather than development time.

## Keep the core decoupled

`mcp/tools.py` imports from `database.py` — never from FastAPI, never from the
route handlers. If we later publish a standalone stdio package, that boundary is
what makes it a day of work instead of a rewrite.

## Load on NILU

The dashboard is one client with a 24h cache. Agents retry, fan out, and re-ask.
Serve from the DB by strong preference, cap concurrency, back off on errors, and
send an identifying User-Agent.

## Open questions

1. **Redistribution.** A hosted MCP endpoint is a redistribution channel for
   EBAS/ACTRIS data, which carries citation and PI-acknowledgement expectations.
   Worth asking NILU/ACTRIS directly rather than letting them discover it.
2. **Public connector or private?** Decides bearer token vs OAuth 2.1, and it is
   the largest single swing in v1 effort.
3. **Attribution mechanics.** Injecting citation text into every tool response is
   the only reliable way to keep it attached once an LLM paraphrases the numbers.

## Prior art checked

No existing ACTRIS/EBAS MCP server found as of 2026-09-10. Worth a look at
`pyaerocom` / `pyaro` (Met Norway's EBAS readers) as an alternative data-access
layer, though the OPeNDAP slicing here is likely faster for this narrow use case.
