"""
Aggregation helpers: transform raw ACTRIS API records into station stats.

Column mapping at the top of compute_annual_stats() must be updated to match
the actual field names returned by the ACTRIS API (verify against swagger).
"""

from __future__ import annotations
import pandas as pd
import numpy as np


# ── Column name mapping ──────────────────────────────────────────────────────
# Keys are the names we expect from the ACTRIS API response.
# Update these if the actual response uses different field names.
COL_MAP = {
    "facility_id":    "id",
    "facility_name":  "name",
    "latitude":       "lat",
    "longitude":      "lon",
    "country_code":   "country",
    "mean_value":     "mean",
    "data_coverage":  "data_coverage",
}
# ─────────────────────────────────────────────────────────────────────────────


def compute_annual_stats(
    raw: list[dict],
    prev_raw: list[dict] | None,
    unit: str,
) -> list[dict]:
    """Return per-station annual mean + YoY delta, sorted highest-to-lowest."""
    if not raw:
        return []

    df = pd.DataFrame(raw)

    missing = [c for c in COL_MAP if c not in df.columns]
    if missing:
        raise ValueError(
            f"ACTRIS response missing expected columns: {missing}. "
            "Update COL_MAP in aggregation.py to match the actual API field names."
        )

    df = df.rename(columns=COL_MAP)
    df = df[df["mean"].notna() & (df["mean"] > 0)].copy()
    df["data_coverage"] = df.get("data_coverage", pd.Series(1.0, index=df.index)).fillna(1.0)

    prev_map: dict[str, float] = {}
    if prev_raw:
        pf = pd.DataFrame(prev_raw)
        if "facility_id" in pf.columns and "mean_value" in pf.columns:
            prev_map = dict(zip(pf["facility_id"].astype(str), pf["mean_value"]))

    records = []
    for _, row in df.iterrows():
        prev = prev_map.get(str(row["id"]))
        delta_pct: float | None = None
        if prev and prev > 0:
            delta_pct = round((float(row["mean"]) - prev) / prev * 100, 2)

        records.append(
            {
                "id": str(row["id"]),
                "name": str(row["name"]),
                "lat": float(row["lat"]),
                "lon": float(row["lon"]),
                "country": str(row.get("country", "")),
                "mean": round(float(row["mean"]), 3),
                "unit": unit,
                "delta_pct": delta_pct,
                "prev_mean": round(prev, 3) if prev else None,
                "data_coverage": round(float(row["data_coverage"]), 3),
            }
        )

    return sorted(records, key=lambda x: x["mean"], reverse=True)


def compute_network_stats(stations: list[dict], year: int, variable: str) -> dict:
    values = [s["mean"] for s in stations if s["mean"] is not None]
    if not values:
        return {
            "median": None, "q1": None, "q3": None,
            "min": None, "max": None, "n_stations": 0,
            "year": year, "variable": variable,
        }

    arr = np.array(values, dtype=float)
    return {
        "median": round(float(np.median(arr)), 3),
        "q1": round(float(np.percentile(arr, 25)), 3),
        "q3": round(float(np.percentile(arr, 75)), 3),
        "min": round(float(arr.min()), 3),
        "max": round(float(arr.max()), 3),
        "n_stations": len(values),
        "year": year,
        "variable": variable,
    }
