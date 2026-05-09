"""Tests for config loading + env-var overrides."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from jslsd.config import Config


def test_load_minimal_yaml(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
sonarr:
  url: http://sonarr.local:8989
  api_key: test-key-1234567890
""".strip()
    )
    cfg = Config.load(cfg_path)
    assert cfg.sonarr is not None
    assert cfg.radarr is None
    assert cfg.poll_interval_seconds == 30  # default


def test_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
sonarr:
  url: http://sonarr.local:8989
  api_key: yaml-key-abcdef0000
poll_interval_seconds: 30
""".strip()
    )
    monkeypatch.setenv("JSLSD_SONARR_API_KEY", "envvar-key-9999999999")
    monkeypatch.setenv("JSLSD_POLL_INTERVAL_SECONDS", "60")

    cfg = Config.load(cfg_path)
    assert cfg.sonarr is not None
    assert cfg.sonarr.api_key == "envvar-key-9999999999"
    assert cfg.poll_interval_seconds == 60


def test_invalid_poll_interval(tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.yaml"
    cfg_path.write_text(
        """
sonarr:
  url: http://x.local
  api_key: 0123456789
poll_interval_seconds: 1
""".strip()
    )
    with pytest.raises(Exception, match="poll_interval_seconds"):
        Config.load(cfg_path)


def test_no_config_no_env() -> None:
    """Without yaml or env, Config still validates if no fields are required at top."""
    # Clean any test pollution
    for k in list(os.environ.keys()):
        if k.startswith("JSLSD_"):
            os.environ.pop(k)
    cfg = Config.load(Path("/this/does/not/exist.yaml"))
    assert cfg.sonarr is None
    assert cfg.radarr is None
