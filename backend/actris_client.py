"""
ACTRIS metadata catalog client — facilities only.

Base URL: https://prod-actris-md2.nilu.no
Swagger:  https://prod-actris-md2.nilu.no/index.html

The /facilities/ endpoint returns station coordinates used to enrich EBAS data.
Measurement values come from THREDDS via ebas_thredds.py, not this API.
"""

import httpx
from datetime import datetime, timedelta
from typing import Any

ACTRIS_BASE = "https://prod-actris-md2.nilu.no"
_TTL = timedelta(hours=24)


class ActrisClient:
    """Thin client kept for backward-compat; EbasThreddsClient embeds its own facilities fetch."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None
        self._cache: dict[str, tuple[Any, datetime]] = {}

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            base_url=ACTRIS_BASE,
            timeout=30.0,
            headers={"Accept": "application/json"},
        )

    async def close(self) -> None:
        if self._client:
            await self._client.aclose()

    async def fetch_facilities(self) -> list[dict]:
        """
        Fetch all ACTRIS measurement facilities with coordinates.

        Response fields per item:
          identifier, name, lat, lon, alt (optional), country_code (optional)
        """
        if "facilities" in self._cache:
            data, ts = self._cache["facilities"]
            if datetime.now() - ts < _TTL:
                return data

        assert self._client
        resp = await self._client.get("/facilities/")
        resp.raise_for_status()
        data: list[dict] = resp.json()
        self._cache["facilities"] = (data, datetime.now())
        return data
