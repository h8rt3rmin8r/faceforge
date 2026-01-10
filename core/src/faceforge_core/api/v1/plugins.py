from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field

from faceforge_core.api.models import ApiResponse, fail, ok
from faceforge_core.db.plugins import (
    PluginRegistryRow,
    get_plugin_registry,
    list_plugin_registry,
    set_plugin_config,
    set_plugin_enabled,
    upsert_plugin_discovery,
)
from faceforge_core.plugins.discovery import discover_plugins

router = APIRouter(tags=["plugins"])


class Plugin(BaseModel):
    plugin_id: str
    name: str | None = None
    version: str | None = None
    enabled: bool
    discovered: bool
    config: Any = Field(default_factory=dict)
    config_schema: dict[str, Any] | None = None


def _registry_to_plugin(
    row: PluginRegistryRow,
    *,
    discovered: bool,
    name: str | None,
    schema: Any,
) -> Plugin:
    return Plugin(
        plugin_id=row.plugin_id,
        name=name,
        version=row.version,
        enabled=row.enabled,
        discovered=discovered,
        config=row.config if isinstance(row.config, dict) else {},
        config_schema=schema if isinstance(schema, dict) else None,
    )


def _validation_error_json(*, message: str, details: Any) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content=fail(
            code="validation_error",
            message=message,
            details=details,
        ).model_dump(mode="json"),
    )


def _validate_config(schema: dict[str, Any], config: Any) -> list[dict[str, Any]]:
    validator = Draft202012Validator(schema)
    errors: list[dict[str, Any]] = []
    for e in validator.iter_errors(config):
        errors.append(
            {
                "path": list(e.path),
                "message": e.message,
                "schema_path": list(e.schema_path),
                "validator": e.validator,
            }
        )
    errors.sort(key=lambda err: ("/".join(map(str, err.get("path", []))), err.get("message", "")))
    return errors


@router.get("/plugins", response_model=ApiResponse[dict[str, list[Plugin]]])
async def plugins_list(request: Request) -> ApiResponse[dict[str, list[Plugin]]]:
    db_path = getattr(request.app.state, "db_path", None)
    paths = getattr(request.app.state, "faceforge_paths", None)
    if db_path is None or paths is None:
        raise HTTPException(status_code=500, detail="Server not initialized")

    discovered = discover_plugins(plugins_dir=paths.plugins_dir)
    discovered_by_id = {p.manifest.id: p for p in discovered}

    # Ensure all discovered plugins have a registry row.
    for p in discovered:
        upsert_plugin_discovery(db_path, plugin_id=p.manifest.id, version=p.manifest.version)

    rows = list_plugin_registry(db_path, include_deleted=False)

    items: list[Plugin] = []
    for row in rows:
        d = discovered_by_id.get(row.plugin_id)
        items.append(
            _registry_to_plugin(
                row,
                discovered=d is not None,
                name=d.manifest.name if d else None,
                schema=d.manifest.config_schema if d else None,
            )
        )

    return ok({"items": items})


@router.post("/plugins/{plugin_id}/enable", response_model=ApiResponse[Plugin])
async def plugins_enable(request: Request, plugin_id: str) -> ApiResponse[Plugin]:
    db_path = getattr(request.app.state, "db_path", None)
    paths = getattr(request.app.state, "faceforge_paths", None)
    if db_path is None or paths is None:
        raise HTTPException(status_code=500, detail="Server not initialized")

    discovered = {p.manifest.id: p for p in discover_plugins(plugins_dir=paths.plugins_dir)}
    if plugin_id not in discovered:
        raise HTTPException(status_code=404, detail="Plugin not discovered")

    upsert_plugin_discovery(
        db_path,
        plugin_id=plugin_id,
        version=discovered[plugin_id].manifest.version,
    )
    row = set_plugin_enabled(db_path, plugin_id=plugin_id, enabled=True)
    if row is None:
        raise HTTPException(status_code=404, detail="Plugin not found")

    d = discovered[plugin_id]
    return ok(
        _registry_to_plugin(
            row,
            discovered=True,
            name=d.manifest.name,
            schema=d.manifest.config_schema,
        )
    )


