# MCP Server — state and roadmap

ACTRIS Monitor exposes its data to AI agents over the Model Context Protocol at
`/mcp`, on the same Railway container and the same SQLite file as the dashboard.

This document is **what exists**, **what might still be done**, and **which
decisions not to relitigate**. The per-tool reference is generated from the server
itself into `docs/mcp-reference.md` — never duplicated here, because the copy that
drifts is the one nobody reads. Operational gotchas live in `CLAUDE.md`.

Originally written 2026-09-10 as a design plan; rewritten 2026-09-14 once the tool
surface was complete.

---

# What exists

**Endpoint:** `https://actris-monitor-production.up.railway.app/mcp`, Streamable
HTTP, open and rate-limited rather than authenticated. `.mcp.json` at the repo root
points at it.

## The surface

Six tools, two resources, one prompt. Full schemas in `docs/mcp-reference.md`.

| Tool | Answers |
|---|---|
| `get_coverage` | What periods and variables exist at all, with a station count per cell |
| `find_station` | Name or code → EBAS station code; or browse by country, network, variable |
| `get_series` | Annual means for named stations over a period range |
| `get_ranking` | Stations highest to lowest for one period |
| `get_network_stats` | Median, quartiles and range across stations, per period |
| `get_change` | Change between two periods per station, steepest decline first |

**Resources** (the client attaches these; the model cannot):
`actris://catalog/stations` — all 144 stations with position, networks and
per-variable coverage as year ranges, ~50 KB, sized deliberately: year *ranges* not
lists, coordinates at 4 dp, no measurements. `actris://citation` — attribution in a
form a person pastes into a manuscript.

**Prompt:** `data_availability_briefing(variable?)` — a person picks it from the
composer menu.

## How it is wired

```
FastAPI app (Railway)
├── /api/*      existing REST  → dashboard on isosavi.com
├── /mcp        Streamable HTTP → AI agents
└── shared: database.py, variables.py, aggregation.py
    └── /data/actris.db (volume)
```

```
backend/mcp_server/
├── server.py      MCPServer instance, registration, transport security
├── tools.py       the six tools
├── resources.py   the two resources
├── prompts.py     the prompt
├── formatting.py  provenance, caps, shared rendering
└── limits.py      rate limit + concurrency cap (stands in for auth)
```

The package is `mcp_server/`, not `mcp/`: `backend/` is the working directory with
flat imports, so a local `mcp/` would shadow the installed SDK.

Four things about the SDK (v2, `mcp==2.2.0`) that are easy to get wrong, all
covered in `CLAUDE.md`: the class is `MCPServer`, not `FastMCP`; a mounted
sub-app's lifespan never runs, so the host app must enter
`mcp.session_manager.run()`; DNS-rebinding protection is armed to localhost by
default, so `MCP_ALLOWED_HOSTS` is required in deployment or everything answers
`421`; and `stateless_http` is a legacy-only knob, because a 2026-07-28 request is
one self-contained POST.

**A new tool is invisible to already-connected clients.** The surface is discovered
once per connection via `server/discover`, and `listChanged` promises a push the
stateless transport cannot deliver. Releases are therefore batched, and after one,
clients must reconnect.

## The data it serves

- **Annual means only** — `station_records` holds one row per (year, variable,
  station). Monthly or daily requests cannot be satisfied, and the tools say so
  rather than approximating.
- **Level 2 only**, three variables (`N`, `scattering`, `absorption`), 2000 onwards.
- **Fully pre-populated**: 81 (year, variable) pairs, 144 stations. No agent request
  can trigger a fetch, and nothing in the MCP path reaches NILU.
- **The current year is normally empty.** Level 2 publication lags a year or two:
  2026 holds zero stations, 2025 holds 12–16, 2023 holds 22–33. No tool resolves
  "latest" silently; where one picks a range it names the range it picked.

## Conventions every response follows

These matter more than the tool list.

- **Provenance travels with the data.** Unit, wavelength, instrument, QC level, and
  the two caveats below, in every payload — a model cites what it was handed, not
  what the documentation says.
- **Absence is stated, never implied.** A requested period with no data returns a
  null mean; a station holding nothing returns flagged; a query matching nothing
  returns candidates and a way forward. Silence is indistinguishable from "does not
  exist".
