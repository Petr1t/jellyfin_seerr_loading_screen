"""Async clients for Sonarr and Radarr REST APIs."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from .config import ArrConfig

log = logging.getLogger(__name__)

# Sonarr/Radarr "timeleft" format: optionally days dot-separated, then HH:MM:SS
_TIMELEFT_RE = re.compile(r"^(?:(\d+)\.)?(\d+):(\d+):(\d+)$")


@dataclass
class QueueRecord:
    """One queue item from Sonarr/Radarr, plus optional series/movie detail."""

    queue_id: int
    source: str
    raw: dict[str, Any]
    media: dict[str, Any] | None = None

    @property
    def progress_percent(self) -> float:
        size = self.raw.get("size") or 0
        size_left = self.raw.get("sizeleft") or 0
        if size <= 0:
            return 0.0
        return round((1 - size_left / size) * 100, 1)

    @property
    def status(self) -> str:
        st = (self.raw.get("status") or "").lower()
        return {
            "completed": "completed",
            "imported": "completed",
            "paused": "paused",
            "failed": "failed",
            "warning": "failed",
            "downloading": "downloading",
        }.get(st, "queued")

    @property
    def eta_seconds(self) -> int | None:
        m = _TIMELEFT_RE.match(self.raw.get("timeleft") or "")
        if not m:
            return None
        d, h, mn, s = (int(g) if g else 0 for g in m.groups())
        return d * 86400 + h * 3600 + mn * 60 + s


class ArrClient:
    """Shared Sonarr/Radarr base. Subclasses override `_fetch_media`."""

    source_name: str = ""

    def __init__(self, config: ArrConfig, client: httpx.AsyncClient) -> None:
        self.base_url = str(config.url).rstrip("/")
        self.api_key = config.api_key
        self._client = client

    async def health(self) -> bool:
        try:
            r = await self._get("/api/v3/system/status")
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    async def queue(self) -> list[QueueRecord]:
        try:
            r = await self._get(
                "/api/v3/queue",
                params={
                    "pageSize": 200,
                    "includeUnknownMovieItems": "false",
                    "includeMovie": "true",
                },
            )
            r.raise_for_status()
            records = r.json().get("records", [])
        except (httpx.HTTPError, ValueError) as e:
            log.warning("%s queue fetch failed: %s", self.source_name, e)
            return []
        out: list[QueueRecord] = []
        for raw in records:
            media = await self._fetch_media(raw)
            out.append(
                QueueRecord(
                    queue_id=raw["id"], source=self.source_name, raw=raw, media=media
                )
            )
        return out

    async def _fetch_media(self, queue_record: dict[str, Any]) -> dict[str, Any] | None:
        return None

    async def _get(self, path: str, **kwargs: Any) -> httpx.Response:
        return await self._client.get(
            f"{self.base_url}{path}",
            headers={"X-Api-Key": self.api_key, "Accept": "application/json"},
            **kwargs,
        )


class SonarrClient(ArrClient):
    source_name = "sonarr"

    async def _fetch_media(self, queue_record: dict[str, Any]) -> dict[str, Any] | None:
        series_id = queue_record.get("seriesId")
        if not series_id:
            return None
        try:
            r = await self._get(f"/api/v3/series/{series_id}")
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as e:
            log.warning("Failed to fetch series %s: %s", series_id, e)
            return None


class RadarrClient(ArrClient):
    source_name = "radarr"

    async def _fetch_media(self, queue_record: dict[str, Any]) -> dict[str, Any] | None:
        if "movie" in queue_record and queue_record["movie"]:
            return queue_record["movie"]
        movie_id = queue_record.get("movieId")
        if not movie_id:
            return None
        try:
            r = await self._get(f"/api/v3/movie/{movie_id}")
            r.raise_for_status()
            return r.json()
        except httpx.HTTPError as e:
            log.warning("Failed to fetch movie %s: %s", movie_id, e)
            return None
