"""Three-item demo set for --demo mode UI preview."""

from __future__ import annotations

from .models import PendingItem

DEMO_ITEMS: list[PendingItem] = [
    PendingItem(
        id="demo-tv-severance",
        source="sonarr",
        type="tv",
        title="Severance — S02E09",
        series_title="Severance",
        season=2,
        episode=9,
        tmdb_id=95396,
        size_total_bytes=3_500_000_000,
        size_left_bytes=1_155_000_000,
        progress_percent=67.0,
        eta_seconds=14 * 60,
        download_client="qbittorrent",
        status="downloading",
        requested_by="pet",
        poster_url="/api/poster/demo-tv-severance.png",
    ),
    PendingItem(
        id="demo-movie-dune2",
        source="radarr",
        type="movie",
        title="Dune: Part Two",
        tmdb_id=693134,
        size_total_bytes=8_100_000_000,
        size_left_bytes=4_050_000_000,
        progress_percent=50.0,
        eta_seconds=48 * 60,
        download_client="qbittorrent",
        status="downloading",
        requested_by="pet",
        poster_url="/api/poster/demo-movie-dune2.png",
    ),
    PendingItem(
        id="demo-tv-andor",
        source="sonarr",
        type="tv",
        title="Andor — S02E07",
        series_title="Andor",
        season=2,
        episode=7,
        size_total_bytes=4_200_000_000,
        size_left_bytes=4_200_000_000,
        progress_percent=0.0,
        eta_seconds=None,
        download_client="qbittorrent",
        status="queued",
        requested_by="pet",
        poster_url="/api/poster/demo-tv-andor.png",
    ),
]
