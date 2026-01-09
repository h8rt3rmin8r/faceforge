from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel

from faceforge_core import __version__
from faceforge_core.api.models import ApiResponse, ok
from faceforge_core.api.v1.admin_field_defs import router as admin_field_defs_router
from faceforge_core.api.v1.assets import router as assets_router
from faceforge_core.api.v1.descriptors import router as descriptors_router
from faceforge_core.api.v1.entities import router as entities_router
from faceforge_core.api.v1.relationships import router as relationships_router
from faceforge_core.api.v1.jobs import router as jobs_router

router = APIRouter(prefix="/v1", tags=["v1"])

router.include_router(entities_router)
router.include_router(descriptors_router)
router.include_router(assets_router)
router.include_router(admin_field_defs_router)
router.include_router(relationships_router)
router.include_router(jobs_router)


class SystemInfo(BaseModel):
    version: str
    faceforge_home: str
    paths: dict[str, str]


@router.get("/ping", response_model=ApiResponse[dict[str, bool]])
async def ping() -> ApiResponse[dict[str, bool]]:
    return ok({"pong": True})


@router.get("/system/info", response_model=ApiResponse[SystemInfo])
async def system_info(request: Request) -> ApiResponse[SystemInfo]:
    # Keep this endpoint stable and boring: basic runtime identity + resolved paths.
    # (No secrets, and no deep config introspection.)
    home = getattr(request.app.state, "faceforge_home", None)
    paths = getattr(request.app.state, "faceforge_paths", None)

    info = SystemInfo(
        version=__version__,
        faceforge_home=str(home) if home is not None else "",
        paths={
            "db_dir": str(paths.db_dir) if paths is not None else "",
            "s3_dir": str(paths.s3_dir) if paths is not None else "",
            "assets_dir": str(paths.assets_dir) if paths is not None else "",
            "logs_dir": str(paths.logs_dir) if paths is not None else "",
            "run_dir": str(paths.run_dir) if paths is not None else "",
            "config_dir": str(paths.config_dir) if paths is not None else "",
            "tools_dir": str(paths.tools_dir) if paths is not None else "",
            "plugins_dir": str(paths.plugins_dir) if paths is not None else "",
        },
    )
    return ok(info)
