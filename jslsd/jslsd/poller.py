"""Background poller. Owns the HTTP client and the canonical state cache."""

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
from .posters import PosterGenerator, safe_filename_id

log = logging.getLogger(__name__)


class Poller:
    def __init__(self, config: Config) -> None:
        self.config = config
        self._cache: dict[str, PendingItem] = {}
        self._exited_at: dict[str, datetime] = {}
        self.last_poll: datetime | None = None
        self.consecutive_failures: int = 0
        self.last_poll_error: str | None = None

        self._http = httpx.AsyncClient(timeout=15.0)
        self._sonarr = SonarrClient(config.sonarr, self._http) if config.sonarr else None
        self._radarr = RadarrClient(config.radarr, self._http) if config.radarr else None
        self._seerr = (
            JellyseerrClient(config.jellyseerr, self._http) if config.jellyseerr else None
        )
        self.posters = PosterGenerator(
            cache_dir=config.poster_cache_dir,
            size=config.poster_size,
            client=self._http,
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
        cache_key = f"{safe_filename_id(item.id)}__p{item.progress_bucket:03d}__{item.status}.png"
        return str((self.config.poster_cache_dir / cache_key).absolute())

    def inject(self, item: PendingItem) -> None:
        """Externally add an item to the cache. Used by --demo mode."""
        self._cache[item.id] = item

    async def start(self) -> None:
        if self.config.demo_mode:
            log.info("Demo mode — poller idle, using injected cache items")
            return
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
        while not self._stop.is_set():
            try:
                await self.poll_once()
                self.consecutive_failures = 0
                self.last_poll_error = None
            except Exception as e:  # noqa: BLE001
                self.consecutive_failures += 1
                self.last_poll_error = f"{type(e).__name__}: {e}"
                log.exception("Poll cycle failed (consecutive=%d)", self.consecutive_failures)
            try:
                await asyncio.wait_for(
                    self._stop.wait(), timeout=self.config.poll_interval_seconds
                )
            except TimeoutError:
                continue

    async def poll_once(self) -> None:
        """One polling cycle: fetch queues, normalise, regenerate posters, evict."""
        records: list[QueueRecord] = []
        for client in (self._sonarr, self._radarr):
            if client is None:
                continue
            try:
                records.extend(await client.queue())
            except httpx.HTTPError as e:
                log.warning("%s poll failed: %s", client.source_name, e)

        seen: set[str] = set()
        for record in records:
            item = await self._normalise(record)
            if item is None:
                continue
            seen.add(item.id)
            self._cache[item.id] = item
            await self._regenerate_poster(item, record)

        self._evict_stale(seen)
        self.last_poll = datetime.now().astimezone()
        log.debug("Poll complete: %d items in cache", len(self._cache))

    async def _normalise(self, record: QueueRecord) -> PendingItem | None:
        media = record.media or {}
        item_id = f"{record.source}-{record.queue_id}"

        common = {
            "id": item_id,
            "size_total_bytes": record.raw.get("size") or 0,
            "size_left_bytes": record.raw.get("sizeleft") or 0,
            "progress_percent": record.progress_percent,
            "eta_seconds": record.eta_seconds,
            "download_client": record.raw.get("downloadClient", "") or "",
            "status": record.status,
            "tmdb_id": media.get("tmdbId"),
            "imdb_id": media.get("imdbId"),
            "poster_url": f"/api/poster/{item_id}.png",
        }

        if record.source == "sonarr":
            ep = record.raw.get("episode") or {}
            season, episode = ep.get("seasonNumber"), ep.get("episodeNumber")
            series = media.get("title") or "Unknown Series"
            title = (
                f"{series} — S{season:02d}E{episode:02d}"
                if season is not None and episode is not None
                else series
            )
            return PendingItem(
                source="sonarr",
                type="tv",
                title=title,
                series_title=media.get("title"),
                season=season,
                episode=episode,
                tvdb_id=media.get("tvdbId"),
                requested_by=await self._lookup_requester(media.get("tmdbId"), "tv"),
                **common,
            )

        if record.source == "radarr":
            return PendingItem(
                source="radarr",
                type="movie",
                title=media.get("title", "Unknown Movie"),
                requested_by=await self._lookup_requester(media.get("tmdbId"), "movie"),
                **common,
            )

        return None

    async def _regenerate_poster(self, item: PendingItem, record: QueueRecord) -> None:
        try:
            await self.posters.get_or_generate(
                item_id=item.id,
                progress_percent=item.progress_percent,
                eta_seconds=item.eta_seconds,
                status=item.status,
                art_url=_art_url(record),
                title=item.title,
            )
        except Exception:  # noqa: BLE001
            log.exception("Poster generation failed for %s", item.id)

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

    def _evict_stale(self, seen: set[str]) -> None:
        """Drop items missing from the latest queue past their retention window."""
        now = datetime.now().astimezone()
        retention = {
            "completed": timedelta(seconds=self.config.completed_retention_seconds),
            "failed": timedelta(seconds=self.config.failed_retention_seconds),
        }
        to_remove: list[str] = []

        for item_id, item in self._cache.items():
            if item_id in seen:
                self._exited_at.pop(item_id, None)
                continue
            keep_for = retention.get(item.status)
            if keep_for is None:
                to_remove.append(item_id)
                continue
            exited = self._exited_at.setdefault(item_id, now)
            if now - exited > keep_for:
                to_remove.append(item_id)

        for item_id in to_remove:
            self._cache.pop(item_id, None)
            self._exited_at.pop(item_id, None)

    async def health(self) -> dict[str, Any]:
        sonarr_ok = await self._sonarr.health() if self._sonarr else True
        radarr_ok = await self._radarr.health() if self._radarr else True
        seerr_ok = await self._seerr.health() if self._seerr else None
        healthy = sonarr_ok and radarr_ok and self.consecutive_failures < 3
        return {
            "status": "ok" if healthy else "degraded",
            "sonarr_reachable": sonarr_ok,
            "radarr_reachable": radarr_ok,
            "jellyseerr_reachable": seerr_ok,
            "items_in_cache": len(self._cache),
            "last_poll": self.last_poll.isoformat() if self.last_poll else None,
            "consecutive_failures": self.consecutive_failures,
            "last_poll_error": self.last_poll_error,
        }


def _art_url(record: QueueRecord) -> str | None:
    for img in (record.media or {}).get("images", []):
        if img.get("coverType") == "poster":
            return img.get("remoteUrl") or img.get("url")
    return None
