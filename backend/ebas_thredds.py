"""
EBAS in-situ aerosol data via NILU THREDDS/OPeNDAP (ASCII endpoint).

Catalog:  https://thredds.nilu.no/thredds/catalog/ebas/catalog.xml
OPeNDAP:  https://thredds.nilu.no/thredds/dodsC/ebas/<filename>

Filename convention (dot-separated):
  STATION . START . END . INSTRUMENT . COMPONENT . MATRIX . DURATION . RESOLUTION . * . LEVEL . nc

Only lev2 files are used (fully QC'd data).

Data access strategy:
  1. Estimate year indices from filename dates (no time-array download needed)
  2. Fetch Wavelength coordinate (~100 bytes) when needed
  3. Fetch only the year's data slice (~130 KB per file)
  4. All results cached 24 h
"""

from __future__ import annotations

import asyncio
import logging
import re
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import httpx
import numpy as np

logger = logging.getLogger(__name__)

CATALOG_URL = "https://thredds.nilu.no/thredds/catalog/ebas/catalog.xml"
OPENDAP_BASE = "https://thredds.nilu.no/thredds/dodsC/ebas"

INSTRUMENT_MAP: dict[str, list[str]] = {
    "N":          ["cpc"],
    "scattering": ["nephelometer"],
    "absorption": ["filter_absorption_photometer"],
}

NC_VAR: dict[str, str] = {
    "N":          "particle_number_concentration_amean",
    "scattering": "aerosol_light_scattering_coefficient_amean",
    "absorption": "aerosol_absorption_coefficient_amean",
}

TARGET_WAVELENGTH: dict[str, float] = {
    "N":          0.0,
    "scattering": 525.0,
    "absorption": 520.0,
}

_TTL = timedelta(hours=24)
_MAX_CONCURRENT = 20
_EPOCH = date(1900, 1, 1)


def _match_network(token: str) -> str | None:
    """Map a raw project token to a canonical network name, tolerating variations."""
    t = token.strip().upper()
    if t.startswith("ACTRIS"):
        return "ACTRIS"
    if t.startswith("EMEP"):
        return "EMEP"
    if "GAW" in t or "WDCA" in t:
        return "GAW-WDCA"
    return None


@dataclass
class _FileInfo:
    station: str
    name: str
    instrument: str
    start: date
    end: date


ACTRIS_DC_URL = "https://dc.actris.nilu.no/data"


