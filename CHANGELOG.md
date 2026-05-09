# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Plugin (v0.2 milestone — in progress)
- Skeleton .NET 8 project compiles against `Jellyfin.Controller` 10.11.
- `Plugin.cs` extending `BasePlugin<PluginConfiguration>` with stable GUID `4f2c0e3a-9b4d-4f7c-9a31-2d6e8f1b5c0a`.
- Configuration page (HTML + JS) for daemon URL / refresh interval / multi-user toggle.
- `DaemonClient.cs` HTTP wrapper for jslsd's `/api/coming-soon`.
- `RefreshTask.cs` periodic task scaffold (logs queue today, syncs to virtual library next).
- `build-zip.sh` produces a Jellyfin-installable `.zip` + `meta.json`.

## [0.1.0] — Daemon (jslsd) — 2026-05-09

### Added
- Side-car Python daemon polling Sonarr's and Radarr's `/api/v3/queue` endpoints.
- Optional Jellyseerr enrichment to attach the requesting user.
- `PendingItem` Pydantic model with stable lifecycle (queued → downloading → completed/failed → eviction).
- PIL-based poster overlay generation with progress bar, status badge, and ETA.
- FastAPI HTTP API: `GET /api/coming-soon`, `GET /api/poster/{id}.png`, `GET /healthz`.
- YAML config + `JSLSD_*` env-var overrides.
- systemd-user-unit + interactive `install-daemon.sh`.
- 15 unit tests (arr_client, posters, config) — all passing.
- Verified against real Sonarr 4.0.17 + Radarr on paradecentral.

[Unreleased]: https://github.com/Petr1t/jellyfin_seerr_loading_screen/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/Petr1t/jellyfin_seerr_loading_screen/releases/tag/v0.1.0
