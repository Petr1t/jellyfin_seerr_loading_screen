# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.3] — 2026-05-16

### Plugin

#### Added
- Clickable detail view: tapping a channel item now opens a tile grid (Status / Fortschritt / ETA / Größe / Download via / Angefragt von) instead of a blank folder.
- Action tile **Blocklisten + neu suchen** appears in detail view for items stuck in `paused`/`failed`. Click → daemon dispatches `DELETE /queue/{id}?removeFromClient=true&blocklist=true` against every underlying Sonarr/Radarr queue record and Sonarr re-searches on the next cycle.
- Versioned channel-item Ids (`{base}__v__p{bucket}__{status}`) so Jellyfin's image cache invalidates when state changes. Fixes posters staying at the first cached % forever.

#### Changed
- Episode-level titles in aggregated season items: `Series — S01E05` (1 episode), `Series — S01 · E01+E04+E05` (2–4), `Series — S01 · E01–E13 (13 Folgen)` (5+).
- Sonarr/Radarr `warning` status (stalled torrents, import-blocked) now maps to `paused` (yellow) instead of `failed` (red) — the download isn't given up on, it just needs attention.

### Daemon

#### Added
- `POST /api/items/{item_id}/blocklist` — fans the action out across every queue row the item aggregates.
- `GET /api/poster/{item_id}/tile/{kind}.png` — per-tile info renderer (status/progress/eta/size/client/requester/blocklist).
- `Poller._queue_ids_by_item` mapping so action endpoints can dispatch without re-fetching the queue.
- `includeEpisode=true` on Sonarr queue fetch + `PendingItem.episodes: list[int]`.

#### Changed
- Default poster size 400×600 → **600×900**, ETA 18pt → **44pt**, percent 22pt → **72pt**. Readable at thumbnail size.
- Subtitle on aggregated TV items shows the explicit episode list when small enough, falls back to a count for full-season packs.

## [0.2.0] — 2026-05-09

### Plugin (.NET 9, Jellyfin 10.11)

#### Added
- `Plugin.cs` extending `BasePlugin<PluginConfiguration>` with stable GUID `4f2c0e3a-9b4d-4f7c-9a31-2d6e8f1b5c0a`.
- `SeerrLoadingScreenChannel` implementing `IChannel` — Jellyfin's stable plugin pattern for browseable virtual content.
- `DaemonClient` typed-HttpClient for the jslsd API.
- `PluginConfiguration` with daemon URL / refresh interval / multi-user toggle / virtual library name / hide-completed.
- HTML configuration page wired into Jellyfin admin UI.
- Build script (`build-zip.sh`) producing a Jellyfin-installable `.zip`.
- Hosted manifest at `https://raw.githubusercontent.com/Petr1t/jellyfin_seerr_loading_screen/main/manifest.json` for one-click install via Jellyfin admin → Plugins → Repositories.

#### Why IChannel
- Stable across Jellyfin versions (BaseItem injection is internal API and changes per release).
- Native iOS / Android / tvOS support via baked PNG posters.
- Cache invalidation via `IHasCacheKey` is built-in — the channel re-fetches when the queue changes.

### Daemon (`jslsd`)

#### Added
- Side-car Python daemon polling Sonarr + Radarr `/api/v3/queue`.
- Optional Jellyseerr enrichment to attach the requesting user.
- `PendingItem` Pydantic model with stable lifecycle (queued → downloading → completed/failed → eviction).
- PIL-based poster overlay with progress bar, status badge, ETA.
- FastAPI HTTP API: `GET /api/coming-soon`, `GET /api/poster/{id}.png`, `GET /healthz`.
- YAML config + `JSLSD_*` env-var overrides.
- systemd-user-unit + interactive `install-daemon.sh`.
- 15 unit tests (arr_client, posters, config) — all passing.
- Verified against real Sonarr 4.0.17 + Radarr.

### CI

- Python workflow: lint (ruff) + test (pytest) + build wheel on Python 3.11 + 3.12.
- .NET workflow: build + package against Jellyfin.Controller 10.11 / .NET 9.

[0.2.0]: https://github.com/Petr1t/jellyfin_seerr_loading_screen/releases/tag/v0.2.0