class EbasThreddsClient:
    def __init__(self) -> None:
        self._http: httpx.AsyncClient | None = None
        self._catalog: tuple[list[_FileInfo], datetime] | None = None
        self._station_meta: dict[str, dict] = {}
        self._data_cache: dict[str, tuple[Any, datetime]] = {}
        self._actris_dc_names: set[str] | None = None

    async def start(self) -> None:
        self._http = httpx.AsyncClient(timeout=60.0)

    async def close(self) -> None:
        if self._http:
            await self._http.aclose()

    async def fetch_measurements(self, year: int, variable: str) -> list[dict]:
        """
        Return enriched station records for compute_annual_stats:
          [{id, name, lat, lon, country, mean, data_coverage}, ...]
        """
        key = f"{year}:{variable}"
        if (hit := self._get_cached(key)) is not None:
            return hit

        catalog = await self._get_catalog()

        instruments = INSTRUMENT_MAP[variable]
        nc_var = NC_VAR[variable]
        target_wl = TARGET_WAVELENGTH[variable]

        relevant = [
            f for f in catalog
            if f.instrument in instruments
            and f.start.year <= year <= f.end.year
        ]

        all_instrument = [f for f in catalog if f.instrument in instruments]

        rep_files: dict[str, _FileInfo] = {}
        for fi in all_instrument:
            if fi.station not in rep_files:
                rep_files[fi.station] = fi
        for fi in relevant:
            rep_files[fi.station] = fi

        sem = asyncio.Semaphore(_MAX_CONCURRENT)
        assert self._http

        means, metas = await asyncio.gather(
            asyncio.gather(*[_fetch_file_mean(self._http, f, nc_var, year, target_wl, sem) for f in relevant]),
            asyncio.gather(*[self._get_station_meta(fi, sem) for fi in rep_files.values()]),
        )

        for fi, meta in zip(rep_files.values(), metas):
            if meta and fi.station not in self._station_meta:
                self._station_meta[fi.station] = meta

        by_station: dict[str, list[float]] = {}
        for fi, mean in zip(relevant, means):
            if mean is not None:
                by_station.setdefault(fi.station, []).append(mean)

        records = []
        for station_code, meta in self._station_meta.items():
            if station_code not in rep_files:
                continue
            values = by_station.get(station_code)
            records.append({
                "id":            station_code,
                "name":          meta["name"],
                "lat":           meta["lat"],
                "lon":           meta["lon"],
                "country":       meta["country"],
                "mean":          float(np.mean(values)) if values else None,
                "data_coverage": 1.0 if values else 0.0,
                "networks":      meta.get("networks", ""),
            })

        self._set_cached(key, records)
        return records

    async def _get_actris_dc_names(self) -> set[str]:
        """Return lowercase ACTRIS National Facility names from the ACTRIS Data Centre."""
        if self._actris_dc_names is not None:
            return self._actris_dc_names
        try:
            assert self._http
            resp = await self._http.get(
                ACTRIS_DC_URL,
                params={"page": "1", "per_page": "1000"},
                headers={"Accept": "application/json"},
                timeout=30.0,
            )
            data = resp.json()
            # facilities: [id, name, lat, lon, altitude, is_actris_nf]
            self._actris_dc_names = {
                f[1].strip().lower()
                for f in data.get("facilities", [])
                if f[5] is True
            }
            logger.info("Fetched %d ACTRIS NF station names from DC", len(self._actris_dc_names))
        except Exception as exc:
            logger.warning("Could not fetch ACTRIS DC station list: %s", exc)
            self._actris_dc_names = set()
        return self._actris_dc_names

    async def backfill_networks(self, station_ids: list[str]) -> dict[str, dict]:
        """
        Re-fetch .das metadata for all given station_ids.
        Returns {station_id: {lat, lon, networks}} for every station found in catalog.

        Picks one file per unique instrument type per station (max 5) so that
        measurements submitted under different frameworks (EMEP, GAW-WDCA, ACTRIS)
        are all captured — each submission can have a different 'project' value.
        Networks from all files are merged via set union.
        """
        catalog = await self._get_catalog()
        actris_dc_names = await self._get_actris_dc_names()

        station_ids_set = set(station_ids)
        station_files: dict[str, list[_FileInfo]] = {}
        for fi in catalog:
            if fi.station not in station_ids_set:
                continue
            files = station_files.setdefault(fi.station, [])
            # One file per instrument keeps request count low while covering
            # all frameworks (each instrument submission may use a different one).
            if len(files) < 5 and fi.instrument not in {f.instrument for f in files}:
                files.append(fi)

        if not station_files:
            return {}

        sem = asyncio.Semaphore(_MAX_CONCURRENT)
        assert self._http
        client = self._http

        async def _fetch_file(fi: _FileInfo) -> tuple[str, dict | None]:
            async with sem:
                return fi.station, await _fetch_station_meta_from_das(client, fi, actris_dc_names)

        all_results = await asyncio.gather(*[
            _fetch_file(fi)
            for files in station_files.values()
            for fi in files
        ])

        # First successful result per station provides name/lat/lon/country;
        # subsequent results from the same station only contribute their networks.
        merged: dict[str, dict] = {}
        for station_id, meta in all_results:
            if meta is None:
                continue
            if station_id not in merged:
                merged[station_id] = {**meta}
            else:
                existing = {n for n in merged[station_id]["networks"].split(",") if n}
                new_nets = {n for n in meta["networks"].split(",") if n}
                combined = sorted(existing | new_nets)
                merged[station_id]["networks"] = ",".join(combined)

        return merged

    async def get_catalog_years(self, variable: str) -> set[int]:
        """Return all years that have data for a given variable in the catalog."""
        catalog = await self._get_catalog()
        instruments = INSTRUMENT_MAP.get(variable, [])
        return {f.end.year for f in catalog if f.instrument in instruments}

    async def _get_catalog(self) -> list[_FileInfo]:
        if self._catalog:
            files, ts = self._catalog
            if datetime.now() - ts < _TTL:
                return files
        assert self._http
        resp = await self._http.get(CATALOG_URL)
        resp.raise_for_status()
        files = _parse_catalog(resp.text)
        self._catalog = (files, datetime.now())
        return files

    async def _get_station_meta(self, fi: _FileInfo, sem: asyncio.Semaphore) -> dict | None:
        if fi.station in self._station_meta:
            return self._station_meta[fi.station]
        async with sem:
            assert self._http
            return await _fetch_station_meta_from_das(self._http, fi, self._actris_dc_names or set())

    def _get_cached(self, key: str) -> Any | None:
        if key in self._data_cache:
            data, ts = self._data_cache[key]
            if datetime.now() - ts < _TTL:
                return data
        return None

    def _set_cached(self, key: str, data: Any) -> None:
        self._data_cache[key] = (data, datetime.now())


# ── Catalog parsing ───────────────────────────────────────────────────────────