- **Truncation is never silent**, and drops whole stations rather than trailing
  rows: half a station's periods reads as a complete record and invites a trend that
  is not there. `truncated`, `n_remaining` and a `hint` naming the better tool.
- **Errors teach** — what *is* available and what to try next, not a bare 404.

## Known limitations, disclosed rather than fixed

1. **`data_coverage` is a boolean in disguise** — `ebas_thredds.py` sets
   `1.0 if values else 0.0`. The MCP layer never emits it, and every
   `provenance.coverage_basis` says coverage is presence only. A station with two
   months of data is indistinguishable from one with twelve.
2. **A station-year's mean can combine different measurands.** This is the serious
   one, and it is worse than the "unweighted mean of means" it was first recorded
   as. `fetch_measurements` selects every lev2 file whose date range overlaps the
   year and averages their per-file annual means with equal weight. Measured against
   the THREDDS catalog for **2019**:

   | | |
   |---|---|
   | Station-variable pairs fed by more than one file | **100 of 164** |
   | …mixing different size cuts or matrices | **56** |
   | …mixing different instrument ids | **80** |

   Hyytiälä's 2019 scattering mean averages **seven** files: `pm1`, `pm10`, three
   no-cut, and an `aerosol_humidified` tandem nephelometer. PM1 scattering excludes
   coarse particles and is systematically lower than PM10; the humidified channel is
   systematically higher than dry. Those are different quantities, not repeat
   measurements of one. IT0004R absorption in 2019 averages 16 files across 2
   matrices; FI0050R absorption, 14 across 4.

   Two consequences worth stating plainly. Cross-station comparison — what
   `get_ranking` and `get_change` are for — may compare a PM10 station against a PM1
   one. And **a year-to-year step can be produced purely by a file appearing or
   disappearing**, which is precisely the artefact a trend report exists to catch.

   `provenance.mean_method` now says all of this, in every payload.

Limitation 1 needs the re-fetch. Limitation 2 needs a **decision** first — see the
roadmap below — and only then the re-fetch.

## Tests

`cd backend && pytest` (after `requirements-dev.txt`). They drive the tools through
the SDK's in-process client — no HTTP, no port, about a second — and target the
conventions that fail *silently*: gaps as explicit nulls, truncation by whole
station, a search that never returns nothing, stations surviving a change ranking,
provenance on every tool.

---

# Roadmap

## Next — file composition, then the analysis prompts

This step was originally written as "backfill the instrument, then the prompts".
Checking it before building found the premise wrong and the underlying problem
bigger, so it has been rewritten.

**What was wrong.** `_parse_catalog` reads field `[3]` of the filename, which is the
instrument *class* — `nephelometer`, `cpc`, `filter_absorption_photometer`. That is
what `INSTRUMENT_MAP` selects on, so it is identical on every file for a variable by
construction. Backfilling it would write the same word on every row and never detect
a change. The field that identifies the instrument is `[8]`
(`FI03L_TSI_3563_SMR_pm10`, `SE02L_Aurora_3000_HYY_ref+Aurora_3000_HYY_wet`), and
the size cut is `[5]`. Both are in the filename convention already documented at the
top of `ebas_thredds.py`; neither is parsed today.

**The step, restated.** Backfill the *composition* of each station-year from the
cached catalog — file count, the set of matrices, the set of instrument ids, per
(station, year, variable). Still no re-fetch, still an admin endpoint mirroring
`backfill_networks`. It does not fix limitation 2; it makes it **visible**, which is
what the prompts need:

- `station_trend_report(station, variable, from_period, to_period)` — resolve the
  station, check coverage, fetch the series, then report against a fixed checklist:
  unit and wavelength from provenance rather than memory; how many requested periods
  actually have data, with the gaps named; no use of the word "trend" below a
  minimum number of periods; a "low" year may be two months of winter; the citation.
  And the one this step unlocks: **if the file composition differs between the
  endpoints — a size cut gained, an instrument swapped — say so and refuse to
  attribute the change to the atmosphere.** A trend report over composition artefacts
  is worse than no trend report, because it lends them authority.
