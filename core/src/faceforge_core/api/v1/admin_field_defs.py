from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from faceforge_core.api.models import ApiResponse, ok
from faceforge_core.db.field_defs import (
    FieldDefRow,
    create_field_def,
    get_field_def,
    list_field_defs,
    patch_field_def,
    soft_delete_field_def,
)

router = APIRouter(tags=["admin"])


class FieldDef(BaseModel):
    field_def_id: str
    scope: str
    field_key: str
    field_type: str
    required: bool
    options: Any = Field(default_factory=dict)
    regex: str | None = None
    created_at: str
    updated_at: str


def _to_field_def(row: FieldDefRow) -> FieldDef:
    return FieldDef(
        field_def_id=row.field_def_id,
        scope=row.scope,
        field_key=row.field_key,
        field_type=row.field_type,
        required=row.required,
        options=row.options,
        regex=row.regex,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


class FieldDefListResponse(BaseModel):
    items: list[FieldDef]


@router.get("/admin/field-defs", response_model=ApiResponse[FieldDefListResponse])
async def field_defs_list(
    request: Request,
    scope: str | None = Query(default=None, description="Optional scope filter"),
) -> ApiResponse[FieldDefListResponse]:
    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise HTTPException(status_code=500, detail="DB not initialized")

    rows = list_field_defs(db_path, scope=scope, include_deleted=False)
    return ok(FieldDefListResponse(items=[_to_field_def(r) for r in rows]))


@router.get("/admin/field-defs/{field_def_id}", response_model=ApiResponse[FieldDef])
async def field_defs_get(request: Request, field_def_id: str) -> ApiResponse[FieldDef]:
    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise HTTPException(status_code=500, detail="DB not initialized")

    row = get_field_def(db_path, field_def_id=field_def_id, include_deleted=False)
    if row is None:
        raise HTTPException(status_code=404, detail="Field definition not found")

    return ok(_to_field_def(row))


class FieldDefCreateRequest(BaseModel):
    scope: str = Field(default="descriptor", min_length=1)
    field_key: str = Field(min_length=1)
    field_type: str = Field(min_length=1)
    required: bool = False
    options: Any = Field(default_factory=dict)
    regex: str | None = None


@router.post("/admin/field-defs", response_model=ApiResponse[FieldDef])
async def field_defs_create(
    request: Request,
    payload: FieldDefCreateRequest,
) -> ApiResponse[FieldDef]:
    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise HTTPException(status_code=500, detail="DB not initialized")

    try:
        row = create_field_def(
            db_path,
            scope=payload.scope,
            field_key=payload.field_key,
            field_type=payload.field_type,
            required=payload.required,
            options=payload.options,
            regex=payload.regex,
        )
    except sqlite3.IntegrityError as err:
        raise HTTPException(
            status_code=409,
            detail="Field definition already exists",
        ) from err

    return ok(_to_field_def(row))


class FieldDefPatchRequest(BaseModel):
    scope: str | None = Field(default=None, min_length=1)
    field_key: str | None = Field(default=None, min_length=1)
    field_type: str | None = Field(default=None, min_length=1)
    required: bool | None = None
    options: Any | None = None
    regex: str | None = None


@router.patch("/admin/field-defs/{field_def_id}", response_model=ApiResponse[FieldDef])
async def field_defs_patch(
    request: Request,
    field_def_id: str,
    payload: FieldDefPatchRequest,
) -> ApiResponse[FieldDef]:
    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise HTTPException(status_code=500, detail="DB not initialized")

    try:
        row = patch_field_def(
            db_path,
            field_def_id=field_def_id,
            scope=payload.scope,
            field_key=payload.field_key,
            field_type=payload.field_type,
            required=payload.required,
            options=payload.options,
            regex=payload.regex,
        )
    except sqlite3.IntegrityError as err:
        raise HTTPException(
            status_code=409,
            detail="Field definition already exists",
        ) from err

    if row is None:
        raise HTTPException(status_code=404, detail="Field definition not found")

    return ok(_to_field_def(row))


class DeleteResponse(BaseModel):
    deleted: bool


@router.delete("/admin/field-defs/{field_def_id}", response_model=ApiResponse[DeleteResponse])
async def field_defs_delete(request: Request, field_def_id: str) -> ApiResponse[DeleteResponse]:
    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise HTTPException(status_code=500, detail="DB not initialized")

    deleted = soft_delete_field_def(db_path, field_def_id=field_def_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Field definition not found")

    return ok(DeleteResponse(deleted=True))