def _parse_catalog(xml_text: str) -> list[_FileInfo]:
    root = ET.fromstring(xml_text)
    ns = {"t": "http://www.unidata.ucar.edu/namespaces/thredds/InvCatalog/v1.0"}
    files: list[_FileInfo] = []
    for d in root.findall(".//t:dataset", ns):
        name = d.get("name", "")
        if not name.endswith(".nc") or "lev2" not in name:
            continue
        parts = name.split(".")
        if len(parts) < 4:
            continue
        try:
            start = datetime.strptime(parts[1][:8], "%Y%m%d").date()
            end   = datetime.strptime(parts[2][:8], "%Y%m%d").date()
            files.append(_FileInfo(
                station=parts[0],
                name=name,
                instrument=parts[3],
                start=start,
                end=end,
            ))
        except (ValueError, IndexError):
            continue
    return files


# ── Async OPeNDAP fetch helpers ───────────────────────────────────────────────

async def _fetch_opendap_ascii(client: httpx.AsyncClient, base_url: str, constraint: str) -> str:
    q = urllib.parse.quote(constraint, safe="")
    url = f"{base_url}.ascii?{q}"
    resp = await client.get(url, timeout=60.0)
    resp.raise_for_status()
    return resp.text


def _parse_first_section_floats(text: str) -> np.ndarray:
    """
    Extract floats from the FIRST data section of an OPeNDAP ASCII response.

    For Grid variables the response contains multiple sections separated by blank
    lines (array data, then each coordinate/map variable). We only want the first.
    """
    after_sep = text.split("-----\n", 1)[-1] if "-----" in text else text
    sections = re.split(r"\n\n+", after_sep.strip())
    if not sections:
        return np.array([])

    first = sections[0]
    lines = first.split("\n")

    vals: list[float] = []
    for line in lines[1:]:
        line = line.strip()
        if not line:
            continue
        line = re.sub(r"\[\d+\]", "", line)
        for tok in line.split(","):
            tok = tok.strip()
            if tok:
                try:
                    vals.append(float(tok))
                except ValueError:
                    pass

    return np.array(vals, dtype=float)


def _extract_coord_value(line: str, hemi_chars: str) -> tuple[float | None, str | None]:
    """
    Extract a coordinate value and optional hemisphere letter from one DAS line.

    Handles:
      - DMS:               62 13 12.0 S  /  62:13:12S  /  62°13'12"S
      - Decimal + suffix:  62.22S  /  62.22 S  /  "62.22S"
      - Signed float:      -62.22
    Returns (decimal_value, hemisphere_char_or_None).
    """
    # DMS: D[sep]M[sep]S [hemi]
    dms = re.search(
        r'(\d{1,3})[°\s:](\d{1,2})[\'°\s:]+(\d+\.?\d*)["\s]*([' + hemi_chars + r'])',
        line, re.IGNORECASE,
    )
    if dms:
        val = int(dms.group(1)) + int(dms.group(2)) / 60.0 + float(dms.group(3)) / 3600.0
        return val, dms.group(4).upper()

    # Decimal with optional direction suffix.
    # Lookbehind (?<![a-zA-Z\d]) prevents matching digits embedded in type names like "Float64".
    # Lookahead (?=\s*[;",]|\s*$) requires a clean terminator (semicolon, quote, end of line).
    dec = re.search(
        r'(?<![a-zA-Z\d])(-?\d+\.?\d*)\s*([' + hemi_chars + r'])?(?=\s*[;",]|\s*$)',
        line, re.IGNORECASE,
    )
    if dec:
        try:
            return float(dec.group(1)), (dec.group(2).upper() if dec.group(2) else None)
        except ValueError:
            pass
    return None, None


def _parse_das_coordinates(das_text: str) -> tuple[float | None, float | None]:
    """
    Parse lat/lon from a .das file, handling multiple coordinate styles:
      - Signed decimal:          Float64 geospatial_lat_min -62.22
      - Unsigned + hemi suffix:  String geospatial_lat_min "62.22S"
      - Separate hemi attribute: String station_lat_hemisphere "S"
      - DMS notation:            String station_latitude "62 13 12 S"
    Also recognises ebas_station_latitude/longitude (preferred — already signed)
    and station_latitude / station_longitude as attribute aliases.
    ebas_measurement_latitude is intentionally excluded; it can be unsigned/wrong
    (e.g. King Sejong: measurement_lat=62.22 but station_lat=-62.22).
    """
    lat = lon = lat_hemi = lon_hemi = None

    for line in das_text.split("\n"):
        low = line.lower()

        if lat is None and re.search(r'\b(ebas_station_latitude|geospatial_lat_min|station_latitude)\b', low):
            val, hemi = _extract_coord_value(line, "NS")
            if val is not None:
                lat, lat_hemi = val, hemi

        if lon is None and re.search(r'\b(ebas_station_longitude|geospatial_lon_min|station_longitude)\b', low):
            val, hemi = _extract_coord_value(line, "EW")
            if val is not None:
                lon, lon_hemi = val, hemi

        if lat_hemi is None and re.search(r'\b\w*lat\w*hemisphere\b', low):
            m = re.search(r'"([NS])"', line, re.IGNORECASE)
            if m:
                lat_hemi = m.group(1).upper()

        if lon_hemi is None and re.search(r'\b\w*lon\w*hemisphere\b', low):
            m = re.search(r'"([EW])"', line, re.IGNORECASE)
            if m:
                lon_hemi = m.group(1).upper()

    # Apply hemisphere signs to unsigned values
    if lat is not None and lat_hemi == "S" and lat > 0:
        lat = -lat
    if lon is not None and lon_hemi == "W" and lon > 0:
        lon = -lon

    return lat, lon


