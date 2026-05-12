"""Optional Jellyseerr enrichment: tmdb_id + media_type → requesting user."""

from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from .config import JellyseerrConfig

log = logging.getLogger(__name__)

_NEGATIVE_TTL_SECONDS = 1800  # 30 min — don't re-query missing requesters every cycle


class JellyseerrClient:
    def __init__(self, config: JellyseerrConfig, client: httpx.AsyncClient) -> None:
        self.base_url = str(config.url).rstrip("/")
        self.api_key = config.api_key
        self._client = client
        self._cache: dict[tuple[int, str], dict[str, Any]] = {}
        self._negative_cache: dict[tuple[int, str], float] = {}

    async def health(self) -> bool:
        try:
            r = await self._get("/api/v1/status")
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def find_request(
        self, tmdb_id: int | None, media_type: str
    ) -> dict[str, Any] | None:
        if not tmdb_id:
            return None

        key = (tmdb_id, media_type)
        if key in self._cache:
            return self._cache[key]
        if (expires := self._negative_cache.get(key)) and expires > time.monotonic():
            return None

        try:
            r = await self._get(
                "/api/v1/request",
                params={"take": 100, "skip": 0, "filter": "all"},
            )
            r.raise_for_status()
            for req in r.json().get("results", []):
                m = req.get("media") or {}
                if m.get("tmdbId") == tmdb_id and m.get("mediaType") == media_type:
                    self._cache[key] = req
                    return req
        except (httpx.HTTPError, ValueError) as e:
            log.warning("Jellyseerr lookup failed for tmdb=%s: %s", tmdb_id, e)
            return None

        self._negative_cache[key] = time.monotonic() + _NEGATIVE_TTL_SECONDS
        return None

    async def _get(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self._client.get(
            f"{self.base_url}{path}",
            headers={"X-Api-Key": self.api_key, "Accept": "application/json"},
            **kwargs,
        )
