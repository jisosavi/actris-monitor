# ACTRIS Metadata API v3 — migration plan

The ACTRIS Data Portal moved to v2.0.0 in August 2026, and with it to a new
metadata API. This project uses the old Data Centre endpoint in exactly one place,
so the migration is small — but it is not a straight port, because the field we
depend on changed meaning.

Investigated 2026-09-15. **Nothing here is implemented yet.**

## This is planned work, not an incident

`https://dc.actris.nilu.no/data` still answers 200 today. Nothing is broken; the
old API is expected to be retired eventually, and moving now buys a better join and
better metadata rather than averting an outage.

## What we use it for today

One call, in `EbasThreddsClient._get_actris_dc_names`: fetch the Data Centre's
facility list and keep the names where `is_actris_nf` is `true`, lowercased. That
set is then used in `_fetch_station_meta_from_das` to add `ACTRIS` to a station's
networks when the EBAS `project` field did not already say so.

Two weaknesses, both fixed by the new API:

- **It joins on lowercased station name.** Any renaming or spelling difference
  silently drops a station, and nothing reports it.
- **It only runs during `backfill_networks`.** `fetch_measurements` never calls it
  (`_get_station_meta` passes `self._actris_dc_names or set()`, and that attribute
  is only primed by the backfill), so a normal fetch does no augmentation at all.

## The new API

`https://prod-actris-md.nilu.no`, "DVAS API" v3, OpenAPI at `/v3/api-docs`.

| Endpoint | State, probed 2026-09-15 |
|---|---|
| `GET /api/facilities` | **Works.** 1,524 facilities, 839 KB |
| `GET /api/facilities/{id}` | **Works** |
| `GET /api/version` | Works |
| `/api/metadata/search` | **500s** on every request shape tried, GET and POST |

The search endpoint is out of scope here — see "Not in scope" — but its state is
worth recording: the portal's own release notes describe a search-index memory
crash in v2.0.1 and 503-handling fixes in v2.0.2, so this is a known-shaky area
rather than a mistake in our requests.

### The join key we did not have

Each facility carries `extra_metadata.insitu.ebas_station_code`. **144 of our 145
stations match on it**, against a name match today. Also present and useful:
`ebas_station_alt`, a stable `uri` (`https://data.actris.eu/facility/<id>`), and
the labelling status.

### The field that changed meaning

The old API gave `is_actris_nf: true|false`. The new one gives
`actris_national_facility` as a **six-value labelling status**, set on every
facility:

| Status | All EBAS-coded facilities | Our stations |
|---|---|---|
| not labelled | 1384 | 99 |
| initially accepted | 36 | 24 |
| labelled | 14 | 10 |
| labelling opened | 8 | 5 |
| labelling planned | 6 | 4 |
| labelling application submitted | 3 | 2 |

Our pipeline currently tags **53** stations as ACTRIS. Only **10** are `labelled`.
The two measure different things: our tag comes mostly from the EBAS `project`
field — *data submitted under the ACTRIS framework* — while the status describes
*facility certification progress*.

## Decisions

| Question | Decision |
|---|---|
| What the ACTRIS network filter means | **Unchanged.** Keep tagging from the EBAS `project` field, so the map behaves as users expect. Carry the labelling status alongside as station metadata |
| Scope | **Facilities only**, joined by `ebas_station_code` |
| Extra fields to adopt | Facility **URI**, **labelling status**, **altitude**, and **`active`** — shown as context, never as a filter |
| Fields deliberately skipped as *filters* | WMO region, contact organisation, and `active` — but see below: `active` is worth showing, just never worth filtering on |

## Which stations are active changes over time

The network is not fixed: stations open, close, and are added to or removed from
the ACTRIS registry, and the count will keep moving. Checked 2026-09-15, only
**50 of our 144** matched facilities are `active: true` — and that flag tracks
something real. Splitting our own stations by the last year for which we hold data:

| Last year with data | `active: true` (45) | `active: false` (48) |
|---|---|---|
| 2022 or later | 38 | 17 |
| 2015–2021 | 7 | 18 |
| before 2015 | **0** | 13 |

No active station's record stops before 2015. Three consequences for this design:

**It confirms the no-storage decision.** `active` and the labelling status are
current-state facts that change, so a table keyed by year is the wrong home for
them. The cached read-through gives the current answer every time, and nothing goes
stale.

**Every count here is a snapshot, not a fact.** "50 of 144" was true on
2026-09-15 and will not stay true. Figures like it belong in a dated line, never in
a tool description or a UI label.