async def _fetch_station_meta_from_das(
    client: httpx.AsyncClient,
    fi: _FileInfo,
    actris_dc_names: set[str] | None = None,
) -> dict | None:
    try:
        url = f"{OPENDAP_BASE}/{fi.name}.das"
        resp = await client.get(url, timeout=30.0)
        text = resp.text

        lat, lon = _parse_das_coordinates(text)
        if lat is None or lon is None:
            return None

        networks = ""
        name = None
        ebas_station_name = None
        for line in text.split("\n"):
            if ebas_station_name is None:
                m = re.search(r'String ebas_station_name "(.*?)"', line, re.IGNORECASE)
                if m:
                    ebas_station_name = m.group(1).strip()
            if name is None and "title" in line.lower():
                title_m = re.search(r'String title "(.*?)"', line, re.IGNORECASE)
                if title_m:
                    title = title_m.group(1)
                    m = re.search(r"\bat (.+?) \(" + re.escape(fi.station) + r"\)", title, re.IGNORECASE)
                    if m:
                        name = m.group(1).strip()
                    else:
                        m = re.search(r"\bat (.+?)(?:\s+using\s|\s*$)", title, re.IGNORECASE)
                        if m:
                            name = m.group(1).strip()
            if not networks:
                m = re.search(r'String project "(.*?)"', line, re.IGNORECASE)
                if m:
                    found = list(dict.fromkeys(filter(None, (
                        _match_network(p) for p in m.group(1).split(',')
                    ))))
                    if found:
                        networks = ','.join(found)

        # Augment with ACTRIS DC lookup: if station is an ACTRIS National Facility,
        # ensure ACTRIS appears in networks even if the EBAS project field omits it.
        if actris_dc_names:
            check = (ebas_station_name or name or "").lower()
            if check and check in actris_dc_names and "ACTRIS" not in networks:
                networks = ("ACTRIS," + networks).rstrip(",") if networks else "ACTRIS"

        return {
            "name":     ebas_station_name or name or fi.station,
            "lat":      lat,
            "lon":      lon,
            "country":  fi.station[:2].upper(),
            "networks": networks,
        }
    except Exception:
        return None


async def _fetch_file_mean(
    client: httpx.AsyncClient,
    fi: _FileInfo,
    nc_var: str,
    year: int,
    target_wl: float,
    sem: asyncio.Semaphore,
) -> float | None:
    async with sem:
        url = f"{OPENDAP_BASE}/{fi.name}"
        idx0, idx1 = _estimate_year_indices(fi, year)
        return await _compute_annual_mean(client, url, nc_var, idx0, idx1, target_wl)


def _estimate_year_indices(fi: _FileInfo, year: int) -> tuple[int, int]:
    effective_start = max(fi.start, date(year, 1, 1))
    effective_end   = min(fi.end,   date(year + 1, 1, 1))
    idx0 = (effective_start - fi.start).days * 24
    idx1 = (effective_end   - fi.start).days * 24 - 1
    return max(0, idx0), max(0, idx1)


async def _compute_annual_mean(
    client: httpx.AsyncClient,
    base_url: str,
    nc_var: str,
    idx0: int,
    idx1: int,
    target_wl: float = 0.0,
) -> float | None:
    if idx1 < idx0:
        return None

    try:
        wl_idx: int | None = None
        if target_wl > 0:
            try:
                wl_text = await _fetch_opendap_ascii(client, base_url, f"{nc_var}.Wavelength")
                wl_vals = _parse_first_section_floats(wl_text)
                if wl_vals.size > 0:
                    wl_idx = int(np.argmin(np.abs(wl_vals - target_wl)))
            except Exception:
                pass

        constraint = (
            f"{nc_var}[{wl_idx}][{idx0}:{idx1}]" if wl_idx is not None
            else f"{nc_var}[{idx0}:{idx1}]"
        )

        data_text = await _fetch_opendap_ascii(client, base_url, constraint)
        data = _parse_first_section_floats(data_text)

        if data.size == 0:
            return None

        valid = data[(data > 0) & np.isfinite(data)]
        return float(np.mean(valid)) if valid.size > 0 else None

    except Exception:
        return None
