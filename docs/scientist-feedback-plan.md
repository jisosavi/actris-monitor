# Scientist feedback — plan

Four suggestions from the scientists using the dashboard, September 2026. One was
already shipped; the other three are planned here. **Not implemented.**

The fourth is the substantial one, and it is the fix this project already
anticipated: `docs/mcp-server-plan.md` says limitation 1 would be fixed by a
re-fetch computing coverage properly as a side effect. The request arrived
independently, which is a good sign the caveat was visible to readers.

## Decisions already made

| Question | Decision | Why |
|---|---|---|
| How to expose real coverage | **Repurpose `data_coverage`, and add it to the MCP payloads** | The column exists and the name finally becomes true. Agents are the readers most likely to over-trust an annual mean |
| A file whose resolution is not hourly | **Omit it from the union, and log it** | A missing percentage is honest; a wrong one is worse than none |
| The full re-fetch | **Decide later** | Build and verify the computation first; the re-fetch is an operational call once its output can be seen |
| Storing "could not determine" | **Make `data_coverage` nullable** | `NOT NULL DEFAULT 0.0` cannot express *unknown*, and `0.0` means "observed nothing", a different claim. SQLite cannot relax the constraint, so `init_db` rebuilds the table — cheap, since the re-fetch rewrites every row anyway |
| The field name | **`observed_fraction`, 0–1, in both REST and MCP** | `StationMatch.coverage` already exists and means *which years hold data*. A second field called coverage, meaning something else, would sit next to it. One name through both doors |

## 1. The registry note — done

*"Not currently registered as operating…"* under **Labelling** in the station
panel. Removed in `6fc6055`, merged in `012e8a8`. It appears on the live site until
the next upload.

Worth recording what it cost: the note explained that *not labelled* describes the
ACTRIS **registry** rather than the data. Removing it makes the panel tighter and
loses that explanation at the point of confusion. The scientists judged the
explanation unnecessary for their own audience, which is the right call to respect —
but if a general reader later asks why a station shows "not labelled", this is why.

## 2. Open the station panel from the ranking chart

**The architecture already supports it.** `StationDetail.vue` takes no props — it
reads `selectedStationId` from the Pinia store. So the chart sets that value and the
existing panel opens, ACTRIS metadata and NRT status included, because those are
queries keyed by station id.

Two things to get right:

- **The chart renders reversed.** `seriesData` is built from `reversedStations` and
  the tooltip reads `stations[n - 1 - p.dataIndex]`. The click handler needs the
  same mapping; getting it wrong opens the wrong station's panel *plausibly*, which
  is the kind of bug that survives review.
- **Clicking the name, not just the bar**, needs `axisLabel: { triggerEvent: true }`
  on the y-axis and a handler branching on `params.componentType === 'yAxis'`. Wire
  both — the scientists asked for the name, and the bar is the larger target.

**One thing to look at before deciding it is finished:** the panel is absolutely
positioned inside the map area (`StationMap.vue:273`), so a click in the chart opens
a panel *over the map*, above the chart that was clicked. That is probably good — it
ties the two views together and the map marker highlights at the same time — but it
should be seen rather than assumed.

## 3. Drag to resize the ranking panel

The layout is already a flex column: `.map-area { flex: 1 }` and
`.ranking-area { height: 240px; flex-shrink: 0 }`. Make that height reactive, add a
drag handle on the top border, and the map takes whatever is left automatically.

Include, or it will feel unfinished:

- **Min and max clamps.** Below roughly 120px the chart is unreadable; above about
  70% of the viewport the map stops being a map.
- **Persist in `localStorage`**, so the choice survives a reload.
- **Double-click the handle to reset** to 240px.
- **Call ECharts `resize()` on drag end.** vue-echarts autoresizes on *window*
  resize, not on container change, so the chart would otherwise keep the old size
  until the window moved.
- A `cursor: row-resize` handle with a real hit area (~7px), and
  `user-select: none` on the body while dragging.

## 4. Data coverage as a real percentage

The request: show, in the station detail panel, what fraction of the year actually
holds valid data — hours out of 8760, or 8784 in a leap year. It lets a reader judge
what an annual mean is worth.

### It is nearly free at the source

`_compute_annual_mean` in `ebas_thredds.py` already computes the numerator and
throws it away:

```python
valid = data[(data > 0) & np.isfinite(data)]
return float(np.mean(valid)) if valid.size > 0 else None
```

`valid.size` is the count. And `data_coverage REAL NOT NULL DEFAULT 0.0` already
exists in `station_records`, so **there is no migration**. Three things make it more
than a one-line change.

### Multiple files cannot be summed

