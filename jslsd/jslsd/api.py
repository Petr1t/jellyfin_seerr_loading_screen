"""FastAPI app: exposes /api/coming-soon, /api/poster/<id>.png, /healthz."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

from .config import Config
from .models import HealthResponse, PendingItem
from .poller import Poller

log = logging.getLogger(__name__)


def create_app(config: Config | None = None) -> FastAPI:
    cfg = config or Config.load()
    poller = Poller(cfg)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await poller.start()
        try:
            yield
        finally:
            await poller.stop()

    app = FastAPI(
        title="jslsd",
        description="jellyfin_seerr_loading_screen daemon",
        version="0.1.0",
        lifespan=lifespan,
    )

    @app.get("/api/coming-soon", response_model=list[PendingItem])
    async def list_coming_soon(
        source: str | None = Query(None, pattern="^(sonarr|radarr)$"),
        status: str | None = Query(None, pattern="^(queued|downloading|completed|failed|paused)$"),
        requested_by: str | None = Query(None),
    ) -> list[PendingItem]:
        items = poller.items
        if source:
            items = [i for i in items if i.source == source]
        if status:
            items = [i for i in items if i.status == status]
        if requested_by:
            items = [
                i
                for i in items
                if i.requested_by and i.requested_by.lower() == requested_by.lower()
            ]
        # Stable sort: status precedence, then progress desc, then title
        status_order = {
            "downloading": 0,
            "queued": 1,
            "paused": 2,
            "completed": 3,
            "failed": 4,
        }
        items.sort(
            key=lambda i: (
                status_order.get(i.status, 99),
                -i.progress_percent,
                i.title.lower(),
            )
        )
        return items

    @app.get("/api/poster/{item_id}.png")
    async def get_poster(item_id: str) -> FileResponse:
        path_str = poller.get_poster_path(item_id)
        if not path_str:
            raise HTTPException(404, detail=f"item_id not in cache: {item_id}")
        path = Path(path_str)
        if not path.exists():  # noqa: ASYNC240 — sync stat is fine at our scale
            raise HTTPException(404, detail="poster not yet generated")
        return FileResponse(path, media_type="image/png")  # noqa: RET504

    @app.get("/api/poster/{item_id}/tile/{kind}.png")
    async def get_info_tile(item_id: str, kind: str) -> FileResponse:
        """Detail-view info tile (one big number/word per tile)."""
        item = poller.items_by_id.get(item_id)
        if not item:
            raise HTTPException(404, detail=f"item_id not in cache: {item_id}")
        spec = _tile_spec(kind, item)
        if spec is None:
            raise HTTPException(404, detail=f"no data for tile kind: {kind}")
        label, value, accent = spec
        path = await poller.posters.generate_info_tile(
            item_id=item_id, kind=kind, label=label, value=value, accent=accent,
        )
        return FileResponse(path, media_type="image/png")

    @app.post("/api/items/{item_id}/blocklist")
    async def blocklist_item(item_id: str) -> JSONResponse:
        """Blocklist every queue record this item aggregates. Sonarr will then
        re-search for a different release on its next scheduled cycle."""
        result = await poller.blocklist_item(item_id)
        status_code = 200 if result.get("ok") else 207  # 207 = multi-status (partial)
        if result.get("reason") == "item not in cache":
            status_code = 404
        return JSONResponse(result, status_code=status_code)

    @app.get("/healthz", response_model=HealthResponse)
    async def healthz() -> HealthResponse:
        data = await poller.health()
        return HealthResponse.model_validate(data)

    @app.get("/")
    async def root() -> JSONResponse:
        return JSONResponse(
            {
                "name": "jslsd",
                "version": "0.1.0",
                "endpoints": ["/api/coming-soon", "/api/poster/{id}.png", "/healthz"],
                "source": "https://github.com/Petr1t/jellyfin_seerr_loading_screen",
            }
        )

    app.state.poller = poller
    app.state.config = cfg
    return app


_STATUS_ACCENT: dict[str, tuple[int, int, int]] = {
    "downloading": (60, 200, 130),
    "queued": (140, 140, 140),
    "completed": (30, 144, 255),
    "failed": (220, 60, 60),
    "paused": (200, 160, 60),
}

_STATUS_LABEL: dict[str, str] = {
    "downloading": "LIVE",
    "queued": "QUEUED",
    "completed": "READY",
    "failed": "FAILED",
    "paused": "PAUSED",
}


def _tile_spec(
    kind: str, item: PendingItem
) -> tuple[str, str, tuple[int, int, int] | None] | None:
    """Map (kind, item) → (label, value, accent_rgb)."""
    from .posters import _human_eta  # local import avoids API↔posters coupling at module load

    if kind == "status":
        return ("Status", _STATUS_LABEL.get(item.status, item.status.upper()),
                _STATUS_ACCENT.get(item.status))
    if kind == "progress":
        return ("Fortschritt", f"{item.progress_percent:.0f}%", None)
    if kind == "eta":
        if item.eta_seconds is None:
            return None
        return ("ETA", _human_eta(item.eta_seconds), None)
    if kind == "size":
        if item.size_total_bytes <= 0:
            return None
        total_gb = item.size_total_bytes / 1024**3
        done_gb = (item.size_total_bytes - item.size_left_bytes) / 1024**3
        return ("Größe", f"{done_gb:.1f} / {total_gb:.1f} GB", None)
    if kind == "client":
        if not item.download_client:
            return None
        return ("Download via", item.download_client, None)
    if kind == "requester":
        if not item.requested_by:
            return None
        return ("Angefragt von", item.requested_by, None)
    if kind == "blocklist":
        # Red accent → reads as a destructive/action tile. The C# detail-view
        # only emits this tile for stuck items (paused/failed), so the visual
        # always lines up with an actionable state.
        return ("Aktion", "Blocklist + Re-Search", (220, 60, 60))
    return None