- `network_comparison(variable, period, network?)` — ranking plus network
  statistics, with "no data" kept distinct from a genuine zero, and a note where the
  stations being compared do not share a size cut.

**The decision this defers.** Whether a station-year should keep averaging every
overlapping file, prefer one canonical matrix (dry PM10, say, falling back to
no-cut), or report each matrix as its own series. That is a science call, it changes
published numbers, and the third option changes the grain of `station_records` —
which is exactly the change `station_series` already makes for monthly. So it
belongs with the re-fetch below rather than costing a second one. Quantifying how
much the choice moves the numbers is worth doing first, and needs no schema change:
fetch per-file means for a handful of multi-file stations and compare.

## Then — monthly resolution

The large one, and mostly wall-clock rather than development time: it re-runs the
fetch against NILU. It also fixes both known limitations, which is why they wait for
it — and why the composition decision above should be made before it starts, not
after. The re-fetch is the expensive event; everything that needs one should ride
the same pass.

Four things are already in place so this stays additive: `resolution` is an enum
parameter, every response carries ISO `period_start`/`period_end` rather than a bare
year, the tools are shaped around periods rather than years, and the response
schemas do not assume annual.

Still to do:

```sql
CREATE TABLE station_series (
    station_id   TEXT    NOT NULL,
    variable     TEXT    NOT NULL,
    period_start TEXT    NOT NULL,   -- ISO date
    resolution   TEXT    NOT NULL,   -- 'annual' | 'monthly'
    matrix       TEXT    NOT NULL,   -- 'pm10' | 'pm1' | '' | 'aerosol_humidified' …
    mean         REAL,
    n_valid      INTEGER,
    coverage     REAL,
    PRIMARY KEY (station_id, variable, period_start, resolution, matrix)
);
```

`matrix` in the key is the change limitation 2 forces. Keeping size cuts as separate
rows is the only shape that lets a caller ask for one measurand, and it costs
nothing extra here: the re-fetch already visits every file, so the per-file values
are in hand at exactly the moment the rows are written. Collapsing to one row per
period, as `station_records` does, is what created the problem.

`station_records` becomes the rows where `resolution='annual'`; the migration is an
insert-select. And `_fetch_file_mean` must **return** the binned sub-annual array
and `valid.size` rather than collapsing to one float — the OPeNDAP round trip is the
expensive part and we are already paying for it. That is also where real coverage
fractions and weighted means come from.

## Designed but unscheduled

- **`actris://station/{id}`** — one station's whole record as an attachable
  document. This was deferred until `get_series` existed so the query would not be
  written twice; `get_series` now exists, so the condition has been met and the
  resource is a thin wrapper away.
- **`anomaly_check(period, variable)`** — needs a series plus network statistics for
  the same period. Both now exist.
- **`get_ranking` when rows exist but hold no usable value.** Production keeps
  `station_records` rows for the empty current year, so this returns 0 rows with
  `n_considered: 51` and an explanatory note rather than the `error: no_data`
  teaching shape. Honest either way; worth deciding whether the shapes should match.
- **QC flags** — confirm what `lev2` selection already guarantees, and whether any
  further EBAS flag filtering is warranted.

## Conditional — authentication

Deliberately unscheduled. The endpoint is open because the tools are read-only over
public EBAS data served from our own SQLite, so a token would protect the container
rather than the data — and the container is protected by
`MCP_RATE_LIMIT_PER_MINUTE` (60, per address) and `MCP_MAX_CONCURRENT` (8), both
per-process counters that replicas would multiply.

**Expect to add authentication** if any of these appear:

- **Abuse or cost** — the tell is Railway CPU or request volume rising without a
  matching rise in dashboard traffic. Per-address limits handle one rude client and
  nothing against a distributed one.
- **Per-user quota or attribution** — today every caller is indistinguishable.
- **Listing as a public connector** — requires OAuth 2.1 with dynamic client
  registration regardless of preference.
- **A request from NILU/ACTRIS** — see the open question below.

