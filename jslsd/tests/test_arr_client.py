"""Tests for arr_client — verify queue parsing, ETA decoding, status mapping."""

from __future__ import annotations

import httpx
import pytest
import respx

from jslsd.arr_client import QueueRecord, RadarrClient, SonarrClient
from jslsd.config import ArrConfig

SONARR_QUEUE_FIXTURE = {
    "page": 1,
    "pageSize": 200,
    "totalRecords": 1,
    "records": [
        {
            "id": 12345,
            "seriesId": 42,
            "episodeId": 4711,
            "size": 1_000_000_000,
            "sizeleft": 250_000_000,
            "timeleft": "00:14:23",
            "status": "downloading",
            "downloadClient": "qbittorrent",
            "episode": {
                "seasonNumber": 2,
                "episodeNumber": 9,
                "title": "Cold Harbor",
            },
        }
    ],
}

SONARR_SERIES_FIXTURE = {
    "id": 42,
    "title": "Severance",
    "tmdbId": 95396,
    "tvdbId": 371572,
    "imdbId": "tt11280740",
    "images": [
        {"coverType": "poster", "url": "/poster.jpg", "remoteUrl": "https://art/poster.jpg"}
    ],
}


@pytest.fixture
def sonarr_config() -> ArrConfig:
    return ArrConfig.model_validate(
        {"url": "http://sonarr.test", "api_key": "deadbeef-test-key-1234"}
    )


@respx.mock
async def test_sonarr_queue_parsing(sonarr_config: ArrConfig) -> None:
    respx.get("http://sonarr.test/api/v3/queue").mock(
        return_value=httpx.Response(200, json=SONARR_QUEUE_FIXTURE)
    )
    respx.get("http://sonarr.test/api/v3/series/42").mock(
        return_value=httpx.Response(200, json=SONARR_SERIES_FIXTURE)
    )

    async with httpx.AsyncClient() as http:
        records = await SonarrClient(sonarr_config, http).queue()

    assert len(records) == 1
    record = records[0]
    assert record.queue_id == 12345
    assert record.source == "sonarr"
    assert record.status == "downloading"
    assert record.eta_seconds == 14 * 60 + 23
    assert record.progress_percent == 75.0
    assert record.media is not None
    assert record.media["title"] == "Severance"


def test_eta_parsing_with_days() -> None:
    rec = QueueRecord(
        queue_id=1,
        source="sonarr",
        raw={"timeleft": "1.02:30:00"},
    )
    assert rec.eta_seconds == 86400 + 2 * 3600 + 30 * 60


def test_eta_parsing_invalid() -> None:
    rec = QueueRecord(queue_id=1, source="sonarr", raw={"timeleft": "garbage"})
    assert rec.eta_seconds is None

    rec2 = QueueRecord(queue_id=1, source="sonarr", raw={})
    assert rec2.eta_seconds is None


def test_progress_zero_size() -> None:
    rec = QueueRecord(queue_id=1, source="sonarr", raw={"size": 0, "sizeleft": 0})
    assert rec.progress_percent == 0.0


def test_status_mapping() -> None:
    cases = [
        ("downloading", "downloading"),
        ("paused", "paused"),
        ("completed", "completed"),
        ("imported", "completed"),
        ("failed", "failed"),
        ("warning", "paused"),
        ("queued", "queued"),
        ("anything-else", "queued"),
    ]
    for raw_status, expected in cases:
        rec = QueueRecord(queue_id=1, source="sonarr", raw={"status": raw_status})
        assert rec.status == expected, f"{raw_status} → {rec.status}, expected {expected}"


@respx.mock
async def test_radarr_queue_includes_movie_inline(sonarr_config: ArrConfig) -> None:
    movie_inline = {
        "id": 100,
        "title": "Dune: Part Two",
        "tmdbId": 693134,
        "imdbId": "tt15239678",
        "images": [],
    }
    queue_fixture = {
        "records": [
            {
                "id": 555,
                "movieId": 100,
                "movie": movie_inline,
                "size": 5_000_000_000,
                "sizeleft": 5_000_000_000,
                "timeleft": "01:00:00",
                "status": "queued",
                "downloadClient": "qbittorrent",
            }
        ],
    }
    respx.get("http://sonarr.test/api/v3/queue").mock(
        return_value=httpx.Response(200, json=queue_fixture)
    )

    async with httpx.AsyncClient() as http:
        records = await RadarrClient(sonarr_config, http).queue()

    assert len(records) == 1
    assert records[0].media == movie_inline
    assert records[0].progress_percent == 0.0
    assert records[0].eta_seconds == 3600
