from __future__ import annotations

import re
import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from faceforge_core.api.models import ApiResponse, fail, ok
from faceforge_core.db.descriptors import (
    DescriptorRow,
    create_descriptor,
    get_descriptor,
    list_descriptors_for_entity,
    patch_descriptor_value,
    soft_delete_descriptor,
)
from faceforge_core.db.entities import get_entity
from faceforge_core.db.field_defs import FieldDefRow, get_field_def_by_key

router = APIRouter(tags=["descriptors"])


class Descriptor(BaseModel):
    descriptor_id: str
    entity_id: str
    scope: str
    field_key: str
    value: Any
    created_at: str
    updated_at: str


def _to_descriptor(row: DescriptorRow) -> Descriptor:
    return Descriptor(
        descriptor_id=row.descriptor_id,
        entity_id=row.entity_id,
        scope=row.scope,
        field_key=row.field_key,
        value=row.value,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


def _options_list(options: Any) -> list[str] | None:
    if isinstance(options, dict):
        v = options.get("options")
        if isinstance(v, list) and all(isinstance(x, str) for x in v):
            return v
    return None


def _validate_value(field_def: FieldDefRow, value: Any) -> list[str]:
    errors: list[str] = []

    if value is None:
        if field_def.required:
            errors.append("value is required")
        return errors

    t = (field_def.field_type or "").strip().lower()

    if t == "string":
        if not isinstance(value, str):
            errors.append("value must be a string")
        elif field_def.required and value == "":
            errors.append("value must not be empty")
        elif field_def.regex:
            try:
                if re.fullmatch(field_def.regex, value) is None:
                    errors.append("value does not match regex")
            except re.error:
                # Misconfigured regex should not silently accept bad values.
                errors.append("field definition regex is invalid")

    elif t in {"int", "integer"}:
        if isinstance(value, bool) or not isinstance(value, int):
            errors.append("value must be an integer")

    elif t in {"float", "number"}:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            errors.append("value must be a number")

    elif t in {"bool", "boolean"}:
        if not isinstance(value, bool):
            errors.append("value must be a boolean")

    elif t in {"enum", "option", "options"}:
        if not isinstance(value, str):
            errors.append("value must be a string")
        else:
            opts = _options_list(field_def.options)
            if not opts:
                errors.append("field definition has no options")
            elif value not in opts:
                errors.append("value must be one of the allowed options")

    elif t in {"json", "any"}:
        # Accept any JSON-serializable value.
        pass

    else:
        errors.append("unknown field_type")

    return errors


class DescriptorListResponse(BaseModel):
    items: list[Descriptor]


@router.get("/entities/{entity_id}/descriptors", response_model=ApiResponse[DescriptorListResponse])
async def entity_descriptors_list(
    request: Request,
    entity_id: str,
) -> ApiResponse[DescriptorListResponse]:
    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise HTTPException(status_code=500, detail="DB not initialized")

    entity = get_entity(db_path, entity_id=entity_id, include_deleted=False)
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    rows = list_descriptors_for_entity(db_path, entity_id=entity_id, include_deleted=False)
    return ok(DescriptorListResponse(items=[_to_descriptor(r) for r in rows]))


class DescriptorCreateRequest(BaseModel):
    scope: str = Field(default="descriptor", min_length=1)
    field_key: str = Field(min_length=1)
    value: Any = None


@router.post("/entities/{entity_id}/descriptors", response_model=ApiResponse[Descriptor])
async def entity_descriptors_create(
    request: Request,
    entity_id: str,
    payload: DescriptorCreateRequest,
) -> ApiResponse[Descriptor] | JSONResponse:
    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise HTTPException(status_code=500, detail="DB not initialized")

    entity = get_entity(db_path, entity_id=entity_id, include_deleted=False)
    if entity is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    field_def = get_field_def_by_key(
        db_path, scope=payload.scope, field_key=payload.field_key, include_deleted=False
    )
    if field_def is None:
        return JSONResponse(
            status_code=422,
            content=fail(
                code="validation_error",
                message="Unknown field definition",
                details={"scope": payload.scope, "field_key": payload.field_key},
            ).model_dump(mode="json"),
        )

    errors = _validate_value(field_def, payload.value)
    if errors:
        return JSONResponse(
            status_code=422,
            content=fail(
                code="validation_error",
                message="Invalid descriptor value",
                details={
                    "scope": payload.scope,
                    "field_key": payload.field_key,
                    "field_type": field_def.field_type,
                    "errors": errors,
                },
            ).model_dump(mode="json"),
        )

    try:
        row = create_descriptor(
            db_path,
            entity_id=entity_id,
            scope=payload.scope,
            field_key=payload.field_key,
            value=payload.value,
        )
    except sqlite3.IntegrityError as err:
        raise HTTPException(status_code=409, detail="Descriptor already exists") from err

    return ok(_to_descriptor(row))


class DescriptorPatchRequest(BaseModel):
    value: Any = None


@router.patch("/descriptors/{descriptor_id}", response_model=ApiResponse[Descriptor])
async def descriptors_patch(
    request: Request,
    descriptor_id: str,
    payload: DescriptorPatchRequest,
) -> ApiResponse[Descriptor] | JSONResponse:
    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise HTTPException(status_code=500, detail="DB not initialized")

    existing = get_descriptor(db_path, descriptor_id=descriptor_id, include_deleted=False)
    if existing is None:
        raise HTTPException(status_code=404, detail="Descriptor not found")

    field_def = get_field_def_by_key(
        db_path, scope=existing.scope, field_key=existing.field_key, include_deleted=False
    )
    if field_def is None:
        return JSONResponse(
            status_code=422,
            content=fail(
                code="validation_error",
                message="Unknown field definition",
                details={"scope": existing.scope, "field_key": existing.field_key},
            ).model_dump(mode="json"),
        )

    errors = _validate_value(field_def, payload.value)
    if errors:
        return JSONResponse(
            status_code=422,
            content=fail(
                code="validation_error",
                message="Invalid descriptor value",
                details={
                    "scope": existing.scope,
                    "field_key": existing.field_key,
                    "field_type": field_def.field_type,
                    "errors": errors,
                },
            ).model_dump(mode="json"),
        )

    row = patch_descriptor_value(db_path, descriptor_id=descriptor_id, value=payload.value)
    if row is None:
        raise HTTPException(status_code=404, detail="Descriptor not found")

    return ok(_to_descriptor(row))


class DeleteResponse(BaseModel):
    deleted: bool


@router.delete("/descriptors/{descriptor_id}", response_model=ApiResponse[DeleteResponse])
async def descriptors_delete(
    request: Request,
    descriptor_id: str,
) -> ApiResponse[DeleteResponse]:
    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise HTTPException(status_code=500, detail="DB not initialized")

    deleted = soft_delete_descriptor(db_path, descriptor_id=descriptor_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Descriptor not found")

    return ok(DeleteResponse(deleted=True))
