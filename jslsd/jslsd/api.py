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