**Never filter on it; use it to explain.** A station inactive today still has valid
measurements from 2005, and hiding it would delete a fifth of the record. The value
is the opposite: it answers "why does this series stop in 2014?", which today is
indistinguishable from "we never fetched it". That is exactly the gap the project's
absence-is-stated convention exists to close, so the natural home is the station
detail panel and `find_station` — not a filter.

Two cautions. The 17 inactive stations with data through 2022 or later show the flag
describes the **ACTRIS facility registry**, not EBAS reporting: a site can still
submit data after leaving the registry, so "inactive" must never be rendered as "no
longer measuring". And our own record already carries an independent, historical
signal — the last period with data — which is a fact about the data rather than
about the registry. Showing both, and letting them disagree visibly, is more honest
than reconciling them.

## Design

### No schema change

Serve the new fields through a **cached read-through**, exactly like
`backend/nrt.py`: one upstream request per hour per container, last-good snapshot
on failure, never an error. A new `backend/actris_md.py` exposing
`get_facilities() -> dict[ebas_code, Facility]`.

This is the right shape rather than the convenient one. **Labelling status is a
current-state fact that changes over time** — stations progress through
certification. `station_records` is keyed by (year, variable, station), so storing
status there would assert that a station was "initially accepted" *in 2011*, which
is not a claim the data supports. Altitude and URI are static and could be stored,
but there is no reason to split the three across two mechanisms.

Consequence: no migration, no re-fetch, and the status is never stale.

### Where the ACTRIS tag is applied

Porting `_get_actris_dc_names` to the new API means replacing a name set with a
code lookup, which also removes the `actris_dc_names` parameter threaded through
`_fetch_station_meta_from_das`: the tag can be applied after parsing, keyed by
station code, rather than inside the `.das` parser.

**One behavioural question remains, and it should be measured before it is
decided.** The augmentation needs a yes/no from a six-value field. Candidate rule:
anything other than `not labelled` counts (45 of our stations). Before applying it,
run the backfill in dry-run and report the diff against current `networks` values —
which stations gain the ACTRIS tag, which lose it. If the diff is small, apply it;
if it moves many stations, bring it back as a decision rather than shipping it.

### Two edge cases the data already shows

- **`US1200R` (Mauna Loa) has no facility record.** Station metadata must degrade
  to what EBAS gives us rather than assuming a match.
- **One EBAS code maps to two facilities** (1,452 records, 1,451 distinct codes).
  The lookup needs a deterministic rule — prefer the `active` record, else the
  first by identifier — and should log the collision rather than silently pick.

### Surfaces

- **Frontend** — the station detail panel gains altitude, the labelling status, a
  link to the ACTRIS portal facility page, and the registry status paired with the
  last period we hold data for, so a series that stops has a stated reason. A new
  `useActrisFacilities()` query mirroring `useNrtStations()`.
- **MCP** — `find_station` and the `actris://catalog/stations` resource gain the
  same three fields. Both read through the same cache. Regenerate
  `docs/mcp-reference.md`; remember that connected clients only see changes after
  reconnecting.
- **Tests** — the existing suite covers the tools; add cases for a station with no
  facility record and for the duplicate-code rule.

## Not in scope

**`/api/metadata/search` as a replacement for THREDDS discovery.** It is the
strategically interesting endpoint — DOIs, landing pages, proper variable metadata,
no filename parsing — and it would replace the most valuable code in this project.
It also returns 500 to every request shape tried. Revisit when it is demonstrably
stable; `ebas_thredds.py` works and owes nothing to the portal.

## Risks

- **A second external dependency in the request path.** Mitigated the same way as
  NRT: hourly cache, fail soft, never an error. An ACTRIS outage must cost the
  labelling status and nothing else.
- **839 KB per refresh.** Once an hour per container is fine; do not fetch per
  station, and do not call `/api/facilities/{id}` in a loop.
- **The API is new.** Its search half is visibly unstable. Keep the parsing in one
  module so a schema change surfaces as one failing function.

## Verification

1. `get_facilities()` returns ~1,451 codes; block the upstream and confirm it still
   answers with a stale snapshot and no error.
2. 144 of 145 stations resolve; `US1200R` degrades cleanly.
3. The dry-run diff of the ACTRIS tag is reported before anything is applied.
4. Ranking, network statistics and the colour scale are unchanged — this adds
   metadata and must not move a single measurement.
5. A station panel shows altitude, status and a working portal link.
6. A station that is inactive but still has recent data renders as exactly that —
   not as "no longer measuring" — and an inactive station's historical values are
   still present everywhere they were before.

## Effort

Roughly a day: the module and its cache 2–3 h, the tag port plus dry-run diff 2 h,
frontend panel 2 h, MCP fields and docs 2 h.
