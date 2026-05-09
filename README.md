# jellyfin_seerr_loading_screen

[![Python (jslsd)](https://github.com/Petr1t/jellyfin_seerr_loading_screen/actions/workflows/python.yml/badge.svg)](https://github.com/Petr1t/jellyfin_seerr_loading_screen/actions/workflows/python.yml)
[![.NET Plugin](https://github.com/Petr1t/jellyfin_seerr_loading_screen/actions/workflows/dotnet.yml/badge.svg)](https://github.com/Petr1t/jellyfin_seerr_loading_screen/actions/workflows/dotnet.yml)
[![License: GPL v2](https://img.shields.io/badge/License-GPL_v2-blue.svg)](https://www.gnu.org/licenses/old-licenses/gpl-2.0.en.html)

> Show Sonarr/Radarr pending downloads as Jellyfin library items with live progress.

When you request a movie or TV show via Jellyseerr, it disappears into a black box until the download finishes. This project surfaces that gap: you see the requested item show up immediately in Jellyfin, with a progress bar overlaid on its poster, an ETA based on the qBittorrent queue, and the option to cancel/pause from the Jellyfin UI itself.

```
┌────────────────┐  ┌────────────────┐  ┌────────────────┐
│   Episode 8    │  │ ▓▓▓▓▓▓░░░ 67%  │  │  Episode 12    │
│ (LIVE)         │  │  ETA  ~14 min  │  │  (LIVE)        │
└────────────────┘  └────────────────┘  └────────────────┘
   Aired           Coming Soon            Aired
```

## Status — **v0.2.0** (released 2026-05-09)

**Daemon (Python `jslsd`)** — feature-complete. Polls Sonarr + Radarr `/api/v3/queue`, generates poster overlays with progress, exposes a JSON HTTP API. Runs as systemd-user-unit on your Arr host. 15 unit tests passing, smoke-tested against real Sonarr 4.0.17 + Radarr.

**Jellyfin Plugin (.NET 9, Jellyfin 10.11)** — implements `IChannel` to expose pending downloads as a browseable channel inside Jellyfin. The channel auto-refreshes when the queue changes. Native iOS/Android/tvOS support via baked PNG progress posters (no JS overlay hacks).

[![Latest release](https://img.shields.io/github/v/release/Petr1t/jellyfin_seerr_loading_screen)](https://github.com/Petr1t/jellyfin_seerr_loading_screen/releases/latest)

## Architecture

```
[Jellyseerr] ──request──▶ [Sonarr / Radarr] ──▶ [qBittorrent / SAB / ...]
                                  │
                                  │ poll /api/v3/queue every 30s
                                  ▼
                          [jslsd Python daemon]
                          ─ caches queue state
                          ─ generates poster overlays (PIL)
                          ─ FastAPI: /api/coming-soon
                                  │
                                  │ HTTP polled by Jellyfin
                                  ▼
                  [Seerr Loading Screen plugin]
                          ─ implements IChannel
                          ─ each pending item → ChannelItemInfo
                          ─ ImageUrl points at daemon poster
                                  │
                                  ▼
                              [Jellyfin]
                          → "📥 Coming Soon" channel
                            in user's library list
```

The two halves are independent. The daemon is useful on its own — `/api/coming-soon` JSON can drive a HUB75 LED display, a Telegram bot, or a Home Assistant sensor.

## Quick start

### Step 1 — install the daemon (`jslsd`) on your Arr host

```bash
git clone https://github.com/Petr1t/jellyfin_seerr_loading_screen.git
cd jellyfin_seerr_loading_screen
./scripts/install-daemon.sh
```

The installer prompts for Sonarr / Radarr / Jellyseerr URLs + API keys, writes `~/.config/jslsd/config.yaml`, installs as a systemd-user-unit on port `7000` (configurable), and starts it.

Verify:
```bash
curl http://localhost:7000/healthz | jq
curl http://localhost:7000/api/coming-soon | jq
```

### Step 2 — install the Jellyfin plugin

In Jellyfin admin → Dashboard → Plugins → **Repositories** → **Add**:

| Field | Value |
|---|---|
| Repository Name | `Seerr Loading Screen` |
| Repository URL | `https://raw.githubusercontent.com/Petr1t/jellyfin_seerr_loading_screen/main/manifest.json` |

Then **Catalog** → **Seerr Loading Screen** → **Install**. Restart Jellyfin.

### Step 3 — point the plugin at the daemon

Plugins → **Seerr Loading Screen** → set:
- **Daemon URL**: `http://<paradecentral-or-wherever>:7000`
- **Refresh interval**: 30s default
- **Show all users**: on (single-user setup) or off (filter by Jellyseerr-mapped current user)

Save. The "📥 Coming Soon" channel appears in your library list within ~30s. Items show with progress posters; click one to see overview + status. Items disappear when the download completes (default 5min READY-state retention).

## Configuration

`/etc/jslsd/config.yaml`:

```yaml
sonarr:
  url: http://localhost:8989
  api_key: REDACTED
radarr:
  url: http://localhost:7878  # if jslsd runs elsewhere
  api_key: REDACTED
jellyseerr:
  url: http://localhost:5055  # optional, used to resolve user from Jellyfin user ID
  api_key: REDACTED
poll_interval_seconds: 30
poster_cache_dir: /var/cache/jslsd/posters
poster_size: [400, 600]   # width, height
api_listen: 0.0.0.0:7000
```

## API

### `GET /api/coming-soon`

Returns array of pending downloads:

```json
[
  {
    "id": "sonarr-12345",
    "type": "tv",
    "title": "Severance — S02E09",
    "tmdb_id": 95396,
    "tvdb_id": 371572,
    "size_total_bytes": 4123456789,
    "size_left_bytes": 1234567890,
    "progress_percent": 70.0,
    "eta_seconds": 840,
    "download_client": "qbittorrent",
    "status": "downloading",
    "requested_by": "pet@example.de",
    "poster_url": "/api/poster/sonarr-12345.png"
  }
]
```

### `GET /api/poster/{id}.png`

Returns a JPEG/PNG poster with progress bar overlaid (size and style configurable).

### `GET /healthz`

Returns `200 OK` with `{"status": "ok"}` when daemon is running.

## License

GPL-2.0 — same as Jellyfin itself, which makes the v0.2 plugin properly integrable.

## Contributing

PRs welcome. See [CONTRIBUTING.md](docs/CONTRIBUTING.md).

The hard problems we want help with:
- Multi-user filtering (only show *my* requests, not housemates'). Needs Jellyseerr-user → Jellyfin-user mapping.
- Live progress in Jellyfin Web UI (currently the plugin polls every 30s — can we hook into Sonarr/Radarr webhooks for push?)
- iOS/tvOS Jellyfin app support (the FileTransformation overlay only works for Web UI).

## Acknowledgements

Inspired by:
- **Jellynext** by [@luall0](https://github.com/luall0/jellynext) — pioneered the virtual-library pattern for Jellyfin.
- **File Transformation** plugin by IAmParadox — the plumbing that makes Web UI overlays possible.
- **Intro Skipper** community for proving that small focused plugins can have real impact.
