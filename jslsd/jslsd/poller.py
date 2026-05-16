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
        # Each item is a (source, queue_id) tuple. Action endpoints use this
        # map to fan out a single user action across the underlying records —
        # one PendingItem may aggregate many queue rows (season packs etc.).
        self._queue_ids_by_item: dict[str, list[tuple[str, int]]] = {}
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
            accent_color=config.accent_color,
            surface_color=config.surface_color,
        )

        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    @property
    def items(self) -> list[PendingItem]:
        return list(self._cache.values())

    @property
    def items_by_id(self) -> dict[str, PendingItem]:
        return dict(self._cache)

    async def blocklist_item(self, item_id: str) -> dict[str, Any]:
        """Remove every queue record this item aggregates from its Arr,
        blocklisting the release so a different one gets grabbed next.
        Returns a summary so the API can surface partial successes."""
        targets = self._queue_ids_by_item.get(item_id, [])
        if not targets:
            return {"ok": False, "reason": "item not in cache", "succeeded": 0, "failed": 0}
        succeeded, failed, errors = 0, 0, []
        for source, queue_id in targets:
            client = self._sonarr if source == "sonarr" else self._radarr
            if client is None:
                failed += 1
                errors.append(f"{source} client not configured")
                continue
            try:
                await client.blocklist_queue(queue_id)
                succeeded += 1
            except httpx.HTTPError as e:
                failed += 1
                errors.append(f"{source}#{queue_id}: {e}")
        # Drop from cache immediately so the UI doesn't continue to show
        # the just-blocklisted item before the next poll.
        if succeeded > 0:
            self._cache.pop(item_id, None)
            self._queue_ids_by_item.pop(item_id, None)
        return {"ok": failed == 0, "succeeded": succeeded, "failed": failed, "errors": errors}

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
        new_queue_map: dict[str, list[tuple[str, int]]] = {}
        for item, art_record, queue_records in await self._build_items(records):
            seen.add(item.id)
            self._cache[item.id] = item
            new_queue_map[item.id] = [(r.source, r.queue_id) for r in queue_records]
            await self._regenerate_poster(item, art_record)
        self._queue_ids_by_item = new_queue_map

        self._evict_stale(seen)
        self.last_poll = datetime.now().astimezone()
        log.debug("Poll complete: %d items in cache", len(self._cache))

    async def _build_items(
        self, records: list[QueueRecord]
    ) -> list[tuple[PendingItem, QueueRecord, list[QueueRecord]]]:
        """Movies stay 1:1, episodes get grouped per (series, season).

        Third tuple element is the full list of underlying queue records,
        used by action endpoints (e.g. blocklist) that must fan out across
        every record in a season aggregation.
        """
        out: list[tuple[PendingItem, QueueRecord, list[QueueRecord]]] = []

        for record in records:
            if record.source == "radarr":
                item = await self._normalise_movie(record)
                if item is not None:
                    out.append((item, record, [record]))

        # Group Sonarr records by (series_id, season). Records without a known
        # season fall back to a single "Sxx" bucket so they still surface.
        groups: dict[tuple[int, int | None], list[QueueRecord]] = {}
        for record in records:
            if record.source != "sonarr":
                continue
            series_id = record.raw.get("seriesId")
            if not series_id:
                continue
            season = record.raw.get("seasonNumber")
            groups.setdefault((series_id, season), []).append(record)

        for (series_id, season), group in groups.items():
            item = await self._aggregate_season(series_id, season, group)
            out.append((item, group[0], group))

        return out

    async def _normalise_movie(self, record: QueueRecord) -> PendingItem | None:
        media = record.media or {}
        item_id = f"radarr-{record.queue_id}"
        return PendingItem(
            id=item_id,
            source="radarr",
            type="movie",
            title=media.get("title", "Unknown Movie"),
            episode_count=1,
            size_total_bytes=record.raw.get("size") or 0,
            size_left_bytes=record.raw.get("sizeleft") or 0,
            progress_percent=record.progress_percent,
            eta_seconds=record.eta_seconds,
            download_client=record.raw.get("downloadClient", "") or "",
            status=record.status,
            tmdb_id=media.get("tmdbId"),
            imdb_id=media.get("imdbId"),
            requested_by=await self._lookup_requester(media.get("tmdbId"), "movie"),
            poster_url=f"/api/poster/{item_id}.png",
        )

    async def _aggregate_season(
        self,
        series_id: int,
        season: int | None,
        group: list[QueueRecord],
    ) -> PendingItem:
        rep = group[0]
        media = rep.media or {}
        series = media.get("title") or "Unknown Series"

        # A season pack shows up as one Sonarr queue record per episode but a
        # single downloadId on SAB/qBittorrent — and every record carries the
        # full pack size. Naively summing inflates the total N-fold.
        # Dedupe by downloadId; records without one are treated as standalone.
        by_download: dict[str, QueueRecord] = {}
        for r in group:
            key = r.raw.get("downloadId") or f"_solo_{r.queue_id}"
            by_download.setdefault(key, r)
        size_total = sum((r.raw.get("size") or 0) for r in by_download.values())
        size_left = sum((r.raw.get("sizeleft") or 0) for r in by_download.values())
        progress = (
            round((1 - size_left / size_total) * 100, 1) if size_total > 0 else 0.0
        )

        # Slowest individual ETA = whole-season ETA (it's the bottleneck).
        etas = [r.eta_seconds for r in group if r.eta_seconds is not None]
        eta = max(etas) if etas else None

        statuses = [r.status for r in group]
        if all(s == "completed" for s in statuses):
            status = "completed"
        elif any(s == "failed" for s in statuses):
            status = "failed"
        elif any(s == "downloading" for s in statuses):
            status = "downloading"
        elif any(s == "paused" for s in statuses):
            status = "paused"
        else:
            status = "queued"

        season_tag = f"S{season:02d}" if season is not None else "Sxx"
        item_id = f"sonarr-{series_id}-{season_tag}"
        n = len(group)

        # Sonarr exposes per-record episodeNumber via the includeEpisode flag.
        # Sorted + unique so multiple records for the same episode (rare but
        # possible across grab attempts) collapse cleanly.
        episodes = sorted({
            ep_num
            for r in group
            if (ep_num := (r.raw.get("episode") or {}).get("episodeNumber")) is not None
        })

        title = _format_season_title(series, season, episodes, n)
        first_episode = episodes[0] if len(episodes) == 1 else None

        return PendingItem(
            id=item_id,
            source="sonarr",
            type="tv",
            title=title,
            series_title=series,
            season=season,
            episode=first_episode,
            episode_count=n,
            episodes=episodes,
            tvdb_id=media.get("tvdbId"),
            tmdb_id=media.get("tmdbId"),
            imdb_id=media.get("imdbId"),
            size_total_bytes=size_total,
            size_left_bytes=size_left,
            progress_percent=progress,
            eta_seconds=eta,
            download_client=rep.raw.get("downloadClient", "") or "",
            status=status,
            requested_by=await self._lookup_requester(media.get("tmdbId"), "tv"),
            poster_url=f"/api/poster/{item_id}.png",
        )

    async def _regenerate_poster(self, item: PendingItem, record: QueueRecord) -> None:
        # Build a one-line subtitle. Show explicit episode list when small,
        # collapse to a count when long, so the poster stays readable.
        size_gb = item.size_total_bytes / 1024**3
        ep_list = _format_episode_list(item.episodes)
        if ep_list:
            subtitle = f"{ep_list}  ·  {size_gb:.1f} GB"
        elif size_gb >= 0.1:
            subtitle = f"{size_gb:.1f} GB"
        else:
            subtitle = None
        # Use just the series title (not the long aggregated title) as the headline.
        display_title = item.series_title or item.title
        if item.type == "tv" and item.season is not None:
            display_title = f"{display_title} · Staffel {item.season}"
        try:
            await self.posters.get_or_generate(
                item_id=item.id,
                progress_percent=item.progress_percent,
                eta_seconds=item.eta_seconds,
                status=item.status,
                art_url=_art_url(record),
                title=display_title,
                subtitle=subtitle,
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


def _format_episode_list(episodes: list[int]) -> str:
    """'E04' / 'E04+E05+E06' / 'E04–E10 (7 Folgen)' depending on count.

    The dense compact ranges keep the poster legible even for full-season packs."""
    if not episodes:
        return ""
    if len(episodes) == 1:
        return f"E{episodes[0]:02d}"
    if len(episodes) <= 4:
        return "+".join(f"E{e:02d}" for e in episodes)
    return f"E{episodes[0]:02d}–E{episodes[-1]:02d} ({len(episodes)} Folgen)"


def _format_season_title(
    series: str, season: int | None, episodes: list[int], total_count: int
) -> str:
    """'Series — S01E04' / 'Series — S01 · E04+E05' / 'Series — S01 · E01–E12 (12 Folgen)'."""
    if season is None:
        word = "Folge" if total_count == 1 else "Folgen"
        return f"{series} ({total_count} {word})"
    if len(episodes) == 1:
        return f"{series} — S{season:02d}E{episodes[0]:02d}"
    if episodes:
        return f"{series} — S{season:02d} · {_format_episode_list(episodes)}"
    word = "Folge" if total_count == 1 else "Folgen"
    return f"{series} — Staffel {season} ({total_count} {word})"
