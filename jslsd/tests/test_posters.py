"""Tests for poster generation — cache hits, placeholder fallback, file output."""

from __future__ import annotations

import io
from pathlib import Path

import httpx
import pytest
import respx
from PIL import Image

from jslsd.posters import PosterGenerator, _human_eta, _safe_id, _status_badge


@pytest.fixture
def cache_dir(tmp_path: Path) -> Path:
    return tmp_path / "posters"


@pytest.fixture
def fake_poster_bytes() -> bytes:
    img = Image.new("RGB", (300, 450), color=(80, 50, 120))
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


@respx.mock
async def test_generate_with_remote_art(
    cache_dir: Path, fake_poster_bytes: bytes
) -> None:
    respx.get("http://art.example/p.jpg").mock(
        return_value=httpx.Response(200, content=fake_poster_bytes)
    )

    gen = PosterGenerator(cache_dir=cache_dir)
    out_path = await gen.get_or_generate(
        item_id="sonarr-12345",
        progress_percent=42.0,
        eta_seconds=900,
        status="downloading",
        art_url="http://art.example/p.jpg",
        title="Severance — S02E09",
    )

    assert out_path.exists()
    assert out_path.stat().st_size > 0
    assert "p040" in out_path.name  # progress bucket: 42 → 40
    assert "downloading" in out_path.name

    # Re-call should hit cache (no new HTTP request)
    out_path2 = await gen.get_or_generate(
        item_id="sonarr-12345",
        progress_percent=42.0,
        eta_seconds=900,
        status="downloading",
        art_url="http://art.example/p.jpg",
        title="Severance — S02E09",
    )
    assert out_path == out_path2

    await gen.aclose()


async def test_generate_placeholder_fallback(cache_dir: Path) -> None:
    gen = PosterGenerator(cache_dir=cache_dir)
    out_path = await gen.get_or_generate(
        item_id="radarr-9999",
        progress_percent=0.0,
        eta_seconds=None,
        status="queued",
        art_url=None,
        title="Unknown Movie",
    )
    assert out_path.exists()
    img = Image.open(out_path)
    assert img.size == (600, 900)
    await gen.aclose()


async def test_generate_info_tile(cache_dir: Path) -> None:
    gen = PosterGenerator(cache_dir=cache_dir)
    out_path = await gen.generate_info_tile(
        item_id="sonarr-12345",
        kind="eta",
        label="ETA",
        value="12m",
    )
    assert out_path.exists()
    assert out_path.stat().st_size > 0
    img = Image.open(out_path)
    assert img.size == (600, 900)

    out_path2 = await gen.generate_info_tile(
        item_id="sonarr-12345",
        kind="eta",
        label="ETA",
        value="12m",
    )
    assert out_path == out_path2  # cache hit
    await gen.aclose()


def test_safe_id_handles_special_chars() -> None:
    safe = _safe_id("sonarr-12/3:45")
    assert "/" not in safe
    assert ":" not in safe


def test_status_badge_known_values() -> None:
    assert _status_badge("downloading")[0] == "LIVE"
    assert _status_badge("queued")[0] == "QUEUED"
    assert _status_badge("completed")[0] == "READY"
    assert _status_badge("failed")[0] == "FAILED"
    assert _status_badge("paused")[0] == "PAUSED"
    # Unknown falls back
    assert _status_badge("zzz-unknown")[0] == "PENDING"


def test_human_eta_formats() -> None:
    assert _human_eta(0) == "0s"
    assert _human_eta(45) == "45s"
    assert _human_eta(60) == "1m"
    assert _human_eta(3599) == "59m"
    assert _human_eta(3600) == "1h 0m"
    assert _human_eta(7330) == "2h 2m"
