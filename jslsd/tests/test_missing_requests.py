"""Tests for missing-request surfacing: Seerr merge, grace period, dedupe."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx

from jslsd.config import Config, JellyseerrConfig
from jslsd.models import PendingItem
from jslsd.poller import Poller

SEERR_URL = "http://seerr.local:5055"

APPROVED = 2
MEDIA_UNKNOWN, MEDIA_PENDING, MEDIA_PROCESSING = 1, 2, 3
MEDIA_PARTIALLY_AVAILABLE, MEDIA_AVAILABLE = 4, 5


def ago(days: int) -> str:
    return (datetime.now(UTC) - timedelta(days=days, hours=1)).isoformat().replace(
        "+00:00", "Z"
    )


def request_payload(
    req_id: int,
    *,
    kind: str = "movie",
    days: int = 10,
    status: int = APPROVED,
    media_status: int = MEDIA_PROCESSING,
    tmdb_id: int = 111,
    tvdb_id: int | None = None,
    seasons: list[int] | None = None,
) -> dict:
    return {
        "id": req_id,
        "status": status,
        "type": kind,
        "createdAt": ago(days),
        "media": {"tmdbId": tmdb_id, "tvdbId": tvdb_id, "status": media_status},
        "requestedBy": {"displayName": "Pet"},
        "seasons": [{"seasonNumber": s} for s in (seasons or [])],
    }


@pytest.fixture
def config(tmp_path: Path) -> Config:
    return Config(
        jellyseerr=JellyseerrConfig(url=SEERR_URL, api_key="dummy-test-value"),
        poster_cache_dir=tmp_path / "posters",
    )


def mock_seerr(requests: list[dict]) -> None:
    respx.get(f"{SEERR_URL}/api/v1/request").mock(
        return_value=httpx.Response(200, json={"results": requests})
    )
    respx.get(url__regex=rf"{SEERR_URL}/api/v1/(movie|tv)/\d+").mock(
        return_value=httpx.Response(
            200, json={"title": "Testfilm", "posterPath": "/abc.jpg"}
        )
    )


async def build(poller: Poller, queue_items: list[PendingItem] | None = None):
    return await poller._build_missing_items(queue_items or [])


@respx.mock
async def test_stale_request_becomes_not_found(config: Config) -> None:
    mock_seerr([request_payload(1, days=10)])
    poller = Poller(config)
    out = await build(poller)

    assert len(out) == 1
    item, art_url = out[0]
    assert item.id == "seerr-req-1"
    assert item.source == "seerr"
    assert item.status == "not_found"
    assert item.title == "Testfilm"
    assert item.requested_by == "Pet"
    assert item.progress_percent == 0.0
    assert item.eta_seconds is None
    assert art_url == "https://image.tmdb.org/t/p/w600_and_h900_bestv2/abc.jpg"


@respx.mock
async def test_fresh_request_is_searching(config: Config) -> None:
    mock_seerr([request_payload(2, days=1)])
    out = await build(Poller(config))
    assert [i.status for i, _ in out] == ["searching"]


@respx.mock
async def test_request_beyond_retention_is_dropped(config: Config) -> None:
    mock_seerr([request_payload(3, days=40)])
    assert await build(Poller(config)) == []


@respx.mock
async def test_available_and_unapproved_are_ignored(config: Config) -> None:
    mock_seerr([
        request_payload(4, media_status=MEDIA_AVAILABLE),
        request_payload(5, status=1),
    ])
    assert await build(Poller(config)) == []


@respx.mock
async def test_partially_available_series_is_ignored(config: Config) -> None:
    mock_seerr([
        request_payload(6, kind="tv", media_status=MEDIA_PARTIALLY_AVAILABLE),
        request_payload(7, kind="tv", media_status=MEDIA_PENDING, tmdb_id=222),
    ])
    out = await build(Poller(config))
    assert [i.id for i, _ in out] == ["seerr-req-7"]


@respx.mock
async def test_partially_available_movie_is_reported(config: Config) -> None:
    """For movies anything but AVAILABLE counts as missing."""
    mock_seerr([request_payload(8, media_status=MEDIA_PARTIALLY_AVAILABLE)])
    out = await build(Poller(config))
    assert [i.id for i, _ in out] == ["seerr-req-8"]


@respx.mock
async def test_queue_item_wins_over_request(config: Config) -> None:
    mock_seerr([
        request_payload(9, tmdb_id=555),
        request_payload(10, kind="tv", tmdb_id=666, tvdb_id=777,
                        media_status=MEDIA_UNKNOWN),
    ])
    queued = [
        PendingItem(id="radarr-1", source="radarr", type="movie", title="X",
                    tmdb_id=555, poster_url="/api/poster/radarr-1.png"),
        PendingItem(id="sonarr-1", source="sonarr", type="tv", title="Y",
                    tvdb_id=777, poster_url="/api/poster/sonarr-1.png"),
    ]
    assert await build(Poller(config), queued) == []


@respx.mock
async def test_season_lands_in_title(config: Config) -> None:
    mock_seerr([
        request_payload(11, kind="tv", media_status=MEDIA_PENDING, seasons=[3])
    ])
    out = await build(Poller(config))
    assert out[0][0].title == "Testfilm — Staffel 3"


@respx.mock
async def test_seerr_error_does_not_break_poll(config: Config) -> None:
    respx.get(f"{SEERR_URL}/api/v1/request").mock(
        return_value=httpx.Response(500)
    )
    assert await build(Poller(config)) == []


@respx.mock
async def test_disabled_by_config(config: Config) -> None:
    mock_seerr([request_payload(12)])
    config.show_missing_requests = False
    assert await build(Poller(config)) == []
