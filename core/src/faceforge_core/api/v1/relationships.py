from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from faceforge_core.api.models import ApiResponse, ok
from faceforge_core.db.entities import get_entity
from faceforge_core.db.relationships import (
    RelationshipRow,
    create_relationship,
    list_relationship_types,
    list_relationships_for_entity,
    soft_delete_relationship,
)

router = APIRouter(tags=["relationships"])


RELATION_TYPE_SEED: list[str] = [
    "friend",
    "family",
    "parent",
    "child",
    "sibling",
    "spouse",
    "partner",
    "coworker",
    "manager",
    "subordinate",
    "mentor",
    "student",
]


class Relationship(BaseModel):
    relationship_id: str
    src_entity_id: str
    dst_entity_id: str
    relationship_type: str
    fields: dict[str, Any] = Field(default_factory=dict)
    created_at: str


def _to_relationship(row: RelationshipRow) -> Relationship:
    return Relationship(
        relationship_id=row.relationship_id,
        src_entity_id=row.src_entity_id,
        dst_entity_id=row.dst_entity_id,
        relationship_type=row.relationship_type,
        fields=row.fields,
        created_at=row.created_at,
    )


class RelationshipCreateRequest(BaseModel):
    src_entity_id: str = Field(min_length=1)
    dst_entity_id: str = Field(min_length=1)
    relationship_type: str = Field(min_length=1)
    fields: dict[str, Any] = Field(default_factory=dict)


@router.post("/relationships", response_model=ApiResponse[Relationship])
async def relationships_create(
    request: Request,
    payload: RelationshipCreateRequest,
) -> ApiResponse[Relationship]:
    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise HTTPException(status_code=500, detail="DB not initialized")

    src = get_entity(db_path, entity_id=payload.src_entity_id, include_deleted=False)
    if src is None:
        raise HTTPException(status_code=404, detail="Source entity not found")

    dst = get_entity(db_path, entity_id=payload.dst_entity_id, include_deleted=False)
    if dst is None:
        raise HTTPException(status_code=404, detail="Destination entity not found")

    row = create_relationship(
        db_path,
        src_entity_id=payload.src_entity_id,
        dst_entity_id=payload.dst_entity_id,
        relationship_type=payload.relationship_type.strip(),
        fields=payload.fields,
    )
    return ok(_to_relationship(row))


class RelationshipListResponse(BaseModel):
    items: list[Relationship]


@router.get("/relationships", response_model=ApiResponse[RelationshipListResponse])
async def relationships_list(
    request: Request,
    entity_id: str = Query(..., min_length=1, description="Entity ID to query relationships for"),
) -> ApiResponse[RelationshipListResponse]:
    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise HTTPException(status_code=500, detail="DB not initialized")

    entity = get_entity(db_path, entity_id=entity_id, include_deleted=False)
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    rows = list_relationships_for_entity(db_path, entity_id=entity_id, include_deleted=False)
    return ok(RelationshipListResponse(items=[_to_relationship(r) for r in rows]))


class DeleteResponse(BaseModel):
    deleted: bool


@router.delete(
    "/relationships/{relationship_id}",
    response_model=ApiResponse[DeleteResponse],
)
async def relationships_delete(
    request: Request,
    relationship_id: str,
) -> ApiResponse[DeleteResponse]:
    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise HTTPException(status_code=500, detail="DB not initialized")

    deleted = soft_delete_relationship(db_path, relationship_id=relationship_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Relationship not found")

    return ok(DeleteResponse(deleted=True))


class RelationTypesResponse(BaseModel):
    items: list[str]


def _dedupe_casefold(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for s in items:
        key = s.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


@router.get("/relation-types", response_model=ApiResponse[RelationTypesResponse])
async def relation_types_suggest(
    request: Request,
    query: str | None = Query(default=None, description="Substring match against relation type"),
    limit: int = Query(default=20, ge=1, le=200),
) -> ApiResponse[RelationTypesResponse]:
    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise HTTPException(status_code=500, detail="DB not initialized")

    q = (query or "").strip()
    q_cf = q.casefold()

    # Start with seeds so first-run UX isn't empty.
    seeds = RELATION_TYPE_SEED
    if q:
        seeds = [s for s in seeds if q_cf in s.casefold()]

    # Pull DB-backed types (distinct) and merge.
    # We apply the same substring filter at the DB level for efficiency.
    db_types = list_relationship_types(db_path, query=q, limit=limit, include_deleted=False)

    merged = _dedupe_casefold([*seeds, *db_types])

    # Rank: prefix matches first, then substring matches, then alphabetically.
    if q:
        starts = [s for s in merged if s.casefold().startswith(q_cf)]
        rest = [s for s in merged if not s.casefold().startswith(q_cf)]
        merged = sorted(starts, key=str.casefold) + sorted(rest, key=str.casefold)
    else:
        merged = sorted(merged, key=str.casefold)

    return ok(RelationTypesResponse(items=merged[:limit]))
