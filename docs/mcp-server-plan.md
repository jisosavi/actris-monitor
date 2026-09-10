# MCP Server Plan

Design plan for exposing ACTRIS Monitor's data to AI agents over the Model Context
Protocol (MCP). Written 2026-09-10.

**Status:** the transport is built and one tool of the eight (`get_coverage`) is
live — see `backend/mcp_server/` and the MCP section of `CLAUDE.md`. The v1 spike
deliberately proved the mount, the Host allowlist, the rate limiter and the
response conventions against a real client before writing seven more tools against
guesses. Everything below still describes the target; the notes marked
**implemented** or **superseded** record where reality has moved.

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
├── main.py            # mounts /mcp alongside /api (mount stays LAST in the file)
├── variables.py       # implemented: one definition per variable, shared by all three
├── mcp_server/        # NOT "mcp/" — see below
│   ├── server.py      # tool + resource registration, transport security
│   ├── tools.py       # the 8 tools
│   ├── formatting.py  # truncation, provenance, error messages
│   └── limits.py      # implemented: rate limit + concurrency cap
├── database.py        # unchanged, imported by both
└── ebas_thredds.py    # unchanged, imported by both
```

**The package is `mcp_server/`, not `mcp/`.** `backend/` is the working directory
and imports are flat (`import database`), so a local `mcp/` package would shadow
the installed `mcp` distribution and break its own import.

Add the MCP dependency to `backend/requirements.txt`. `backend/Dockerfile` needed
one change after all: `--proxy-headers --forwarded-allow-ips="*"`, because Railway
terminates TLS and without it uvicorn builds `http://` redirects (which MCP clients
refuse) and the rate limiter sees the proxy as every caller.

### SDK reality (v2, `mcp==2.2.0`)

This plan was written against the v1 API. Four corrections:

- `from mcp.server import MCPServer` — not `FastMCP`. Response models are Pydantic,
  and `structured_content` comes for free from the return annotation.
- **A mounted sub-app's lifespan never runs.** The host app must enter
  `mcp.session_manager.run()`, and the manager exists only after
  `streamable_http_app()` has been called.
- **DNS-rebinding protection is on by default, allowlisting localhost only.** Behind
  a real hostname every request is `421` until `transport_security=` is given an
  allowlist. This is the most likely way a first deploy fails.
- **`stateless_http=True` is a legacy-only knob.** On protocol 2026-07-28 a request
  is one self-contained POST with no session id, so there is nothing for Railway to
  be sticky about and nothing to configure. Set for the legacy leg only, which costs
  nothing here because the server needs no server-to-client back-channel.

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
| `get_coverage()` | **Implemented.** The period × variable availability matrix, so an agent can check instead of discovering gaps through failures. Also returns each variable's definition (unit, instrument, wavelength, QC level) so values can be described without a second call. |

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

Three mechanisms, three distinct failure modes. **Tools** are verbs the model calls
— they fix "the agent can't get the data". **Resources** are documents the
application attaches — they fix "the agent doesn't know what exists", which is a
real problem here because agents never say `FI0050R`. **Prompts** are procedures
with the caveats baked in — they fix "the agent states a number as fact without the
caveats", the specific risk of a dataset with unweighted means and presence-only
coverage.

Claude Desktop surfaces resources and prompts in the composer under Connectors, so
their titles are user-facing UI labels, not internal identifiers.

### Resources

**Implemented:**

- `actris://catalog/stations` (`application/json`) — every station with identity,
  position, networks, and a per-variable coverage summary as compact year ranges
  (`"2000-2019,2021-2024"`). Attached once, it answers "which Finnish ACTRIS sites
  measure absorption" and "what is Hyytiälä's station code" with **no tool call**,
  removing the failed first call that otherwise opens a session.
  - **Size is the design constraint: ~228 bytes per station, so ~50 KB (~13k
    tokens) for the full network.** Hence year *ranges* rather than lists,
    coordinates rounded to 4 dp, and no measurements in the document. It is an
    attach-when-relevant resource, not something to load reflexively.
  - Metadata is picked from each station's most recent year, because it is stored
    per station-year and the rows can disagree — `update_station_meta_bulk` rewrites
    lat/lon/networks for all of a station's rows but leaves `name`/`country` as
    whatever each fetch wrote. `database.get_station_catalog` relies on SQLite
    guaranteeing that bare columns beside a `MAX()` come from the row that produced
    the maximum.
  - **This does not retire `find_station`.** The resource serves clients that attach
    it; the tool serves clients that ignore resources, sessions where 50 KB is better
    spent elsewhere, and fuzzy matching done server-side ("Finnish forest site" →
    `FI0050R`), which a raw JSON document cannot do. They share one DB helper.
- `actris://citation` (`text/markdown`) — the attribution EBAS/ACTRIS and the
  contributing PIs expect, in a form a person can paste into a manuscript. Not
  redundant with the `provenance` field: provenance is machine-readable and aimed at
  the model, this is a document aimed at a human. Same content, different audience.

