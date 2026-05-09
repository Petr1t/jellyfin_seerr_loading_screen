# Roadmap

## v0.1 — Side-car daemon (current)

**Status:** in development.

- [x] Repo skeleton, GPL-2.0 LICENSE, README, ARCHITECTURE
- [x] `pyproject.toml`, package layout
- [ ] `arr_client.py`: Sonarr `/api/v3/queue` + Radarr `/api/v3/queue` polling
- [ ] `models.py`: `PendingItem` Pydantic model
- [ ] `poller.py`: background task with state cache
- [ ] `posters.py`: PIL-based overlay generation
- [ ] `tmdb_art.py`: poster-art fallback (iTunes Search API or TMDB)
- [ ] `jellyseerr_client.py`: optional, resolve request → user
- [ ] `api.py`: FastAPI app, `/api/coming-soon`, `/api/poster/<id>.png`, `/healthz`
- [ ] `config.py`: YAML config + env-var override
- [ ] `tests/`: unit tests for client, poster, api
- [ ] `scripts/install-daemon.sh`: interactive installer
- [ ] `jslsd.service`: systemd-user-unit template
- [ ] GitHub Actions CI: lint (ruff) + test (pytest) + build wheel

**Done = daemon runs as systemd-user-unit, returns valid JSON, generates working poster overlays. Verified on paradecentral against real Sonarr+Radarr+Jellyseerr instances.**

## v0.2 — Jellyfin C# plugin (next)

**Status:** skeleton only.

- [x] `plugin/` directory layout
- [ ] `Jellyfin.Plugin.SeerrLoadingScreen.csproj` targeting Jellyfin 10.11
- [ ] `Plugin.cs` extending `BasePlugin<PluginConfiguration>`
- [ ] `PluginConfiguration.cs` (daemon URL, poll interval, show_all_users)
- [ ] `Configuration/configPage.html` admin UI
- [ ] `Services/DaemonClient.cs`: HTTP client to jslsd
- [ ] `Services/VirtualItemProvider.cs`: creates virtual `BaseItem`s in a virtual library "📥 Coming Soon"
- [ ] `ScheduledTasks/RefreshTask.cs`: polls daemon every N seconds
- [ ] FileTransformation integration for live progress overlay in Web UI
- [ ] Build script: produces `.zip` + `meta.json` for Jellyfin's plugin manifest
- [ ] GitHub Actions: build .NET, upload artifact

**Done = plugin installs into Jellyfin 10.11 via manifest URL, virtual items appear in library view with poster + overlay, refreshes every 30s.**

## v0.3 — Webhooks + multi-user

**Status:** planned.

- [ ] `POST /webhook/sonarr` and `/webhook/radarr` endpoints in jslsd
- [ ] Sonarr/Radarr connect-config templates included in `scripts/`
- [ ] Push-based cache invalidation (sub-second update latency)
- [ ] Multi-user filter via Jellyseerr's `requestedBy.jellyfinUserId`
- [ ] Plugin: per-user filter toggle in Web UI

## v0.4 — Polish + Plugin Repo

**Status:** future.

- [ ] iOS/Android Jellyfin app screenshots in README (the baked-PNG approach should work natively there too)
- [ ] Submit to https://repo.jellyfin.org/ as community plugin
- [ ] Helm chart for Kubernetes deployments
- [ ] Docker Compose example with full Arr stack
- [ ] Proper `manifest.intro-skipper.workers.dev` style hosted manifest

## Non-goals

- ❌ Replacing Jellyseerr. We display its requests, we don't reimplement them.
- ❌ Replacing Sonarr/Radarr. We're a thin layer on top of their queue APIs.
- ❌ Showing recommendations (use Jellynext for that — it's the recommended pattern).
- ❌ Becoming a download manager. We display state, we don't manage it.
