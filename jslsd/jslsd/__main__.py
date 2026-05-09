"""Entry point: load config, optionally inject demo items, start uvicorn."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import tempfile
from pathlib import Path

import uvicorn

from .api import create_app
from .config import Config
from .demo import DEMO_ITEMS


def main() -> None:
    parser = argparse.ArgumentParser(
        description="jslsd — Jellyfin Seerr Loading Screen daemon"
    )
    parser.add_argument(
        "--config", "-c", type=Path, help="Path to config.yaml (env vars also work)"
    )
    parser.add_argument(
        "--log-level",
        default="info",
        choices=["debug", "info", "warning", "error"],
    )
    parser.add_argument(
        "--demo",
        action="store_true",
        help="Skip Sonarr/Radarr polling, inject 3 fake pending items for UI preview.",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    config = _demo_config() if args.demo else _load_config(args.config)
    app = create_app(config)

    if args.demo:
        asyncio.run(_inject_demo(app))
        sys.stderr.write(f"[demo] Injected {len(DEMO_ITEMS)} fake pending items.\n")

    uvicorn.run(
        app,
        host=config.api_listen_host,
        port=config.api_listen_port,
        log_level=args.log_level,
        access_log=False,
    )


def _load_config(path: Path | None) -> Config:
    try:
        config = Config.load(path)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"Failed to load config: {e}\n")
        sys.exit(2)
    if not (config.sonarr or config.radarr):
        sys.stderr.write("Config must define at least one of sonarr/radarr.\n")
        sys.exit(2)
    return config


def _demo_config() -> Config:
    return Config.model_validate({
        "poster_cache_dir": Path(tempfile.gettempdir()) / "jslsd-demo-posters",
        "api_listen_host": os.environ.get("JSLSD_API_LISTEN_HOST", "0.0.0.0"),  # noqa: S104
        "api_listen_port": int(os.environ.get("JSLSD_API_LISTEN_PORT", "7000")),
        "demo_mode": True,
    })


async def _inject_demo(app) -> None:  # noqa: ANN001
    poller = app.state.poller
    for item in DEMO_ITEMS:
        poller.inject(item)
        await poller.posters.get_or_generate(
            item_id=item.id,
            progress_percent=item.progress_percent,
            eta_seconds=item.eta_seconds,
            status=item.status,
            art_url=None,
            title=item.title,
        )


if __name__ == "__main__":
    main()