**Deliberately not built:**

- `actris://variables` and `actris://coverage` — both already travel inside
  `get_coverage`'s payload. A second copy creates two sources for one truth, and the
  one that goes stale is the one nobody reads.
- `actris://station/{id}` (templated) — attractive, but it is the same query as
  `get_series`. Build the tool first and make the resource a thin wrapper over it,
  or the query gets written twice.

### Prompts

**Implemented:** `data_availability_briefing(variable?)` — the only one the current
tool surface can support. Instructs a model to call `get_coverage` and then report
what exists, **name** the gaps, distinguish "period reporting zero stations" from
"period never fetched", restate what `coverage_basis` and `mean_method` mean for the
requested analysis, and refuse to approximate monthly figures from annual means.
Modest analytical value; its real job was proving the prompt path surfaces in a
client before the expensive ones get written.

**Designed, blocked on tools — and specified now on purpose.** A prompt's checklist
is a requirements document for the tools it calls, so writing it first surfaces
return-shape requirements that tool design alone misses:

- `station_trend_report(station, variable, from_period, to_period)` — resolve the
  station, check coverage, fetch the series, then report against a fixed checklist:
  state unit and wavelength from provenance rather than memory; say how many
  requested periods actually have data and name the gaps; do not use the word
  "trend" below a minimum number of periods; flag that a "low" year may be two
  months of winter; flag an instrument change between endpoints, which alone can
  move the number; carry the citation.
  - **What that forces on `get_series`:** explicit gap markers rather than silently
    omitted periods, a per-period valid-sample count, and the instrument per period.
    None of it is in the schema today — `station_records` does not even store the
    instrument.
- `network_comparison(variable, period, network?)` — needs `get_ranking` and
  `get_network_stats`, and **forces them to agree on what `n_stations` counts** and
  to distinguish "no data" from a genuine zero. That distinction is live already:
  2026 legitimately reports `n_stations: 0` for all three variables, because no
  Level-2 data is published for the current year yet.
- `anomaly_check(period, variable)` — needs a series plus network statistics for the
  same period.

### Sequencing

1. **Done** — the two resources and `data_availability_briefing`, all implementable
   against today's schema.
2. **Next** — `find_station` and `get_series`, plus the index they need
   (`idx_sr_lookup` leads with `year`, so a lookup by station code alone is a full
   scan) and the instrument-per-period the trend report requires.
3. **Then** — `station_trend_report` and `network_comparison`, which now have tools
   to call.

## Auth and hardening

**Fix independently of MCP, and first:** `backend/main.py` defaults to
`allow_origins=["*"]` and exposes three unauthenticated mutating POSTs —
`/api/db/reset`, `/api/start-fetch`, `/api/backfill-networks`. Anyone who finds the
Railway URL can wipe the database or pin the instance against NILU's server.

**Update:** the three mutating POSTs are now guarded by `require_admin`
(`X-Admin-Token` against `ADMIN_TOKEN`, failing closed). `allow_origins` still
defaults to `*` and remains open.

**Superseded — `/mcp` is unauthenticated by design.** The bearer-token vs OAuth 2.1
choice below assumed the endpoint needed an identity. It does not: the tools are
read-only over public EBAS data served from our own SQLite, so a token would protect
the container, not the data. That is also how hosted open-data MCP servers generally
run — the alternative pattern, a local stdio package with no auth at all, has the
same property for the same reason.

What replaced it (`mcp_server/limits.py`): a sliding-window per-address limit
(`MCP_RATE_LIMIT_PER_MINUTE`, default 60) and a global concurrency cap
(`MCP_MAX_CONCURRENT`, default 8) wrapped around the MCP app only, answering `429`
and `503` with `Retry-After` and a message that tells an agent to batch rather than
poll. Both counters are per-process: replicating the service multiplies the
effective limit.

### Authentication is a live roadmap item, not a closed question

Open was the right call for the v1 spike, and it is reversible. The endpoint URL is
now published — `.mcp.json` at the repo root and a section in the README point at
the Railway service — which raises the discoverability that makes the decision worth
revisiting. **Expect to add authentication** if any of these show up:

- **Abuse or cost.** The per-address limit handles one rude client and does nothing
  against a distributed one. The tell is Railway CPU or request volume rising without
  a matching rise in dashboard traffic.
- **Per-user quota or attribution.** Today every caller is indistinguishable, so
  there is no way to throttle one heavy user without throttling everyone, and no way
  to know who is redistributing the data.
- **Listing as a public connector.** Requires OAuth 2.1 with dynamic client
  registration regardless of what we would otherwise prefer.
- **A request from NILU/ACTRIS.** See the redistribution question below; if they want
  the channel controlled, tokens are the mechanism.

The options, in ascending cost:

- **Shared bearer token, ASGI middleware** — roughly an hour. Compare
  `Authorization: Bearer <secret>` against an env var in the same middleware chain as
  `limits.py`, mirroring `require_admin`'s fail-closed pattern. Works with
  `claude mcp add --header` and with `.mcp.json`.