@router.post("/plugins/{plugin_id}/disable", response_model=ApiResponse[Plugin])
async def plugins_disable(request: Request, plugin_id: str) -> ApiResponse[Plugin]:
    db_path = getattr(request.app.state, "db_path", None)
    paths = getattr(request.app.state, "faceforge_paths", None)
    if db_path is None or paths is None:
        raise HTTPException(status_code=500, detail="Server not initialized")

    discovered = {p.manifest.id: p for p in discover_plugins(plugins_dir=paths.plugins_dir)}
    if plugin_id not in discovered:
        raise HTTPException(status_code=404, detail="Plugin not discovered")

    upsert_plugin_discovery(
        db_path,
        plugin_id=plugin_id,
        version=discovered[plugin_id].manifest.version,
    )
    row = set_plugin_enabled(db_path, plugin_id=plugin_id, enabled=False)
    if row is None:
        raise HTTPException(status_code=404, detail="Plugin not found")

    d = discovered[plugin_id]
    return ok(
        _registry_to_plugin(
            row,
            discovered=True,
            name=d.manifest.name,
            schema=d.manifest.config_schema,
        )
    )


class PluginConfigResponse(BaseModel):
    plugin_id: str
    config: Any


@router.get("/plugins/{plugin_id}/config", response_model=ApiResponse[PluginConfigResponse])
async def plugins_get_config(request: Request, plugin_id: str) -> ApiResponse[PluginConfigResponse]:
    db_path = getattr(request.app.state, "db_path", None)
    paths = getattr(request.app.state, "faceforge_paths", None)
    if db_path is None:
        raise HTTPException(status_code=500, detail="DB not initialized")

    if paths is None:
        raise HTTPException(status_code=500, detail="Server not initialized")

    discovered = {p.manifest.id: p for p in discover_plugins(plugins_dir=paths.plugins_dir)}
    if plugin_id not in discovered:
        raise HTTPException(status_code=404, detail="Plugin not discovered")

    # Ensure registry row exists even if /v1/plugins has not been called yet.
    upsert_plugin_discovery(
        db_path,
        plugin_id=plugin_id,
        version=discovered[plugin_id].manifest.version,
    )

    row = get_plugin_registry(db_path, plugin_id=plugin_id, include_deleted=False)
    if row is None:
        raise HTTPException(status_code=404, detail="Plugin not found")

    return ok(
        PluginConfigResponse(
            plugin_id=plugin_id,
            config=row.config if isinstance(row.config, dict) else {},
        )
    )


class PluginConfigPutRequest(BaseModel):
    config: Any = Field(default_factory=dict)


@router.put("/plugins/{plugin_id}/config", response_model=ApiResponse[PluginConfigResponse])
async def plugins_put_config(
    request: Request,
    plugin_id: str,
    payload: PluginConfigPutRequest,
) -> ApiResponse[PluginConfigResponse] | JSONResponse:
    db_path = getattr(request.app.state, "db_path", None)
    paths = getattr(request.app.state, "faceforge_paths", None)
    if db_path is None or paths is None:
        raise HTTPException(status_code=500, detail="Server not initialized")

    discovered = {p.manifest.id: p for p in discover_plugins(plugins_dir=paths.plugins_dir)}
    if plugin_id not in discovered:
        raise HTTPException(status_code=404, detail="Plugin not discovered")

    # Ensure registry row exists even if /v1/plugins has not been called yet.
    upsert_plugin_discovery(
        db_path,
        plugin_id=plugin_id,
        version=discovered[plugin_id].manifest.version,
    )

    schema = discovered[plugin_id].manifest.config_schema
    if isinstance(schema, dict):
        errors = _validate_config(schema, payload.config)
        if errors:
            return _validation_error_json(
                message="Invalid plugin config",
                details={"plugin_id": plugin_id, "errors": errors},
            )

    row = set_plugin_config(db_path, plugin_id=plugin_id, config=payload.config)
    if row is None:
        raise HTTPException(status_code=404, detail="Plugin not found")

    return ok(
        PluginConfigResponse(
            plugin_id=plugin_id,
            config=row.config if isinstance(row.config, dict) else {},
        )
    )
