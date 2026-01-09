from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from faceforge_core.api.models import ApiResponse, ok
from faceforge_core.db.assets import get_asset, link_asset_to_entity, unlink_asset_from_entity
from faceforge_core.db.entities import (
    EntityRow,
    create_entity,
    get_entity,
    list_entities,
    patch_entity,
    soft_delete_entity,
)

router = APIRouter(tags=["entities"])


class Entity(BaseModel):
    entity_id: str
    display_name: str
    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    fields: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


def _to_entity(row: EntityRow) -> Entity:
    return Entity(
        entity_id=row.entity_id,
        display_name=row.display_name,
        aliases=row.aliases,
        tags=row.tags,
        fields=row.fields,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class EntityCreateRequest(BaseModel):
    display_name: str = Field(min_length=1)
    aliases: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    fields: dict[str, Any] = Field(default_factory=dict)


class EntityPatchRequest(BaseModel):
    display_name: str | None = Field(default=None, min_length=1)
    aliases: list[str] | None = None
    tags: list[str] | None = None
    fields: dict[str, Any] | None = None


class EntityListResponse(BaseModel):
    items: list[Entity]
    total: int
    limit: int
    offset: int


@router.get("/entities", response_model=ApiResponse[EntityListResponse])
async def entities_list(
    request: Request,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    sort_by: Literal["created_at", "updated_at", "display_name"] = "created_at",
    sort_order: Literal["asc", "desc"] = "desc",
    q: str | None = Query(default=None, description="Substring match against basic fields"),
    tag: str | None = Query(default=None, description="Filter by tag (exact tag string)"),
) -> ApiResponse[EntityListResponse]:
    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise HTTPException(status_code=500, detail="DB not initialized")

    result = list_entities(
        db_path,
        limit=limit,
        offset=offset,
        sort_by=sort_by,
        sort_order=sort_order,
        q=q,
        tag=tag,
    )

    return ok(
        EntityListResponse(
            items=[_to_entity(r) for r in result.items],
            total=result.total,
            limit=limit,
            offset=offset,
        )
    )


@router.post("/entities", response_model=ApiResponse[Entity])
async def entities_create(
    request: Request,
    payload: EntityCreateRequest,
) -> ApiResponse[Entity]:
    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise HTTPException(status_code=500, detail="DB not initialized")

    row = create_entity(
        db_path,
        display_name=payload.display_name,
        aliases=payload.aliases,
        tags=payload.tags,
        fields=payload.fields,
    )
    return ok(_to_entity(row))


@router.get("/entities/{entity_id}", response_model=ApiResponse[Entity])
async def entities_get(request: Request, entity_id: str) -> ApiResponse[Entity]:
    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise HTTPException(status_code=500, detail="DB not initialized")

    row = get_entity(db_path, entity_id=entity_id, include_deleted=False)
    if row is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    return ok(_to_entity(row))


@router.patch("/entities/{entity_id}", response_model=ApiResponse[Entity])
async def entities_patch(
    request: Request,
    entity_id: str,
    payload: EntityPatchRequest,
) -> ApiResponse[Entity]:
    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise HTTPException(status_code=500, detail="DB not initialized")

    row = patch_entity(
        db_path,
        entity_id=entity_id,
        display_name=payload.display_name,
        aliases=payload.aliases,
        tags=payload.tags,
        fields=payload.fields,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    return ok(_to_entity(row))


class DeleteResponse(BaseModel):
    deleted: bool


@router.delete("/entities/{entity_id}", response_model=ApiResponse[DeleteResponse])
async def entities_delete(request: Request, entity_id: str) -> ApiResponse[DeleteResponse]:
    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise HTTPException(status_code=500, detail="DB not initialized")

    deleted = soft_delete_entity(db_path, entity_id=entity_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Entity not found")

    return ok(DeleteResponse(deleted=True))


class EntityAssetLinkRequest(BaseModel):
    role: str | None = None


class EntityAssetLinkResponse(BaseModel):
    linked: bool


@router.post(
    "/entities/{entity_id}/assets/{asset_id}",
    response_model=ApiResponse[EntityAssetLinkResponse],
)
async def entity_assets_link(
    request: Request,
    entity_id: str,
    asset_id: str,
    payload: EntityAssetLinkRequest,
) -> ApiResponse[EntityAssetLinkResponse]:
    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise HTTPException(status_code=500, detail="DB not initialized")

    entity = get_entity(db_path, entity_id=entity_id, include_deleted=False)
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    asset = get_asset(db_path, asset_id=asset_id, include_deleted=False)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    link_asset_to_entity(db_path, entity_id=entity_id, asset_id=asset_id, role=payload.role)
    return ok(EntityAssetLinkResponse(linked=True))


@router.delete(
    "/entities/{entity_id}/assets/{asset_id}",
    response_model=ApiResponse[EntityAssetLinkResponse],
)
async def entity_assets_unlink(
    request: Request,
    entity_id: str,
    asset_id: str,
) -> ApiResponse[EntityAssetLinkResponse]:
    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise HTTPException(status_code=500, detail="DB not initialized")

    entity = get_entity(db_path, entity_id=entity_id, include_deleted=False)
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    asset = get_asset(db_path, asset_id=asset_id, include_deleted=False)
    if asset is None:
        raise HTTPException(status_code=404, detail="Asset not found")

    removed = unlink_asset_from_entity(db_path, entity_id=entity_id, asset_id=asset_id)
    return ok(EntityAssetLinkResponse(linked=removed))