- **Bearer token via the SDK's `TokenVerifier`** — spec-correct `401` plus RFC 9728
  discovery at `/.well-known/oauth-protected-resource/mcp`. But `token_verifier=` and
  `auth=AuthSettings(issuer_url=...)` must travel together (the SDK raises otherwise),
  and `issuer_url` has to name a real authorization server — so a static-token
  verifier publishes a discovery document pointing nowhere. Plain middleware is the
  honest shortcut until there is an actual issuer.
- **OAuth 2.1** — what the MCP spec points at, and what a publicly listed connector
  needs. Meaningfully more work, and mostly configuration outside this repo.

Three things to get right when it happens:

1. **It is a breaking change for every published client.** The committed `.mcp.json`
   and the README URL are now the advertised entry point; adding auth silently turns
   them into `401`s. Bump the README, and prefer a grace period where an
   unauthenticated call returns a teaching error naming how to get a token rather
   than a bare `401`.
2. **Never commit the token.** `.mcp.json` supports environment expansion — use
   `"headers": {"Authorization": "Bearer ${ACTRIS_MCP_TOKEN}"}` so the committed file
   stays secret-free. A literal token in that file is the actual leak, and it is a
   public repo.
3. **Keep the rate limits.** Auth identifies callers; it does not stop one
   authenticated caller from hammering the container. The two controls are
   complementary, and per-token limits are the natural upgrade once callers have
   identities.

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
   full-year coverage for a station with two months of data. **Handled for v1 by
   disclosure, not by computation:** the MCP layer never emits the field, and every
   response's `provenance.coverage_basis` states that coverage is presence only. The
   real figure lands with the monthly work, which re-fetches anyway.
2. **Unweighted mean of means.** Multi-file stations use `np.mean(values)` over
   per-file means without weighting by valid sample count. **Same treatment:**
   `provenance.mean_method` says so in every payload. Fixing it properly requires
   `_fetch_file_mean` to return valid-sample counts, i.e. a re-fetch.
3. ~~**Wavelength discrepancy.**~~ **Resolved.** The constants (525 nm scattering,
   520 nm absorption) were right and the "550 nm" labels were wrong. Both now come
   from `backend/variables.py`, the single definition of a variable, and
   `wavelength_nm` is in every MCP response. Note selection is nearest-neighbour
   with no tolerance check, which the response says too.
4. **QC flags.** Confirm what `lev2` selection already guarantees and whether any
   further EBAS flag filtering is warranted.

## Phasing

- **v1 spike — transport + one tool: done.** Mount, Host allowlist, rate limiter and
  the response conventions, verified against a real MCP client.
- **v1 remainder — the other seven tools, then pre-population.** `find_station`
  first: agents never say `FI0050R`, so without fuzzy resolution most sessions open
  with a failed call. It needs an index — `idx_sr_lookup` leads with `year`, so a
  lookup by `station_id` alone is a full scan today.
- **v1 — annual, remote, authed:** ~3–5 days including hardening and
  pre-population.
- **v2 — monthly:** ~1 week, mostly wall-clock time re-running the fetch job
  against NILU rather than development time.

## Keep the core decoupled

`mcp_server/tools.py` imports from `database.py` and `variables.py` — never from
FastAPI, never from `main`, never from the route handlers. It does not even import
the MCP SDK: registration happens in `server.py`. If we later publish a standalone stdio package, that boundary is
what makes it a day of work instead of a rewrite.

## Load on NILU

The dashboard is one client with a 24h cache. Agents retry, fan out, and re-ask.
Serve from the DB by strong preference, cap concurrency, back off on errors, and
send an identifying User-Agent.

## Open questions

1. **Redistribution — now the most pressing of the three.** A hosted MCP endpoint is
   a redistribution channel for EBAS/ACTRIS data, which carries citation and
   PI-acknowledgement expectations. The endpoint is live and its URL is published in
   the README and `.mcp.json`, so this has moved from hypothetical to actual: worth
   asking NILU/ACTRIS directly rather than letting them discover it. Their answer may
   also settle the authentication question above.
2. ~~**Public connector or private?**~~ Answered for now: **public and open**, with
   rate limiting instead of tokens, because the data is public and read-only. Not
   permanent — see "Authentication is a live roadmap item" above for the triggers
   that would reopen it.
3. **Attribution mechanics.** Injecting citation text into every tool response is
   the only reliable way to keep it attached once an LLM paraphrases the numbers.
   **Implemented** for `get_coverage` via `formatting.Provenance`; the open part is
   whether a model actually carries it into prose, which only real sessions reveal.

## Prior art checked

No existing ACTRIS/EBAS MCP server found as of 2026-09-10. Worth a look at
`pyaerocom` / `pyaro` (Met Norway's EBAS readers) as an alternative data-access
layer, though the OPeNDAP slicing here is likely faster for this narrow use case.
