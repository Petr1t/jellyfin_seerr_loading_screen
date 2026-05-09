"""Config loader: YAML file with env-var overrides.

Env-var precedence: JSLSD_<SECTION>_<KEY>, e.g. JSLSD_SONARR_API_KEY.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, HttpUrl

DEFAULT_CONFIG_PATHS = [
    Path("/etc/jslsd/config.yaml"),
    Path.home() / ".config" / "jslsd" / "config.yaml",
    Path("./config.yaml"),
]


class ArrConfig(BaseModel):
    url: HttpUrl
    api_key: str = Field(..., min_length=8)


class JellyseerrConfig(BaseModel):
    url: HttpUrl
    api_key: str = Field(..., min_length=8)


class Config(BaseModel):
    sonarr: ArrConfig | None = None
    radarr: ArrConfig | None = None
    jellyseerr: JellyseerrConfig | None = None

    poll_interval_seconds: int = Field(30, ge=5, le=600)
    poster_cache_dir: Path = Field(Path("/var/cache/jslsd/posters"))
    poster_size: tuple[int, int] = Field((400, 600), description="width, height in px")
    api_listen_host: str = "0.0.0.0"  # noqa: S104 — daemon needs LAN reach by design
    api_listen_port: int = Field(7000, ge=1, le=65535)

    completed_retention_seconds: int = 300
    failed_retention_seconds: int = 3600

    @classmethod
    def load(cls, path: Path | None = None) -> Config:
        """Load config from path or default locations, then apply env overrides."""
        data: dict[str, Any] = {}

        candidate_paths = [path] if path else DEFAULT_CONFIG_PATHS
        for candidate in candidate_paths:
            if candidate and candidate.exists():
                with candidate.open() as f:
                    data = yaml.safe_load(f) or {}
                break

        # Apply env overrides
        data = _apply_env_overrides(data)

        return cls.model_validate(data)


def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """Override config values from JSLSD_* env vars."""
    mapping = {
        "JSLSD_SONARR_URL": ("sonarr", "url"),
        "JSLSD_SONARR_API_KEY": ("sonarr", "api_key"),
        "JSLSD_RADARR_URL": ("radarr", "url"),
        "JSLSD_RADARR_API_KEY": ("radarr", "api_key"),
        "JSLSD_JELLYSEERR_URL": ("jellyseerr", "url"),
        "JSLSD_JELLYSEERR_API_KEY": ("jellyseerr", "api_key"),
        "JSLSD_POLL_INTERVAL_SECONDS": ("poll_interval_seconds",),
        "JSLSD_API_LISTEN_HOST": ("api_listen_host",),
        "JSLSD_API_LISTEN_PORT": ("api_listen_port",),
        "JSLSD_POSTER_CACHE_DIR": ("poster_cache_dir",),
    }

    for env_key, path in mapping.items():
        value = os.environ.get(env_key)
        if value is None:
            continue

        cursor = data
        for segment in path[:-1]:
            cursor = cursor.setdefault(segment, {})
        cursor[path[-1]] = value

    return data
