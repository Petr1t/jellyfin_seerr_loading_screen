"""Background poller: fetches Sonarr/Radarr queues, normalises to PendingItem,
generates posters, holds the canonical in-memory cache.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any

import httpx

from .arr_client import QueueRecord, RadarrClient, SonarrClient
from .config import Config
from .jellyseerr_client import JellyseerrClient
from .models import PendingItem
from .posters import PosterGenerator

log = logging.getLogger(__name__)


class Poller:
    """Single background task. Holds the canonical state cache."""

    def __init__(self, config: Config) -> None:
        self.config = config
        self._cache: dict[str, PendingItem] = {}
        self._completed_at: dict[str, datetime] = {}
        self._failed_at: dict[str, datetime] = {}
        self.last_poll: datetime | None = None

        self._http = httpx.AsyncClient(timeout=15.0)
        self._sonarr = (
            SonarrClient(config.sonarr, client=self._http) if config.sonarr else None
        )
        self._radarr = (
            RadarrClient(config.radarr, client=self._http) if config.radarr else None
        )
        self._seerr = (
            JellyseerrClient(config.jellyseerr, client=self._http)
            if config.jellyseerr
            else None
        )
        self._posters = PosterGenerator(
            cache_dir=config.poster_cache_dir, size=config.poster_size, client=self._http
        )

        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    @property
    def items(self) -> list[PendingItem]:
        return list(self._cache.values())

    def get_poster_path(self, item_id: str) -> str | None:
        item = self._cache.get(item_id)
        if not item:
            return None
        return self._poster_path_for(item)

    def _poster_path_for(self, item: PendingItem) -> str:
        # Reconstruct the path the PosterGenerator wrote to.
        bucket = item.progress_bucket
        from .posters import _safe_id  # noqa: PLC0415 — internal helper, lazy import

        cache_key = f"{_safe_id(item.id)}__p{bucket:03d}__{item.status}.png"
        return str((self.config.poster_cache_dir / cache_key).absolute())

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="jslsd-poller")
            log.info("Poller started, interval=%ss", self.config.poll_interval_seconds)

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            await self._task
            self._task = None
        await self._http.aclose()

    async def _run(self) -> None:
        # First poll immediately, then on interval
        while not self._stop.is_set():
            try:
                await self._poll_once()
            except Exception:  # noqa: BLE001 — daemon must keep running
                log.exception("Poll cycle failed")
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self.config.poll_interval_seconds
                )
            except TimeoutError:
                continue

    async def _poll_once(self) -> None:
        """One polling cycle: fetch queues, build PendingItems, regenerate posters."""
        records: list[QueueRecord] = []
        if self._sonarr:
            try:
                records.extend(await self._sonarr.queue())
            except httpx.HTTPError as e:
                log.warning("Sonarr poll failed: %s", e)
        if self._radarr:
            try:
                records.extend(await self._radarr.queue())
            except httpx.HTTPError as e:
                log.warning("Radarr poll failed: %s", e)

        seen_ids: set[str] = set()

        for record in records:
            item = await self._normalise(record)
            if item is None:
                continue
            seen_ids.add(item.id)
            self._cache[item.id] = item

            if item.status == "completed":
                self._completed_at.setdefault(item.id, datetime.now().astimezone())
            elif item.status == "failed":
                self._failed_at.setdefault(item.id, datetime.now().astimezone())

            try:
                await self._posters.get_or_generate(
                    item_id=item.id,
                    progress_percent=item.progress_percent,
                    eta_seconds=item.eta_seconds,
                    status=item.status,
                    art_url=self._art_url_for_record(record),
                    title=item.title,
                )
            except Exception:  # noqa: BLE001 — poster failure is non-fatal
                log.exception("Poster generation failed for %s", item.id)

        # Evict items that disappeared from queue after retention window
        self._evict_stale(seen_ids)

        self.last_poll = datetime.now().astimezone()
        log.debug("Poll complete: %d items in cache", len(self._cache))

    async def _normalise(self, record: QueueRecord) -> PendingItem | None:
        media = record.media or {}
        item_id = f"{record.source}-{record.queue_id}"

        if record.source == "sonarr":
            episode_info = self._sonarr_episode_info(record)
            title = self._sonarr_title(media, episode_info)
            requester = await self._lookup_requester(media.get("tmdbId"), "tv")
            return PendingItem(
                id=item_id,
                source="sonarr",
                type="tv",
                title=title,
                series_title=media.get("title"),
                season=episode_info.get("season"),
                episode=episode_info.get("episode"),
                tmdb_id=media.get("tmdbId"),
                tvdb_id=media.get("tvdbId"),
                imdb_id=media.get("imdbId"),
                size_total_bytes=record.raw.get("size") or 0,
                size_left_bytes=record.raw.get("sizeleft") or 0,
                progress_percent=record.progress_percent,
                eta_seconds=record.eta_seconds,
                download_client=record.raw.get("downloadClient", "") or "",
                status=record.status,
                requested_by=requester,
                poster_url=f"/api/poster/{item_id}.png",
            )

        if record.source == "radarr":
            requester = await self._lookup_requester(media.get("tmdbId"), "movie")
            return PendingItem(
                id=item_id,
                source="radarr",
                type="movie",
                title=media.get("title", "Unknown"),
                tmdb_id=media.get("tmdbId"),
                imdb_id=media.get("imdbId"),
                size_total_bytes=record.raw.get("size") or 0,
                size_left_bytes=record.raw.get("sizeleft") or 0,
                progress_percent=record.progress_percent,
                eta_seconds=record.eta_seconds,
                download_client=record.raw.get("downloadClient", "") or "",
                status=record.status,
                requested_by=requester,
                poster_url=f"/api/poster/{item_id}.png",
            )

        return None

    @staticmethod
    def _sonarr_episode_info(record: QueueRecord) -> dict[str, Any]:
        episode = record.raw.get("episode") or {}
        return {
            "season": episode.get("seasonNumber"),
            "episode": episode.get("episodeNumber"),
            "episode_title": episode.get("title"),
        }

    @staticmethod
    def _sonarr_title(media: dict[str, Any], episode_info: dict[str, Any]) -> str:
        series = media.get("title") or "Unknown Series"
        if episode_info.get("season") is not None and episode_info.get("episode") is not None:
            return f"{series} — S{episode_info['season']:02d}E{episode_info['episode']:02d}"
        return series

    def _art_url_for_record(self, record: QueueRecord) -> str | None:
        media = record.media or {}
        images = media.get("images", [])
        for img in images:
            if img.get("coverType") == "poster":
                return img.get("remoteUrl") or img.get("url")
        return None

    async def _lookup_requester(
        self, tmdb_id: int | None, media_type: str
    ) -> str | None:
        if not self._seerr or not tmdb_id:
            return None
        req = await self._seerr.find_request(tmdb_id, media_type)
        if not req:
            return None
        user = req.get("requestedBy") or {}
        return user.get("displayName") or user.get("username") or user.get("email")

    def _evict_stale(self, seen_ids: set[str]) -> None:
        """Remove items that vanished from the queue past their retention window."""
        now = datetime.now().astimezone()
        completed_keep = timedelta(seconds=self.config.completed_retention_seconds)
        failed_keep = timedelta(seconds=self.config.failed_retention_seconds)

        to_remove: list[str] = []
        for item_id, item in self._cache.items():
            if item_id in seen_ids:
                continue
            if item.status == "completed":
                seen_at = self._completed_at.get(item_id, now)
                if now - seen_at > completed_keep:
                    to_remove.append(item_id)
            elif item.status == "failed":
                seen_at = self._failed_at.get(item_id, now)
                if now - seen_at > failed_keep:
                    to_remove.append(item_id)
            else:
                # Item gone from queue without completion → drop immediately
                to_remove.append(item_id)

        for item_id in to_remove:
            self._cache.pop(item_id, None)
            self._completed_at.pop(item_id, None)
            self._failed_at.pop(item_id, None)

    async def health(self) -> dict[str, Any]:
        sonarr_ok = await self._sonarr.health() if self._sonarr else True
        radarr_ok = await self._radarr.health() if self._radarr else True
        seerr_ok = await self._seerr.health() if self._seerr else None
        return {
            "status": "ok" if (sonarr_ok and radarr_ok) else "degraded",
            "sonarr_reachable": sonarr_ok,
            "radarr_reachable": radarr_ok,
            "jellyseerr_reachable": seerr_ok,
            "items_in_cache": len(self._cache),
            "last_poll": self.last_poll.isoformat() if self.last_poll else None,
        }
