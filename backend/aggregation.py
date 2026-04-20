"""
Aggregation helpers: transform enriched station records into stats.

Expected input fields (produced by EbasThreddsClient.fetch_measurements):
  id, name, lat, lon, country, mean, data_coverage
"""

from __future__ import annotations
import pandas as pd
import numpy as np

_REQUIRED = {"id", "name", "lat", "lon", "country", "mean", "data_coverage"}


def compute_annual_stats(
    raw: list[dict],
    prev_raw: list[dict] | None,
    unit: str,
) -> list[dict]:
    """Return per-station annual mean + YoY delta, sorted highest-to-lowest."""
    if not raw:
        return []

    df = pd.DataFrame(raw)

    missing = _REQUIRED - set(df.columns)
    if missing:
        raise ValueError(f"Station records missing columns: {missing}")

    df = df[df["mean"].notna() & (df["mean"] > 0)].copy()
    df["data_coverage"] = df["data_coverage"].fillna(1.0)

    prev_map: dict[str, float] = {}
    if prev_raw:
        pf = pd.DataFrame(prev_raw)
        if {"id", "mean"}.issubset(pf.columns):
            prev_map = dict(zip(pf["id"].astype(str), pf["mean"]))

    records = []
    for _, row in df.iterrows():
        prev = prev_map.get(str(row["id"]))
        delta_pct: float | None = None
        if prev and prev > 0:
            delta_pct = round((float(row["mean"]) - prev) / prev * 100, 2)

        records.append({
            "id":            str(row["id"]),
            "name":          str(row["name"]),
            "lat":           float(row["lat"]),
            "lon":           float(row["lon"]),
            "country":       str(row.get("country", "")),
            "mean":          round(float(row["mean"]), 3),
            "unit":          unit,
            "delta_pct":     delta_pct,
            "prev_mean":     round(prev, 3) if prev else None,
            "data_coverage": round(float(row["data_coverage"]), 3),
        })

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
        "median":     round(float(np.median(arr)), 3),
        "q1":         round(float(np.percentile(arr, 25)), 3),
        "q3":         round(float(np.percentile(arr, 75)), 3),
        "min":        round(float(arr.min()), 3),
        "max":        round(float(arr.max()), 3),
        "n_stations": len(values),
        "year":       year,
        "variable":   variable,
    }
