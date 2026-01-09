from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from faceforge_core.config import load_core_config, resolve_configured_paths
from faceforge_core.home import ensure_faceforge_layout, resolve_faceforge_home


def create_app() -> FastAPI:
    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        home = resolve_faceforge_home()
        paths = ensure_faceforge_layout(home)
        config = load_core_config(paths)
        paths = resolve_configured_paths(paths, config)

        app.state.faceforge_home = home
        app.state.faceforge_paths = paths
        app.state.faceforge_config = config

        yield

    app = FastAPI(title="FaceForge Core", version="0.0.0", lifespan=_lifespan)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
