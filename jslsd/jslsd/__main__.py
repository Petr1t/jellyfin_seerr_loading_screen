"""Entry point: load config, start uvicorn."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import uvicorn

from .api import create_app
from .config import Config


def main() -> None:
    parser = argparse.ArgumentParser(description="jslsd — Jellyfin Seerr Loading Screen daemon")
    parser.add_argument(
        "--config",
        "-c",
        type=Path,
        help="Path to config.yaml (default: search /etc/jslsd/, ~/.config/jslsd/, ./)",
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["debug", "info", "warning", "error"],
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Inject three fake pending items so you can preview the plugin without "
        "an active download. No Sonarr/Radarr config required in this mode.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    if args.demo:
        config = _demo_config()
    else:
        try:
            config = Config.load(args.config)
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"Failed to load config: {e}\n")
            sys.exit(2)

        if not (config.sonarr or config.radarr):
            sys.stderr.write("Config must define at least one of sonarr/radarr.\n")
            sys.exit(2)

    app = create_app(config)

    if args.demo:
        _inject_demo_items(app)

    uvicorn.run(
        app,
        host=config.api_listen_host,
        port=config.api_listen_port,
        log_level=args.log_level,
        access_log=False,
    )


def _demo_config() -> Config:
    """Minimal config for --demo mode: no Arr clients, just the API."""
    import os
    import tempfile

    return Config.model_validate({
        "poster_cache_dir": Path(tempfile.gettempdir()) / "jslsd-demo-posters",
        "api_listen_host": os.environ.get("JSLSD_API_LISTEN_HOST", "0.0.0.0"),
        "api_listen_port": int(os.environ.get("JSLSD_API_LISTEN_PORT", "7000")),
        "poll_interval_seconds": 600,
        "demo_mode": True,
    })


def _inject_demo_items(app) -> None:  # noqa: ANN001
    """Pre-populate the poller cache with three fake PendingItems for UI preview."""
    import asyncio

    from .models import PendingItem
    from .posters import PosterGenerator

    poller = app.state.poller
    config = app.state.config

    demo = [
        PendingItem(
            id="demo-tv-severance",
            source="sonarr",
            type="tv",
            title="Severance — S02E09",
            series_title="Severance",
            season=2,
            episode=9,
            tmdb_id=95396,
            size_total_bytes=3_500_000_000,
            size_left_bytes=1_155_000_000,
            progress_percent=67.0,
            eta_seconds=14 * 60,
            download_client="qbittorrent",
            status="downloading",
            requested_by="pet",
            poster_url="/api/poster/demo-tv-severance.png",
        ),
        PendingItem(
            id="demo-movie-dune2",
            source="radarr",
            type="movie",
            title="Dune: Part Two",
            tmdb_id=693134,
            size_total_bytes=8_100_000_000,
            size_left_bytes=4_050_000_000,
            progress_percent=50.0,
            eta_seconds=48 * 60,
            download_client="qbittorrent",
            status="downloading",
            requested_by="pet",
            poster_url="/api/poster/demo-movie-dune2.png",
        ),
        PendingItem(
            id="demo-tv-andor",
            source="sonarr",
            type="tv",
            title="Andor — S02E07",
            series_title="Andor",
            season=2,
            episode=7,
            size_total_bytes=4_200_000_000,
            size_left_bytes=4_200_000_000,
            progress_percent=0.0,
            eta_seconds=None,
            download_client="qbittorrent",
            status="queued",
            requested_by="pet",
            poster_url="/api/poster/demo-tv-andor.png",
        ),
    ]

    gen = PosterGenerator(cache_dir=config.poster_cache_dir, size=config.poster_size)

    async def populate() -> None:
        for item in demo:
            poller._cache[item.id] = item  # noqa: SLF001 — internal injection by design
            await gen.get_or_generate(
                item_id=item.id,
                progress_percent=item.progress_percent,
                eta_seconds=item.eta_seconds,
                status=item.status,
                art_url=None,
                title=item.title,
            )
        await gen.aclose()

    asyncio.run(populate())
    sys.stderr.write(f"[demo] Injected {len(demo)} fake pending items.\n")


if __name__ == "__main__":
    main()
