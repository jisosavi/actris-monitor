# Year slicing — plan

The app is missing years that EBAS holds, and some of the years it does show are
computed from the wrong window. Found 2026-09-18 from user feedback about Pallas
(Sammaltunturi) and Värriö.

**Status: phases 0-2 and 4 are implemented.** Phase 3 — the forced re-fetch that
reaches stored values — has not been run, so the live numbers are still the old
ones. Verified against the Pallas file that was failing: 2005 and 2006 now return
values where they returned nothing, 2007 correctly returns nothing because the file
ends 2006-12-31, and the recomputed 2005 (7.824) is within 0.2% of the value stored
under **2004** (7.840) — the drift, made concrete.

This is in `ebas_thredds.py`, which `CLAUDE.md` calls the valuable, subtle part.
Read this whole document before changing it.

## What is wrong

Two faults, one visible and one not.

### 1. The file's end date is read from the wrong field

`_parse_catalog` takes `parts[2]` of the filename as the data end. It is the
**revision date**. The extent is `parts[6]`, the duration.

```
FI0096G.20000202120000.20181031145000.nephelometer..aerosol.7y.1h...
        └─ start ────┘ └─ revision ─┘                        └─ 7y
```

For that file, four sources and only one of them is ours:

| Source | Data ends |
|---|---|
| EBAS portal | 2007-01-01 |
| `parts[6]` duration `7y` | ~2007-02 |
| The netCDF's own `time[51673]` | 2006-12-31 |
| **`parts[2]`, what we use** | **2018-10-31** |

**96% of the 12,419 catalogue files** have `parts[2]` later than start + duration,
median overshoot **7.9 years**. Within our three instruments, 900 files, **587
(65%) span more than one year** — and each of those has a tail year whose slice
runs off the end of the array:

```
2003: idx 25536-34295  -> HTTP 200
2004: idx 34296-43079  -> HTTP 200
2005: idx 43080-51839  -> HTTP 400   (the array ends at 51673)
```

The 400 is swallowed by the bare `except Exception: return None` at the end of
`_compute_annual_mean`, so the year disappears with no error and no log entry.
Pallas scattering holds 2000-2004 and not 2005-2007, exactly at that boundary.

### 2. Index is assumed to be hour-offset, and is not

`_estimate_year_indices` computes `(days since file start) × 24`. That is only
true if the file is a gapless hourly grid. Measured on the same file:

| | actual | assumed | drift |
|---|---|---|---|
| `time[0]` | 2000-02-02 | 2000-02-02 | 0 |
| `time[8760]` | 2001-02-02 | 2001-02-01 | +1 day |
| `time[25536]` | 2004-01-05 | 2003-01-01 | **+369 days** |
| `time[51673]` | 2006-12-31 | 2005-12-25 | **+371 days** |

So the stored Pallas scattering **"2003" was computed from roughly 2004's data**.
Where a multi-year file contains a gap, every year after it is mislabelled.

Resolution is not a factor for us: 899 of our 900 files really are `1h`. The drift
comes from gaps, not from sampling rate.

## What has to change

**The filename cannot answer this question.** `parts[6]` fixes which years to
*attempt* — it matches the portal — but it still overstates the array: `7y` implies
61,368 samples where the file holds 51,674, so the tail year would still overrun.
Only the `time` coordinate is authoritative.

### Phase 0 — stop swallowing the evidence

Independently valuable, and first because everything else is easier to verify once
failures are visible.

`_compute_annual_mean` ends in `except Exception: return None`. Replace it with a
log line naming the file, the constraint and the error. `CLAUDE.md` already records
this bare except as a known caveat, filed as a rare problem about netCDF variable
names; it has been hiding a defect affecting most multi-year files. A silent
`return None` in the one place that talks to the network was the real bug.

### Phase 1 — trust the duration field for *selection*

Parse `parts[6]` (`7y`, `1y`, `3mo`, `10w`) into a real end date and use it in
`_FileInfo.end`. Keep `parts[2]` under a different name if anything wants the
revision date; nothing does today.

This alone corrects which files are considered for a year, and stops us requesting
years a file never covered. It does **not** fix the tail overrun or the drift.

### Phase 2 — take the window from the `time` array

The actual fix. For each file, resolve the year's index bounds from the file's own
time coordinate rather than from arithmetic on dates.

