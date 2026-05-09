"""Pydantic models for jslsd's public API."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class PendingItem(BaseModel):
    """A pending download surfaced from Sonarr or Radarr.

    Cache lifecycle:
    - status='queued'/'downloading' → kept while present in source queue
    - status='completed' → kept for 5 min (so users see "just finished")
    - status='failed' → kept for 1 hour (retry option)
    """

    id: str = Field(..., description="Stable ID: f'{source}-{queue_id}', e.g. 'sonarr-12345'")
    source: Literal["sonarr", "radarr"]
    type: Literal["movie", "tv"]

    title: str = Field(..., description="Canonical human-readable title")
    series_title: str | None = Field(None, description="For TV episodes, the series name")
    season: int | None = None
    episode: int | None = None

    tmdb_id: int | None = None
    tvdb_id: int | None = None
    imdb_id: str | None = None

    size_total_bytes: int = 0
    size_left_bytes: int = 0
    progress_percent: float = 0.0
    eta_seconds: int | None = None

    download_client: str = Field("", description="qbittorrent, deluge, sabnzbd, ...")
    status: Literal["queued", "downloading", "completed", "failed", "paused"] = "queued"

    requested_by: str | None = Field(
        None, description="Jellyseerr username if available"
    )
    requested_by_jellyfin_id: str | None = None

    poster_url: str = Field(
        ..., description="Path on jslsd to the overlay PNG, e.g. /api/poster/sonarr-12345.png"
    )

    last_updated: datetime = Field(default_factory=lambda: datetime.now().astimezone())

    @property
    def progress_bucket(self) -> int:
        """Progress rounded down to nearest 5%, used for poster cache key."""
        return int(self.progress_percent // 5) * 5


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"] = "ok"
    sonarr_reachable: bool = True
    radarr_reachable: bool = True
    jellyseerr_reachable: bool | None = None
    items_in_cache: int = 0
    last_poll: datetime | None = None
