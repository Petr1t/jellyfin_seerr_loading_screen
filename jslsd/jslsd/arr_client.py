"""Async clients for Sonarr and Radarr REST APIs.

We talk to /api/v3/queue, /api/v3/series (Sonarr), /api/v3/movie (Radarr) to
enrich queue records with title and poster art.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

import httpx

from .config import ArrConfig

log = logging.getLogger(__name__)


@dataclass
class QueueRecord:
    """Raw queue record, source-specific fields kept for downstream normalisation."""

    queue_id: int
    source: str  # "sonarr" or "radarr"
    raw: dict[str, Any]
    media: dict[str, Any] | None = None  # Series (Sonarr) or Movie (Radarr) detail

    @property
    def progress_percent(self) -> float:
        size = self.raw.get("size") or 0
        size_left = self.raw.get("sizeleft") or 0
        if size == 0:
            return 0.0
        return round((1 - size_left / size) * 100, 1)

    @property
    def status(self) -> str:
        # Sonarr/Radarr status enum: queued, paused, downloading, completed, failed, warning
        st = (self.raw.get("status") or "").lower()
        if st in {"completed", "imported"}:
            return "completed"
        if st in {"paused"}:
            return "paused"
        if st in {"failed", "warning"}:
            return "failed"
        if st in {"downloading"}:
            return "downloading"
        return "queued"

    @property
    def eta_seconds(self) -> int | None:
        time_left = self.raw.get("timeleft")
        # Format: "00:14:23" or "1.00:14:23"
        if not time_left:
            return None
        parts = time_left.split(":")
        days = 0
        try:
            if "." in parts[0]:
                d, h = parts[0].split(".")
                days = int(d)
                hours = int(h)
            else:
                hours = int(parts[0])
            minutes = int(parts[1])
            seconds = int(parts[2])
        except (ValueError, IndexError):
            return None
        return days * 86400 + hours * 3600 + minutes * 60 + seconds


class ArrClient:
    """Generic Sonarr/Radarr client. Subclass overrides media-detail endpoint."""

    media_endpoint: str = ""  # "series" or "movie"
    source_name: str = ""

    def __init__(self, config: ArrConfig, client: httpx.AsyncClient | None = None) -> None:
        self.base_url = str(config.url).rstrip("/")
        self.api_key = config.api_key
        self._client = client or httpx.AsyncClient(timeout=10.0)
        self._owns_client = client is None

    async def __aenter__(self) -> ArrClient:
        return self

    async def __aexit__(self, *_: object) -> None:
        if self._owns_client:
            await self._client.aclose()

    def _headers(self) -> dict[str, str]:
        return {"X-Api-Key": self.api_key, "Accept": "application/json"}

    async def health(self) -> bool:
        try:
            r = await self._client.get(
                f"{self.base_url}/api/v3/system/status", headers=self._headers()
            )
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def queue(self) -> list[QueueRecord]:
        """Fetch the queue and enrich each record with media (series/movie) detail."""
        url = f"{self.base_url}/api/v3/queue"
        r = await self._client.get(
            url,
            headers=self._headers(),
            params={"pageSize": 200, "includeUnknownMovieItems": "false", "includeMovie": "true"},
        )
        r.raise_for_status()
        records = r.json().get("records", [])

        out: list[QueueRecord] = []
        for raw in records:
            media = await self._fetch_media(raw)
            out.append(
                QueueRecord(
                    queue_id=raw["id"],
                    source=self.source_name,
                    raw=raw,
                    media=media,
                )
            )
        return out

    async def _fetch_media(self, queue_record: dict[str, Any]) -> dict[str, Any] | None:
        """Override in subclass: fetch the series/movie detail for a queue item."""
        return None


class SonarrClient(ArrClient):
    media_endpoint = "series"
    source_name = "sonarr"

    async def _fetch_media(self, queue_record: dict[str, Any]) -> dict[str, Any] | None:
        series_id = queue_record.get("seriesId")
        if not series_id:
            return None
        url = f"{self.base_url}/api/v3/series/{series_id}"
        try:
            r = await self._client.get(url, headers=self._headers())
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as e:
            log.warning("Failed to fetch series %s: %s", series_id, e)
            return None


class RadarrClient(ArrClient):
    media_endpoint = "movie"
    source_name = "radarr"

    async def _fetch_media(self, queue_record: dict[str, Any]) -> dict[str, Any] | None:
        # Radarr's queue includes the movie inline if includeMovie=true was passed.
        if "movie" in queue_record and queue_record["movie"]:
            return queue_record["movie"]

        movie_id = queue_record.get("movieId")
        if not movie_id:
            return None
        url = f"{self.base_url}/api/v3/movie/{movie_id}"
        try:
            r = await self._client.get(url, headers=self._headers())
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as e:
            log.warning("Failed to fetch movie %s: %s", movie_id, e)
            return None
