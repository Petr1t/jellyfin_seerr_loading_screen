"""Optional Jellyseerr client to enrich pending items with the requesting user.

Jellyseerr exposes /api/v1/request which links a tmdb_id+media_type to the
Jellyfin user who made the request. We use this for multi-user filtering.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from .config import JellyseerrConfig

log = logging.getLogger(__name__)


class JellyseerrClient:
    def __init__(
        self, config: JellyseerrConfig, client: httpx.AsyncClient | None = None
    ) -> None:
        self.base_url = str(config.url).rstrip("/")
        self.api_key = config.api_key
        self._client = client or httpx.AsyncClient(timeout=10.0)
        self._owns_client = client is None
        self._cache: dict[tuple[int, str], dict[str, Any]] = {}

    async def __aenter__(self) -> JellyseerrClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        return {"X-Api-Key": self.api_key, "Accept": "application/json"}

    async def health(self) -> bool:
        try:
            r = await self._client.get(
                f"{self.base_url}/api/v1/status", headers=self._headers()
            )
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def find_request(
        self, tmdb_id: int | None, media_type: str
    ) -> dict[str, Any] | None:
        """Find the Jellyseerr request matching this tmdb_id + media_type.

        Returns the raw request dict including `requestedBy` user info, or None.
        Cached in-memory for the daemon's lifetime — Jellyseerr requests don't
        change identity once made.
        """
        if not tmdb_id:
            return None

        cache_key = (tmdb_id, media_type)
        if cache_key in self._cache:
            return self._cache[cache_key]

        # Jellyseerr's /api/v1/request supports filtering. We page through.
        try:
            r = await self._client.get(
                f"{self.base_url}/api/v1/request",
                headers=self._headers(),
                params={"take": 100, "skip": 0, "filter": "all"},
            )
            r.raise_for_status()
            for req in r.json().get("results", []):
                m = req.get("media") or {}
                if m.get("tmdbId") == tmdb_id and m.get("mediaType") == media_type:
                    self._cache[cache_key] = req
                    return req
        except httpx.HTTPError as e:
            log.warning("Jellyseerr lookup failed for tmdb=%s: %s", tmdb_id, e)

        return None