Most station-years have several files, sometimes overlapping in time with different
size cuts. Summing per-file valid counts exceeds 100%; taking the maximum
understates files that are complementary in time.

The correct structure is a **union over hour slots**: a boolean array of 8760 (8784)
per station-year, with each file's valid samples mapped to their hour-of-year index
and OR'd in. Trivial memory, and exact.

Note what it answers: *how many hours of the year hold at least one valid
measurement* — not how many hold a measurement of the same measurand. Given that the
mean itself already mixes size cuts, that is the consistent question. It does not
resolve the aggregation caveat and must not be described as if it does.

### The hourly assumption is an estimate, and this tests it

`_estimate_year_indices` computes `(days) * 24` from **filename dates**. It assumes
hourly resolution and never checks. For a mean that is tolerable — a wrong window
still yields values. For a percentage it is the denominator, so a non-hourly file
would produce a confidently wrong number.

So compare the returned array length against the expected slice length, and where
they disagree, **omit that file from the union and log it**. Nobody currently knows
how often the assumption fails; this measures it. Expect the bare
`except Exception: return None` in `_compute_annual_mean` to have been hiding some of
this — the same silent path that was already dropping files whose netCDF lacks the
exact `NC_VAR` name.

A station-year whose files were all omitted gets **no percentage**, not zero. Zero
means "we looked and found nothing", which is a different claim.

### What has to change with it

Repurposing the field means every place describing it is now wrong:

| Where | Currently says |
|---|---|
| `CLAUDE.md`, known-caveats list | "has-data flag, not a coverage fraction, despite the name" |
| `provenance.coverage_basis` | "Presence only… not what fraction of the period was observed" |
| `docs/mcp-getting-started.md` | the same caveat, in the two-caveats section |
| `docs/public/openapi.json` | via the route description in `main.py` |
| `docs/mcp-server-plan.md` | limitation 1, and *Both are permanent* |
| `docs/index.md` | the caveats feature card |

Both generated artefacts need regenerating, and `--check` will fail until they are.

The MCP tools do not currently expose `data_coverage` as a field, so adding it is a
**new output field** rather than a changed one — but it is still a surface change,
and clients see it only after reconnecting. The REST API does expose it, and its
meaning changes silently for anyone consuming it; today that is only our own
frontend.

### Naming and the nullable column

Two wrinkles this plan missed on the first pass, both settled above.

`data_coverage` is `NOT NULL DEFAULT 0.0`, so there is nowhere to put *unknown*.
The rename to `observed_fraction` and the nullable rebuild happen together, in one
`init_db` migration: create the new table, copy, drop, rename. `mean REAL` is
already nullable, so the pattern exists.

And `StationMatch.coverage` in the MCP surface already means *which years hold data
for this station*. The new field is deliberately not called coverage.

### Frontend

The value flows through `aggregation.py` → `/api/stations` → the `Station` type as
it does today, under the new name. The panel renders it. Show it as a percentage with a plain label —
*"Data coverage: 87% of 2023"* — and render the no-data case as "not available"
rather than 0%.

## Verification

1. Pick three station-years and check the percentage against EBAS by hand, including
   one with several files and one with a known gap.
2. A station-year with two overlapping files does not exceed 100%.
3. A leap year divides by 8784.
4. The resolution mismatch path is exercised by a test, and produces "no percentage"
   rather than a number.
5. `dump_mcp_tools.py --check` and `dump_openapi.py --check` fail before the docs are
   updated and pass after.
6. Clicking a bar and clicking a y-axis label both open the correct station.
7. The ranking panel's height survives a reload, and the chart redraws at the new
   size rather than the old one.

## Effort

| Item | Estimate |
|---|---|
| 2 — click-through from the ranking chart | 1–2 hours |
| 3 — drag-resizable ranking panel | 2–3 hours |
| 4 — coverage computation, union, resolution check, tests | ~1 day |
| 4 — documentation ripple and regeneration | ~2 hours |
| 4 — frontend display | 30 min |
| 4 — the forced re-fetch of 81 (year, variable) pairs | operational, deferred |

Suggested order: 2 and 3 first — small, visible, no data risk — then 4 on its own
branch, because it changes the meaning of a published field and wants the re-fetch
run deliberately rather than alongside UI work.

## Not in scope

- **Monthly or sub-annual data.** Coverage is a count of hours, not a time series.
  Storing sub-annual values remains a schema change, as `mcp-server-plan.md` says.
- **Changing how the mean is computed.** The aggregation question is closed; see
  that plan before touching `fetch_measurements`.
- **Filtering or ranking by coverage.** Showing the number is the request. Whether a
  low-coverage station should be excluded from a ranking is a scientific judgement
  nobody has asked for yet.
