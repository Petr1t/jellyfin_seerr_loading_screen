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
        self._details_cache: dict[tuple[int, str], dict[str, Any]] = {}

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

    async def list_requests(self) -> list[dict[str, Any]]:
        """All requests Jellyseerr knows about. Raises on transport/parse errors."""
        r = await self._get(
            "/api/v1/request",
            params={"take": 500, "skip": 0, "filter": "all"},
        )
        r.raise_for_status()
        return r.json().get("results", [])

    async def media_details(self, tmdb_id: int, media_type: str) -> dict[str, Any]:
        """Title + poster URL for a tmdb id. Requests carry neither.

        Cached per (tmdb_id, media_type) — details are static enough that one
        lookup per daemon lifetime is plenty.
        """
        key = (tmdb_id, media_type)
        if key in self._details_cache:
            return self._details_cache[key]

        kind = "movie" if media_type == "movie" else "tv"
        details: dict[str, Any] = {"title": None, "art_url": None}
        try:
            r = await self._get(f"/api/v1/{kind}/{tmdb_id}")
            r.raise_for_status()
            data = r.json()
            details["title"] = data.get("title") or data.get("name")
            if poster := data.get("posterPath"):
                details["art_url"] = (
                    f"https://image.tmdb.org/t/p/w600_and_h900_bestv2{poster}"
                )
        except (httpx.HTTPError, ValueError) as e:
            log.warning("Jellyseerr details lookup failed for tmdb=%s: %s", tmdb_id, e)

        self._details_cache[key] = details
        return details

    async def _get(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self._client.get(
            f"{self.base_url}{path}",
            headers={"X-Api-Key": self.api_key, "Accept": "application/json"},
            **kwargs,
        )
