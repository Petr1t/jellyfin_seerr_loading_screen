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
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    try:
        config = Config.load(args.config)
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"Failed to load config: {e}\n")
        sys.exit(2)

    if not (config.sonarr or config.radarr):
        sys.stderr.write("Config must define at least one of sonarr/radarr.\n")
        sys.exit(2)

    app = create_app(config)
    uvicorn.run(
        app,
        host=config.api_listen_host,
        port=config.api_listen_port,
        log_level=args.log_level,
        access_log=False,  # too noisy for our use; FastAPI logs structured anyway
    )


if __name__ == "__main__":
    main()