Options, ascending: a shared bearer token in ASGI middleware beside `limits.py`
(about an hour, mirrors `require_admin`'s fail-closed pattern); the SDK's
`TokenVerifier`, which gives spec-correct 401s and RFC 9728 discovery but demands an
`issuer_url` naming a real authorization server, so a static-token verifier
advertises an issuer that does not exist; or full OAuth 2.1.

Three things to get right when it happens: it is a **breaking change** for the
published URL and `.mcp.json`, so prefer a grace period with a teaching error over a
bare 401; the token must use `.mcp.json`'s `${VAR}` expansion, since committing a
literal one to a public repo is the actual leak; and keep the rate limits, because
auth identifies callers without stopping them.

## Out of scope — near-real-time data

`backend/nrt.py` exists and the map links to EBAS NRT, but exposing it through MCP
is deliberately **not** part of this work. It would mix Level 1.5 — preliminary, not
quality-assured — into a surface whose provenance block promises Level 2, and that
needs its own thinking rather than a flag. See `docs/nrt-integration-plan.md`.

## Open questions

1. **Redistribution.** A hosted MCP endpoint is a redistribution channel for
   EBAS/ACTRIS data, carrying citation and PI-acknowledgement expectations. The
   endpoint is live and its URL is published in the README and `.mcp.json`, so this
   is actual rather than hypothetical: worth asking NILU/ACTRIS directly rather than
   letting them discover it. Their answer may also settle the authentication
   question. **The only pending item that is not code.**
2. **Does attribution survive paraphrase?** Every response carries the provenance
   block, which is the only reliable way to keep citation attached once a model
   restates the numbers. Whether a model actually carries it into prose is something
   only real sessions reveal — and there are now six tools returning numbers to
   observe.

---

# Decisions worth not relitigating

| Decision | Why |
|---|---|
| **Annual only in v1**, monthly later | Ships in days; the forward-compat work above makes monthly additive |
| **Remote, on the existing Railway service** | The backend already runs with a populated DB; a `/mcp` mount is close to free |
| **Same repo, second entrypoint** | Same deploy, same container, same SQLite volume. A separate repo means a second service and either a duplicated DB or a network hop |
| **Data only, no rendered visuals** | Token-efficient, and agents chart well from clean tabular data |
| **Six tools, not eight** | `list_variables` duplicated definitions that already travel in every response; `list_stations` merged into `find_station`, where a blank query with filters is a browse |
| **Open, rate-limited, not authenticated** | Read-only tools over public data; a token protects the container, not the data. Reversible — see the triggers above |
| **One filter vocabulary** — `stations?`, `country?`, `network?`, `limit` | Three tools with three filter shapes is three chances for a model to guess wrong |
| **Caps of 10 stations × 30 periods, truncated by whole station** | 20 × 30 is ~54 KB, comparable to the whole catalogue for one call |
| **Search degrades, never empties** | An empty result reads as "no such station" and ends the session; candidates read as "narrow this" and continue it |
| **No implicit "latest" period** | The newest period is reliably the emptiest |
| **Station facts computed over the whole record** | The NRT map feature shipped with exactly this bug: a global fact derived from one period's rows |
| **The catalogue resource does not retire `find_station`** | The resource serves clients that attach it; the tool serves those that ignore resources, and sessions where 50 KB is better spent elsewhere |
| **No `actris://variables` or `actris://coverage`** | Both already travel inside `get_coverage`; a second copy is a second source of truth |
| **Read-only surface** | No `start_fetch`, `reset` or `backfill-networks`: agents retry on ambiguity, and a retried reset is unrecoverable |
| **Releases are batched** | Clients discover the surface once per connection, so each release costs every user a reconnect |

**Keep the core decoupled.** `mcp_server/tools.py` imports `database.py`,
`variables.py` and `aggregation.py` — never FastAPI, never `main`, never a route
handler, and not even the MCP SDK: registration happens in `server.py`. If a
standalone stdio package is ever published, that boundary is what makes it a day of
work instead of a rewrite.

**Be polite to NILU.** Their THREDDS server is a shared research resource. Serve
from the DB by strong preference, cap concurrency, back off on errors, and send an
identifying User-Agent. Agents retry, fan out and re-ask in a way the dashboard
never did.

## Prior art

No existing ACTRIS/EBAS MCP server found as of 2026-09-10. `pyaerocom` / `pyaro`
(Met Norway's EBAS readers) are worth a look as an alternative data-access layer,
though the OPeNDAP slicing here is likely faster for this narrow use case.