Sketch:

1. `.dds` gives the array length `n`.
2. Fetch `time` **strided** — `time[0:n-1:24]` — one value per day. For a seven-year
   file that is ~2,500 values, roughly 45 KB.
3. `searchsorted` on those gives the year boundary to within 24 samples.
4. One small exact fetch around each boundary pins it precisely.
5. Cache the result **per file**, not per (file, year): a 7y file serves seven
   years, so the cost amortises across them.

Then `_compute_annual_mean` requests a slice that is inside the array by
construction, and whose first and last timestamps are inside the requested year.

**Assert that last point rather than assume it.** If the window's own timestamps
fall outside the year, skip the file and log it. That check is what would have
caught the present bug, and the check already in the code would not: it compares
the returned array length against the *requested* length, and OPeNDAP returns
exactly what was asked for even when the window is wrong.

**Cost.** Today: one ~130 KB slice per (file, year). After: the same slice, plus
~50 KB per *file* once. With 900 files and roughly 2,500 (file, year) combinations,
that is single-digit percent more traffic, not a multiple — worth confirming before
the re-fetch, since `CLAUDE.md` is explicit about being polite to NILU.

### Phase 3 — re-fetch, and expect the numbers to move

A forced re-fetch of all 81 (year, variable) pairs. Two things will change:

- **Years appear.** Pallas scattering should gain 2005-2007, 2011-2012 and 2025;
  Värriö should gain 2013-2016 and 2018-2020.
- **Existing values change**, wherever a file had an internal gap. This is not a
  cosmetic change: a published annual mean will move because it was previously the
  wrong year's data.

The second needs saying out loud to the scientists rather than shipping quietly —
they have been reading these numbers.

### Phase 4 — the documentation that currently describes the bug as a caveat

- `CLAUDE.md`: the "year slices are estimated from filenames" section becomes a
  description of the time-array method. The bare-except caveat is resolved.
- `docs/mcp-server-plan.md`: the limitations list.
- `provenance.mean_method` if the wording implies filename-derived windows.
- Both generated artefacts regenerate; `--check` fails until they do.

## It also decides whether `observed_fraction` is right

`observed_fraction` maps a file's valid samples onto hour-of-year using
`hour_offset`, which comes from the same filename arithmetic. On a file with a gap,
the coverage mask is shifted by the same drift. The feature is only as correct as
this fix — worth doing before anyone trusts a coverage percentage, and worth
re-running the coverage numbers as part of phase 3.

## Verification

1. Pallas scattering gains 2005-2007, 2011-2012, 2025. Värriö gains 2013-2016,
   2018-2020.
2. For three station-years spanning a gap, the computed window's first and last
   timestamps are inside the year — checked against the `time` array directly.
3. A file whose slice would overrun produces a log line, not a silent absence.
4. Total (station, variable, year) combinations before and after, reported as a
   number: this is the headline "how much data was missing".
5. A handful of means checked against the EBAS portal by hand, including one that
   changes and one that should not.
6. Leap years, files starting mid-year, and files ending mid-year covered by unit
   tests against synthetic time arrays.

## Effort

| Phase | | Estimate |
|---|---|---|
| 0 | Log the swallowed failures | 1 hour |
| 1 | Duration field for file extent | 2 hours |
| 2 | Time-array bounds, cached per file, with the window assertion | ~1 day |
| 3 | Forced re-fetch, verification, telling the scientists | half a day + run time |
| 4 | Documentation ripple and regeneration | 2 hours |

About two and a half days. Phase 0 is worth shipping on its own the moment it is
written.

## Open questions

- **Strided time fetch, or fetch the whole array?** Strided plus refinement is
  ~50 KB per file; the whole array is ~900 KB for a seven-year file. Strided is
  recommended, but the simpler version is defensible if the traffic turns out not
  to matter.
- **How many stored values actually change?** Unknown until phase 2 runs. It
  determines how loudly phase 3 needs announcing.
- **Do the changed values need marking in the UI?** A station-year whose mean moved
  because it was previously mislabelled is a different claim, not a refinement.

## Not in scope

- Changing how the mean is computed across files. The aggregation question is
  closed; see `docs/mcp-server-plan.md`.
- Sub-annual storage. Reading the time array makes it *possible*; it remains a
  schema change and nobody has asked for it.
