# Roadmap

## ✅ v0.2.0 — Released 2026-05-09

- [x] Python daemon: Sonarr + Radarr queue polling, poster overlay generation, FastAPI
- [x] systemd-user-unit installer
- [x] Jellyfin plugin implementing `IChannel`
- [x] Plugin admin UI for daemon URL + refresh interval + multi-user toggle
- [x] Hosted manifest at `https://raw.githubusercontent.com/Petr1t/jellyfin_seerr_loading_screen/main/manifest.json`
- [x] GitHub Release with attached plugin ZIP
- [x] CI green for both halves (Python 3.11/3.12 + .NET 9)
- [x] 15 unit tests passing for the daemon

**Verified end-to-end:** daemon runs as systemd-user-unit, returns JSON, generates working poster overlays. Plugin builds in CI against Jellyfin.Controller 10.11.

## 🟡 v0.3 — webhooks + multi-user fix (next)

- [ ] `POST /webhook/sonarr` and `/webhook/radarr` endpoints in `jslsd`
- [ ] Sonarr/Radarr "Connect" config templates included in `scripts/`
- [ ] Push-based cache invalidation (sub-second update latency vs current 30s poll)
- [ ] Multi-user filter via Jellyseerr's `requestedBy.jellyfinUserId` (currently filters by display-name, which is fragile)
- [ ] Plugin: per-user filter toggle in Web UI

## 🔵 v0.4 — polish + plugin-repo submission

- [ ] iOS / Android client compatibility testing — verify the baked progress poster renders on native apps
- [ ] Discord/Reddit announcement post in `/r/jellyfin` once tested
- [ ] Submit to https://repo.jellyfin.org/ as community plugin
- [ ] Helm chart for Kubernetes deployments
- [ ] Docker Compose example with full Arr stack
- [ ] Pause / Resume / Cancel buttons in the plugin UI (calls Sonarr/Radarr queue-edit endpoints)

## ⚪ Open questions / non-goals

- ❌ Replacing Jellyseerr. We display its requests, we don't reimplement them.
- ❌ Replacing Sonarr/Radarr. We're a thin layer on top of their queue APIs.
- ❌ Showing recommendations (use [Jellynext](https://github.com/luall0/jellynext) for that).
- ❌ Becoming a download manager. We display state, we don't manage it.

## 💡 Hard problems we want help with

- **iOS/tvOS app testing.** We don't have one. If you do, file an issue with screenshots showing how the channel renders.
- **Multi-user mapping.** The current name-based filter is a placeholder. Proper Jellyseerr user → Jellyfin user mapping needs the daemon to expose the Jellyfin-side user ID, which Jellyseerr stores per-request. We have a design (see `jellyseerr_client.py`) but no test setup with multiple users.
- **Sub-second progress updates.** The 30s poll is fine for first-pass, but a webhook flow (planned v0.3) would let the channel reflect download progress in near-real-time.
- **Channel image / icon.** Currently the channel has no icon — Jellyfin shows a default. A small SVG that fits the Forest-Green-Apple aesthetic of the rest of the project would be nice.
