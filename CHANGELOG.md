# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
