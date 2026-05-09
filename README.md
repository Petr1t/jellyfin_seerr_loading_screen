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

## Status

**v0.1 — Side-car daemon (Python).** Pollt Sonarr and Radarr APIs, caches the queue, generates poster overlays with progress, exposes a JSON HTTP API.
*Working today, runs as systemd-user-unit on the same host as your Arr stack.*

**v0.2 — Jellyfin C# plugin.** Consumes the v0.1 daemon, creates virtual library items via Jellyfin's `BaseItem` API, hooks into the Web UI via the `FileTransformation` plugin to render the progress overlay live in your library view.
*Skeleton present, full implementation in progress — see [ROADMAP.md](docs/ROADMAP.md).*

## Architecture

```
[Jellyseerr] ──request──▶ [Sonarr / Radarr] ──▶ [qBittorrent]
                                  │
                                  │ poll /api/v3/queue every 30s
                                  ▼
                          [jslsd Python daemon]
                          ─ caches queue state
                          ─ generates poster overlays (PIL)
                          ─ FastAPI: /api/coming-soon
                                  │
                                  │ HTTP poll
                                  ▼
                  [jellyfin_seerr_loading_screen plugin]
                          ─ creates virtual BaseItems
                          ─ injects progress overlay into Web UI
                                  │
                                  ▼
                              [Jellyfin]
```

The two halves are independent. You can run only the Python daemon today and build your own UI on top of `/api/coming-soon`. The plugin is convenience — it wires the daemon into Jellyfin's native library view.

## Quick start (v0.1 daemon only)

```bash
git clone https://github.com/Petr1t/jellyfin_seerr_loading_screen.git
cd jellyfin_seerr_loading_screen
./scripts/install-daemon.sh
```

The installer prompts for:
- Sonarr URL + API key
- Radarr URL + API key
- (Optional) Jellyseerr URL + API key
- Listening port (default 7878 — yes, same as Radarr's, change if you run the daemon on the same host)

It writes `/etc/jslsd/config.yaml`, installs `jslsd.service`, starts it, and you can verify:

```bash
curl http://localhost:7878/api/coming-soon | jq
```

## Quick start (v0.2 plugin)

[See ROADMAP.md](docs/ROADMAP.md) — not stable yet.

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
