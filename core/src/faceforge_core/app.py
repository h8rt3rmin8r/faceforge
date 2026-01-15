from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from logging.handlers import RotatingFileHandler

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response
from starlette.staticfiles import StaticFiles

from faceforge_core.api.models import fail
from faceforge_core.api.v1.router import router as v1_router
from faceforge_core.auth import extract_token_from_request, is_exempt_path, require_install_token
from faceforge_core.config import ensure_install_token, load_core_config, resolve_configured_paths
from faceforge_core.db import resolve_db_path
from faceforge_core.db.migrate import apply_migrations
from faceforge_core.home import ensure_faceforge_layout, resolve_faceforge_home
from faceforge_core.seaweedfs import start_managed_seaweed, stop_managed_seaweed
from faceforge_core.storage.manager import build_storage_manager
from faceforge_core.ui.router import STATIC_DIR as UI_STATIC_DIR
from faceforge_core.ui.router import router as ui_router

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    @asynccontextmanager
    async def _lifespan(app: FastAPI):
        home = resolve_faceforge_home()
        paths = ensure_faceforge_layout(home)
        config = load_core_config(paths)
        paths = resolve_configured_paths(paths, config)
        config = ensure_install_token(paths, config)

        # Configure Logging
        log_path = paths.logs_dir / "core.log"
        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=config.logging.max_size_mb * 1024 * 1024,
            backupCount=config.logging.backup_count,
            encoding="utf-8",
        )
        formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
        file_handler.setFormatter(formatter)

        # Configure root logger to capture all module logs
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        # Avoid adding duplicate handlers if reloaded
        if not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
            root.addHandler(file_handler)

        logger.info("FaceForge Core starting up")
        logger.info(f"Logs directory: {paths.logs_dir}")

        db_path = resolve_db_path(paths)
        apply_migrations(db_path)

        app.state.faceforge_home = home
        app.state.faceforge_paths = paths
        app.state.faceforge_config = config
        app.state.db_path = db_path

        # Storage manager (filesystem + optional S3).
        app.state.storage_manager = build_storage_manager(paths=paths, config=config)

        # Optional: Core-managed SeaweedFS process (dev/testing only; Desktop orchestrates later).
        app.state.seaweed_process = start_managed_seaweed(paths, config)

        try:
            yield
        finally:
            stop_managed_seaweed(getattr(app.state, "seaweed_process", None))

    app = FastAPI(title="FaceForge Core", version="0.1.9", lifespan=_lifespan)

    @app.middleware("http")
    async def log_requests(request: Request, call_next):
        response = await call_next(request)
        # Log after response to get status code
        # We can add more details here if needed
        logger.info(f"{request.method} {request.url.path} - {response.status_code}")
        return response

    class _TokenAuthMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next) -> Response:
            path = request.url.path
            if is_exempt_path(path):
                return await call_next(request)

            expected = getattr(getattr(request.app.state, "faceforge_config", None), "auth", None)
            expected_token = getattr(expected, "install_token", None)
            if not expected_token:
                return JSONResponse(
                    status_code=500,
                    content=fail(
                        code="internal_error",
                        message="Server auth token not initialized",
                    ).model_dump(mode="json"),
                )

            provided = extract_token_from_request(request)
            if not provided:
                return JSONResponse(
                    status_code=401,
                    content=fail(code="unauthorized", message="Missing token").model_dump(
                        mode="json"
                    ),
                )
            if provided != expected_token:
                return JSONResponse(
                    status_code=401,
                    content=fail(code="unauthorized", message="Invalid token").model_dump(
                        mode="json"
                    ),
                )

            return await call_next(request)

    app.add_middleware(_TokenAuthMiddleware)

    @app.exception_handler(RequestValidationError)
    async def _validation_error_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=fail(
                code="validation_error",
                message="Request validation failed",
                details=exc.errors(),
            ).model_dump(mode="json"),
        )

    def _status_to_code(status_code: int) -> str:
        if status_code == 401:
            return "unauthorized"
        if status_code == 403:
            return "forbidden"
        if status_code == 404:
            return "not_found"
        if status_code == 409:
            return "conflict"
        if status_code == 422:
            return "validation_error"
        if 400 <= status_code < 500:
            return "client_error"
        return "server_error"

    @app.exception_handler(HTTPException)
    async def _http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=fail(
                code=_status_to_code(exc.status_code),
                message=str(exc.detail),
            ).model_dump(mode="json"),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _starlette_http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=fail(
                code=_status_to_code(exc.status_code),
                message=exc.detail if isinstance(exc.detail, str) else "HTTP error",
            ).model_dump(mode="json"),
        )

    @app.exception_handler(Exception)
    async def _unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        # Avoid leaking internals; details can be logged later.
        return JSONResponse(
            status_code=500,
            content=fail(code="internal_error", message="Internal server error").model_dump(
                mode="json"
            ),
        )

    app.include_router(v1_router, dependencies=[Depends(require_install_token)])

    # Server-rendered UI (served by Core; no runtime Node dependency).
    if UI_STATIC_DIR.is_dir():
        app.mount(
            "/ui/static",
            StaticFiles(directory=str(UI_STATIC_DIR)),
            name="ui-static",
        )
    else:
        logger.warning(
            "UI static directory is missing (%s); /ui/static will not be served",
            UI_STATIC_DIR,
        )
    app.include_router(ui_router)

    @app.get("/")
    async def root() -> RedirectResponse:
        return RedirectResponse(url="/ui/entities", status_code=302)

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app
