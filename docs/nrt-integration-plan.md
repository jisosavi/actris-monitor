# NRT Integration Plan

Linking EBAS near-real-time (NRT) data to the dashboard map. Investigated and
decided 2026-09-14, **implemented the same day**.

Shipped: `backend/nrt.py` with the availability proxy, click-to-select with a
station detail panel, the LIVE chip on hovered stations, and distinct markers for
the live-data-only sites. Deliberately not shipped: rendering NRT measurements
ourselves — the dashboard links out instead, see "Deliberately not chosen".

One bug is worth remembering from the build, because it is a shape that recurs:
the first version decided which sites were "NRT-only" by subtracting the *selected
year's* stations, so in an empty year the entire NRT network rendered as unknown
sites. The fix moved that judgement to the backend, which knows every station in
every year. It was caught by running the app, not by reading the code.

The goal: when a station on the map has live data at
<https://ebas-nrt.nilu.no>, say so and offer a way through to it — without
pretending the two datasets are the same thing.

## Decisions already made

| Question | Decision | Why |
|---|---|---|
| Depth | **Link out, don't render** | NRT visualisation stays NILU's job. No preliminary data rendered under our name, nothing new to keep working |
| Interaction | **Click selects a station and opens a detail panel** | The map has no click handling at all today, and a hover tooltip cannot hold a clickable link |
| NRT-only stations | **Shown, as a distinct marker type** | 7 sites have live data we have no annual record for |
| What counts as "NRT available" | **Only our three variables** | The badge should predict what the user finds, not lead to a pollen chart |

## What NRT actually is

Verified against the live service, not assumed:

- **An undocumented JSON API exists**, found in `/static/js/nrt.js`:
  `/api/stations` (GeoJSON, 54 stations, 36 KB), `/api/station/{id}` (404s for
  unknown ids), `/api/station/{id}/datafiles`, and `/plot-html/{id}`.
- **No CORS headers.** The browser cannot call it from isosavi.com. This single
  fact is why a backend endpoint is required rather than a frontend fetch.
- **No `X-Frame-Options` or CSP**, so iframing is technically permitted — see
  "Deliberately not chosen" for why it is still the wrong move.
- **The files sit on the THREDDS server we already read**: catalog `actris_nrt`,
  111 datasets, hourly resolution, rolling windows from 3 weeks to 3 months.
- **The data is `lev1.5`** — near-real-time, preliminary, *not* fully
  quality-assured. The entire rest of this project is Level 2 only. Some eBC
  products are `lev3b`.

## What lights up

Filtering to our three variables (`cpc` → N, `nephelometer` → scattering,
`filter_absorption_photometer` → absorption):

| | Count |
|---|---|
| NRT stations with at least one of our variables | 30 |
| → badge on a station already on our map | **23** |
| → new markers, no annual record of our own | **7** |
| Our stations with no NRT at all | **121** |

The seven: Dübendorf, Zürich-Kaserne, Marseille Longchamp, Potenza (CIAO),
ISAC Bologna II, Racibórz, Wrocław.

**84% of the map gains nothing from this feature.** It must read as an
annotation on the few, not as an attribute the rest are missing.

## Source: their API, not THREDDS

Both were compared. The THREDDS `actris_nrt` catalog is a **strict subset** —
no station appears there that is missing from their site — while their
`/api/stations` carries three stations with our variables that THREDDS does not
list (`CH0007U`, `CH0010U`, `FR0035U`).

Since the badge's promise is "their site will show you something", their own list
is the only source that cannot lie about it. Sourcing from THREDDS would let us
claim availability for a station whose link then lands on an empty page.

## Backend

A new `backend/nrt.py` holding the client (mirroring `ebas_thredds.py`'s shape and
keeping `main.py` thin), plus one endpoint:

```
GET /api/nrt/stations
```

```jsonc
{ "fetched_at": "2026-09-14T…Z", "stale": false,
  "source": "https://ebas-nrt.nilu.no/api/stations",
  "stations": {
    "FI0096G": { "name": "Pallas", "lat": 67.97, "lon": 24.12,
                 "variables": ["N", "absorption", "scattering"],
                 "url": "https://ebas-nrt.nilu.no/?station=FI0096G" } } }
```

Declared **above the MCP mount** in `main.py` — the root mount matches every path,
so anything below it is unreachable.

Three properties matter more than the shape:

1. **Cached 1 h, in-process.** One upstream request per hour per container no
   matter how many visitors — the same politeness rule the THREDDS client follows.
   NRT updates hourly, so a shorter TTL buys nothing.
2. **Fails soft, always 200.** On upstream error serve the last good cache; with no
   cache return `{"stations": {}, "stale": true}`. An NRT outage must never degrade
   the Level 2 dashboard — it just means no badges appear.
3. **Variables derived from the filename convention**, ignoring pollen monitors,
   SMPS, GC and PTR-MS.

## Frontend

- **New state:** `selectedStationId` in `stores/stations.ts`.
- **`StationMap.vue`** gains `onClick` on both existing layers. The hover tooltip
  stays as it is, plus a small **LIVE** chip when the station has NRT.
- **`StationDetail.vue`**, a new panel: the station's annual record, and an NRT
  section when available.
- **A third deck.gl layer** for the 7 NRT-only markers. Design constraint: hollow
  circles already mean "no data for the selected year", so these need a genuinely
  distinct encoding — a different shape or a ringed dot — not another hollow
  variant.

**The constraint that matters most:** the 7 NRT-only stations must not leak into
anything aggregate — not the ranking chart, not the network median/IQR, not the
colour scale, not the station count. They come from a different dataset and happen
to share a map. Clicking one opens a panel with only an NRT section.

## Saying what the data is

The NRT panel states plainly that the data is **preliminary Level 1.5, not
quality-assured**, hourly over a rolling window, provided by NILU, and **not
comparable** with the annual means shown beside it. This is the same standard the
MCP provenance block holds itself to, for the same reason: a number presented
without its caveat gets repeated without it. The link opens in a new tab with
`rel="noopener noreferrer"`.

## Deliberately not chosen

- **Embedding their plot.** `/plot-html/{id}` is a **779 KB fragment** carrying no
  Plotly of its own, so we would ship Plotly 2.35 and inject three-quarters of a
  megabyte per station. Iframing `/?station=X` instead drags in their entire nav and
  map.
- **Fetching NRT ourselves and drawing it natively.** Genuinely attractive and
  cheaper than it looks — the files are on the same THREDDS server, in the same
  filename convention `ebas_thredds.py` already parses, so the existing OPeNDAP
  slicing would mostly work as-is. Deferred because it commits us to rendering
  preliminary data under our own name and to recurring load on NILU, before we know
  anyone wants it in-app. Revisit if click-through shows they do; it would also make
  a natural MCP tool.

## Verification

1. The endpoint returns 30 stations.
2. Block the upstream: it still answers 200 with `stale: true`, and the dashboard
   renders normally with no badges.
3. The map shows 23 badges and 7 new markers, while the ranking chart, stats cards
   and colour scale stay **identical to before** — the proof that the 7 did not leak
   into any aggregate.
4. Clicking a badged station opens a panel whose link lands on that station.
5. Clicking a non-NRT station says so, rather than offering a dead link.
6. Phone width.

## Effort and risk

Roughly a day: backend 2–3 h, click-and-panel 3–4 h, markers and badges 2 h.

The main risk is that the API is undocumented and can change without notice.
Mitigated by failing soft and keeping all parsing in `backend/nrt.py`, so a break
surfaces as missing badges rather than a broken dashboard.
