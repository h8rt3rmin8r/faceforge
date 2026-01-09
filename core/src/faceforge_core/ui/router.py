from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from jsonschema import Draft202012Validator
from starlette.responses import Response

from faceforge_core.auth import TOKEN_COOKIE
from faceforge_core.db.assets import (
    get_asset,
    link_asset_to_entity,
    list_assets_for_entity,
    unlink_asset_from_entity,
)
from faceforge_core.db.descriptors import list_descriptors_for_entity, soft_delete_descriptor
from faceforge_core.db.entities import (
    create_entity,
    get_entity,
    list_entities,
    patch_entity,
    soft_delete_entity,
)
from faceforge_core.db.field_defs import create_field_def, get_field_def_by_key, list_field_defs
from faceforge_core.db.jobs import (
    append_job_log,
    get_job,
    list_job_logs,
    list_jobs,
    request_job_cancel,
)
from faceforge_core.db.plugins import (
    list_plugin_registry,
    set_plugin_config,
    set_plugin_enabled,
    upsert_plugin_discovery,
)
from faceforge_core.db.relationships import (
    create_relationship,
    list_relationships_for_entity,
    soft_delete_relationship,
)
from faceforge_core.plugins.discovery import discover_plugins

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

router = APIRouter(prefix="/ui", tags=["ui"])


def _flash_from_request(request: Request) -> dict[str, Any] | None:
    msg = request.query_params.get("msg")
    if not msg:
        return None
    kind = request.query_params.get("kind") or ""
    return {"message": msg, "kind": kind}


def _split_csv(raw: str | None) -> list[str]:
    if not raw:
        return []
    out: list[str] = []
    for part in raw.split(","):
        s = part.strip()
        if s:
            out.append(s)
    return out


def _parse_json(raw: str | None, *, default: Any) -> Any:
    text = (raw or "").strip()
    if not text:
        return default
    return json.loads(text)


def _get_db_path(request: Request) -> Any:
    db_path = getattr(request.app.state, "db_path", None)
    if db_path is None:
        raise HTTPException(status_code=500, detail="DB not initialized")
    return db_path


def _get_expected_token(request: Request) -> str:
    expected = getattr(getattr(request.app.state, "faceforge_config", None), "auth", None)
    token = getattr(expected, "install_token", None)
    if not token:
        raise HTTPException(status_code=500, detail="Server auth token not initialized")
    return str(token)


@router.get("/login", response_class=HTMLResponse)
async def ui_login(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "login.html",
        {"title": "Login • FaceForge", "hide_nav": True, "no_static": True, "active": None},
    )


@router.post("/login", response_model=None)
async def ui_login_post(request: Request, token: str = Form(...)) -> Response:
    expected = _get_expected_token(request)
    token = (token or "").strip()

    if not token:
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "title": "Login • FaceForge",
                "hide_nav": True,
                "no_static": True,
                "error": "Missing token",
            },
            status_code=400,
        )

    if token != expected:
        return templates.TemplateResponse(
            request,
            "login.html",
            {
                "title": "Login • FaceForge",
                "hide_nav": True,
                "no_static": True,
                "error": "Invalid token",
            },
            status_code=401,
        )

    resp = RedirectResponse(url="/ui/entities?msg=Logged+in&kind=ok", status_code=302)
    resp.set_cookie(
        TOKEN_COOKIE,
        token,
        httponly=True,
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    return resp


@router.post("/logout")
async def ui_logout() -> RedirectResponse:
    resp = RedirectResponse(url="/ui/login?msg=Logged+out", status_code=302)
    resp.delete_cookie(TOKEN_COOKIE)
    return resp


@router.get("/entities", response_class=HTMLResponse)
async def ui_entities_list(request: Request) -> HTMLResponse:
    db_path = _get_db_path(request)

    q = request.query_params.get("q")
    view = (request.query_params.get("view") or "table").strip().lower()
    if view not in {"table", "gallery"}:
        view = "table"

    result = list_entities(
        db_path,
        limit=200,
        offset=0,
        sort_by="created_at",
        sort_order="desc",
        q=q,
        tag=None,
    )

    items = [
        {
            "entity_id": r.entity_id,
            "display_name": r.display_name,
            "aliases": r.aliases,
            "tags": r.tags,
            "created_at": r.created_at,
            "updated_at": r.updated_at,
        }
        for r in result.items
    ]

    return templates.TemplateResponse(
        request,
        "entities_list.html",
        {
            "title": "Entities • FaceForge",
            "active": "entities",
            "flash": _flash_from_request(request),
            "items": items,
            "total": result.total,
            "q": q,
            "view": view,
        },
    )


@router.post("/entities/create")
async def ui_entities_create(
    request: Request,
    display_name: str = Form(...),
    tags: str = Form(default=""),
    aliases: str = Form(default=""),
    fields_json: str = Form(default="{}"),
) -> RedirectResponse:
    db_path = _get_db_path(request)

    try:
        fields = _parse_json(fields_json, default={})
        if not isinstance(fields, dict):
            raise ValueError("fields must be an object")
    except Exception:
        return RedirectResponse(
            url="/ui/entities?msg=Invalid+fields+JSON&kind=bad", status_code=302
        )

    row = create_entity(
        db_path,
        display_name=display_name.strip(),
        aliases=_split_csv(aliases),
        tags=_split_csv(tags),
        fields=fields,
    )
    return RedirectResponse(
        url=f"/ui/entities/{row.entity_id}?msg=Entity+created&kind=ok", status_code=302
    )


@router.get("/entities/{entity_id}", response_class=HTMLResponse)
async def ui_entity_detail(request: Request, entity_id: str) -> HTMLResponse:
    db_path = _get_db_path(request)

    tab = (request.query_params.get("tab") or "overview").strip().lower()
    if tab not in {"overview", "descriptors", "attachments", "relationships"}:
        tab = "overview"

    row = get_entity(db_path, entity_id=entity_id, include_deleted=False)
    if row is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    entity = {
        "entity_id": row.entity_id,
        "display_name": row.display_name,
        "aliases": row.aliases,
        "tags": row.tags,
        "fields": row.fields,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }

    ctx: dict[str, Any] = {
        "title": f"{row.display_name} • FaceForge",
        "active": "entities",
        "flash": _flash_from_request(request),
        "entity": entity,
        "tab": tab,
        "fields_json": json.dumps(row.fields or {}, ensure_ascii=False, indent=2),
        "descriptors": [],
        "field_defs": [],
        "assets": [],
        "relationships": [],
    }

    if tab == "descriptors":
        desc = list_descriptors_for_entity(db_path, entity_id=entity_id, include_deleted=False)
        ctx["descriptors"] = [
            {
                "descriptor_id": d.descriptor_id,
                "scope": d.scope,
                "field_key": d.field_key,
                "value_json": json.dumps(d.value, ensure_ascii=False, indent=2),
            }
            for d in desc
        ]
        fds = list_field_defs(db_path, scope="descriptor", include_deleted=False)
        ctx["field_defs"] = [{"field_key": fd.field_key} for fd in fds]

    if tab == "attachments":
        links = list_assets_for_entity(db_path, entity_id=entity_id)
        ctx["assets"] = [
            {
                "asset_id": x.asset.asset_id,
                "filename": x.asset.filename,
                "kind": x.asset.kind,
                "byte_size": x.asset.byte_size,
            }
            for x in links
        ]

    if tab == "relationships":
        rels = list_relationships_for_entity(db_path, entity_id=entity_id, include_deleted=False)
        ctx["relationships"] = [
            {
                "relationship_id": r.relationship_id,
                "src_entity_id": r.src_entity_id,
                "dst_entity_id": r.dst_entity_id,
                "relationship_type": r.relationship_type,
                "fields_json": json.dumps(r.fields or {}, ensure_ascii=False, indent=2),
            }
            for r in rels
        ]

    return templates.TemplateResponse(request, "entity_detail.html", ctx)


@router.post("/entities/{entity_id}/update")
async def ui_entity_update(
    request: Request,
    entity_id: str,
    display_name: str = Form(...),
    tags: str = Form(default=""),
    aliases: str = Form(default=""),
    fields_json: str = Form(default="{}"),
) -> RedirectResponse:
    db_path = _get_db_path(request)

    try:
        fields = _parse_json(fields_json, default={})
        if not isinstance(fields, dict):
            raise ValueError("fields must be an object")
    except Exception:
        return RedirectResponse(
            url=f"/ui/entities/{entity_id}?tab=overview&msg=Invalid+fields+JSON&kind=bad",
            status_code=302,
        )

    updated = patch_entity(
        db_path,
        entity_id=entity_id,
        display_name=display_name.strip(),
        tags=_split_csv(tags),
        aliases=_split_csv(aliases),
        fields=fields,
    )
    if updated is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    return RedirectResponse(
        url=f"/ui/entities/{entity_id}?tab=overview&msg=Saved&kind=ok",
        status_code=302,
    )


@router.post("/entities/{entity_id}/delete")
async def ui_entity_delete(request: Request, entity_id: str) -> RedirectResponse:
    db_path = _get_db_path(request)
    deleted = soft_delete_entity(db_path, entity_id=entity_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Entity not found")
    return RedirectResponse(url="/ui/entities?msg=Entity+deleted&kind=ok", status_code=302)


@router.post("/field-defs/create")
async def ui_field_defs_create(
    request: Request,
    scope: str = Form(default="descriptor"),
    field_key: str = Form(...),
    field_type: str = Form(...),
    required: str = Form(default="false"),
    options_json: str = Form(default="{}"),
    regex: str = Form(default=""),
    return_to: str = Form(default="/ui/entities"),
) -> RedirectResponse:
    db_path = _get_db_path(request)

    try:
        options = _parse_json(options_json, default={})
    except Exception:
        return RedirectResponse(
            url=f"{return_to}&msg=Invalid+options+JSON&kind=bad", status_code=302
        )

    req_bool = (required or "").strip().lower() == "true"
    regex2 = (regex or "").strip() or None

    try:
        create_field_def(
            db_path,
            scope=scope.strip(),
            field_key=field_key.strip(),
            field_type=field_type.strip(),
            required=req_bool,
            options=options,
            regex=regex2,
        )
    except sqlite3.IntegrityError:
        return RedirectResponse(
            url=f"{return_to}&msg=Field+def+already+exists&kind=bad", status_code=302
        )

    return RedirectResponse(url=f"{return_to}&msg=Field+def+created&kind=ok", status_code=302)


@router.post("/entities/{entity_id}/descriptors/create")
async def ui_descriptors_create(
    request: Request,
    entity_id: str,
    scope: str = Form(default="descriptor"),
    field_key: str = Form(...),
    value_json: str = Form(default="null"),
) -> RedirectResponse:
    db_path = _get_db_path(request)

    # Validate against field definition (matches API behavior).
    fd = get_field_def_by_key(
        db_path, scope=scope.strip(), field_key=field_key.strip(), include_deleted=False
    )
    if fd is None:
        return RedirectResponse(
            url=f"/ui/entities/{entity_id}?tab=descriptors&msg=Unknown+field+definition&kind=bad",
            status_code=302,
        )

    try:
        value = _parse_json(value_json, default=None)
    except Exception:
        return RedirectResponse(
            url=f"/ui/entities/{entity_id}?tab=descriptors&msg=Invalid+value+JSON&kind=bad",
            status_code=302,
        )

    # Reuse the same validation rules as the API.
    from faceforge_core.api.v1.descriptors import _validate_value  # noqa: PLC0415

    errors = _validate_value(fd, value)
    if errors:
        return RedirectResponse(
            url=f"/ui/entities/{entity_id}?tab=descriptors&msg=Invalid+value&kind=bad",
            status_code=302,
        )

    from faceforge_core.db.descriptors import create_descriptor  # noqa: PLC0415

    try:
        create_descriptor(
            db_path,
            entity_id=entity_id,
            scope=scope.strip(),
            field_key=field_key.strip(),
            value=value,
        )
    except sqlite3.IntegrityError:
        return RedirectResponse(
            url=f"/ui/entities/{entity_id}?tab=descriptors&msg=Descriptor+already+exists&kind=bad",
            status_code=302,
        )

    return RedirectResponse(
        url=f"/ui/entities/{entity_id}?tab=descriptors&msg=Descriptor+added&kind=ok",
        status_code=302,
    )


@router.post("/descriptors/{descriptor_id}/delete")
async def ui_descriptors_delete(
    request: Request,
    descriptor_id: str,
    entity_id: str = Form(...),
) -> RedirectResponse:
    db_path = _get_db_path(request)
    deleted = soft_delete_descriptor(db_path, descriptor_id=descriptor_id)
    if not deleted:
        return RedirectResponse(
            url=f"/ui/entities/{entity_id}?tab=descriptors&msg=Descriptor+not+found&kind=bad",
            status_code=302,
        )

    return RedirectResponse(
        url=f"/ui/entities/{entity_id}?tab=descriptors&msg=Descriptor+deleted&kind=ok",
        status_code=302,
    )


@router.post("/entities/{entity_id}/attachments/upload")
async def ui_attachments_upload(
    request: Request,
    background_tasks: BackgroundTasks,
    entity_id: str,
    kind: str = Form(default="file"),
    role: str = Form(default=""),
    file: UploadFile = File(...),  # noqa: B008
    meta: UploadFile | None = File(default=None),  # noqa: B008
) -> RedirectResponse:
    db_path = _get_db_path(request)

    # Reuse the API upload implementation.
    from faceforge_core.api.v1.assets import assets_upload  # noqa: PLC0415

    api_resp = await assets_upload(
        request=request,
        background_tasks=background_tasks,
        kind=kind,
        file=file,
        meta=meta,
    )

    asset_id = getattr(getattr(api_resp, "data", None), "asset_id", None)
    if not asset_id:
        return RedirectResponse(
            url=f"/ui/entities/{entity_id}?tab=attachments&msg=Upload+failed&kind=bad",
            status_code=302,
        )

    # Link it to the entity.
    if get_entity(db_path, entity_id=entity_id, include_deleted=False) is None:
        return RedirectResponse(
            url=f"/ui/entities/{entity_id}?tab=attachments&msg=Entity+not+found&kind=bad",
            status_code=302,
        )

    if get_asset(db_path, asset_id=asset_id, include_deleted=False) is None:
        return RedirectResponse(
            url=f"/ui/entities/{entity_id}?tab=attachments&msg=Asset+not+found&kind=bad",
            status_code=302,
        )

    link_asset_to_entity(
        db_path, entity_id=entity_id, asset_id=asset_id, role=(role or "").strip() or None
    )

    return RedirectResponse(
        url=f"/ui/entities/{entity_id}?tab=attachments&msg=Uploaded+and+linked&kind=ok",
        status_code=302,
    )


@router.post("/entities/{entity_id}/attachments/link-existing")
async def ui_attachments_link_existing(
    request: Request,
    entity_id: str,
    asset_id: str = Form(...),
    role: str = Form(default=""),
) -> RedirectResponse:
    db_path = _get_db_path(request)

    if get_entity(db_path, entity_id=entity_id, include_deleted=False) is None:
        return RedirectResponse(
            url=f"/ui/entities/{entity_id}?tab=attachments&msg=Entity+not+found&kind=bad",
            status_code=302,
        )

    if get_asset(db_path, asset_id=asset_id.strip(), include_deleted=False) is None:
        return RedirectResponse(
            url=f"/ui/entities/{entity_id}?tab=attachments&msg=Asset+not+found&kind=bad",
            status_code=302,
        )

    link_asset_to_entity(
        db_path, entity_id=entity_id, asset_id=asset_id.strip(), role=(role or "").strip() or None
    )
    return RedirectResponse(
        url=f"/ui/entities/{entity_id}?tab=attachments&msg=Linked&kind=ok",
        status_code=302,
    )


@router.post("/entities/{entity_id}/attachments/unlink")
async def ui_attachments_unlink(
    request: Request,
    entity_id: str,
    asset_id: str = Form(...),
) -> RedirectResponse:
    db_path = _get_db_path(request)
    unlink_asset_from_entity(db_path, entity_id=entity_id, asset_id=asset_id.strip())
    return RedirectResponse(
        url=f"/ui/entities/{entity_id}?tab=attachments&msg=Unlinked&kind=ok",
        status_code=302,
    )


@router.post("/entities/{entity_id}/relationships/create")
async def ui_relationships_create(
    request: Request,
    entity_id: str,
    dst_entity_id: str = Form(...),
    relationship_type: str = Form(...),
    fields_json: str = Form(default="{}"),
) -> RedirectResponse:
    db_path = _get_db_path(request)

    if get_entity(db_path, entity_id=entity_id, include_deleted=False) is None:
        raise HTTPException(status_code=404, detail="Entity not found")

    if get_entity(db_path, entity_id=dst_entity_id.strip(), include_deleted=False) is None:
        return RedirectResponse(
            url=f"/ui/entities/{entity_id}?tab=relationships&msg=Destination+entity+not+found&kind=bad",
            status_code=302,
        )

    try:
        fields = _parse_json(fields_json, default={})
        if not isinstance(fields, dict):
            raise ValueError("fields must be an object")
    except Exception:
        return RedirectResponse(
            url=f"/ui/entities/{entity_id}?tab=relationships&msg=Invalid+fields+JSON&kind=bad",
            status_code=302,
        )

    create_relationship(
        db_path,
        src_entity_id=entity_id,
        dst_entity_id=dst_entity_id.strip(),
        relationship_type=relationship_type.strip(),
        fields=fields,
    )

    return RedirectResponse(
        url=f"/ui/entities/{entity_id}?tab=relationships&msg=Relationship+created&kind=ok",
        status_code=302,
    )


@router.post("/relationships/{relationship_id}/delete")
async def ui_relationships_delete(
    request: Request,
    relationship_id: str,
    entity_id: str = Form(...),
) -> RedirectResponse:
    db_path = _get_db_path(request)
    soft_delete_relationship(db_path, relationship_id=relationship_id)
    return RedirectResponse(
        url=f"/ui/entities/{entity_id}?tab=relationships&msg=Relationship+deleted&kind=ok",
        status_code=302,
    )


@router.get("/jobs", response_class=HTMLResponse)
async def ui_jobs_list(request: Request) -> HTMLResponse:
    db_path = _get_db_path(request)

    result = list_jobs(db_path, limit=200, offset=0)
    items = [
        {
            "job_id": j.job_id,
            "job_type": j.job_type,
            "status": j.status,
            "progress_percent": j.progress_percent,
            "progress_step": j.progress_step,
        }
        for j in result.items
    ]

    return templates.TemplateResponse(
        request,
        "jobs_list.html",
        {
            "title": "Jobs • FaceForge",
            "active": "jobs",
            "flash": _flash_from_request(request),
            "items": items,
            "total": result.total,
        },
    )


@router.post("/jobs/bulk-import")
async def ui_jobs_bulk_import(
    request: Request,
    path: str = Form(...),
    recursive: str = Form(default="true"),
    kind: str = Form(default="file"),
) -> RedirectResponse:
    from faceforge_core.api.v1.assets import BulkImportRequest, assets_bulk_import  # noqa: PLC0415

    payload = BulkImportRequest(
        path=path.strip(),
        recursive=(recursive or "").strip().lower() == "true",
        kind=(kind or "file").strip() or "file",
    )

    resp = await assets_bulk_import(request=request, payload=payload)
    job_id = getattr(getattr(resp, "data", None), "job_id", None)
    if not job_id:
        return RedirectResponse(url="/ui/jobs?msg=Failed+to+start+job&kind=bad", status_code=302)

    return RedirectResponse(url=f"/ui/jobs/{job_id}?msg=Job+started&kind=ok", status_code=302)


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
async def ui_job_detail(request: Request, job_id: str) -> HTMLResponse:
    db_path = _get_db_path(request)

    job = get_job(db_path, job_id=job_id, include_deleted=False)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")

    logs = list_job_logs(db_path, job_id=job_id, after_id=0, limit=500)

    refresh = request.query_params.get("refresh")
    refresh_s: int | None = None
    if refresh:
        try:
            refresh_s = max(1, min(30, int(refresh)))
        except ValueError:
            refresh_s = None

    return templates.TemplateResponse(
        request,
        "job_detail.html",
        {
            "title": f"Job {job_id} • FaceForge",
            "active": "jobs",
            "flash": _flash_from_request(request),
            "refresh_s": refresh_s,
            "job": {
                "job_id": job.job_id,
                "job_type": job.job_type,
                "status": job.status,
                "progress_percent": job.progress_percent,
                "progress_step": job.progress_step,
                "created_at": job.created_at,
                "started_at": job.started_at,
                "finished_at": job.finished_at,
            },
            "logs": [
                {
                    "job_log_id": log.job_log_id,
                    "ts": log.ts,
                    "level": log.level,
                    "message": log.message,
                    "data_json": (
                        json.dumps(log.data, ensure_ascii=False, indent=2)
                        if log.data is not None
                        else ""
                    ),
                }
                for log in logs
            ],
        },
    )


@router.post("/jobs/{job_id}/cancel")
async def ui_job_cancel(request: Request, job_id: str) -> RedirectResponse:
    db_path = _get_db_path(request)

    ok_cancel = request_job_cancel(db_path, job_id=job_id)
    if ok_cancel:
        append_job_log(db_path, job_id=job_id, level="info", message="Cancel requested")
        return RedirectResponse(
            url=f"/ui/jobs/{job_id}?msg=Cancel+requested&kind=ok", status_code=302
        )

    return RedirectResponse(url=f"/ui/jobs/{job_id}?msg=Cannot+cancel&kind=bad", status_code=302)


@dataclass(frozen=True)
class PluginConfigField:
    key: str
    input: str
    required: bool
    description: str | None
    enum: list[str] | None
    value: Any
    value_json: str


def _schema_fields(schema: dict[str, Any], config: dict[str, Any]) -> list[PluginConfigField]:
    if schema.get("type") != "object":
        return []

    props = schema.get("properties")
    if not isinstance(props, dict):
        return []

    required_set = set(schema.get("required") or [])

    fields: list[PluginConfigField] = []
    for key, sch in props.items():
        if not isinstance(key, str) or not isinstance(sch, dict):
            continue

        desc = sch.get("description") if isinstance(sch.get("description"), str) else None
        enum = sch.get("enum") if isinstance(sch.get("enum"), list) else None
        if enum is not None and not all(isinstance(x, (str, int, float, bool)) for x in enum):
            enum = None
        enum_s = [str(x) for x in enum] if enum is not None else None

        t = sch.get("type")
        if enum_s is not None:
            input_type = "select"
        elif t in {"integer", "number"}:
            input_type = "number"
        elif t == "boolean":
            input_type = "checkbox"
        elif t == "string":
            input_type = "text"
        else:
            input_type = "json"

        value = config.get(key)
        value_json = ""
        if input_type == "json":
            value_json = (
                json.dumps(value, ensure_ascii=False, indent=2) if value is not None else ""
            )

        fields.append(
            PluginConfigField(
                key=key,
                input=input_type,
                required=key in required_set,
                description=desc,
                enum=enum_s,
                value=value,
                value_json=value_json,
            )
        )

    fields.sort(key=lambda f: f.key.casefold())
    return fields


def _validate_plugin_config(schema: dict[str, Any], config: Any) -> list[str]:
    v = Draft202012Validator(schema)
    errors: list[str] = []
    for e in v.iter_errors(config):
        p = ".".join(str(x) for x in e.path)
        errors.append(f"{p}: {e.message}" if p else e.message)
    return errors


@router.get("/plugins", response_class=HTMLResponse)
async def ui_plugins(request: Request) -> HTMLResponse:
    db_path = _get_db_path(request)

    paths = getattr(request.app.state, "faceforge_paths", None)
    if paths is None:
        raise HTTPException(status_code=500, detail="Server not initialized")

    discovered = discover_plugins(plugins_dir=paths.plugins_dir)
    discovered_by_id = {p.manifest.id: p for p in discovered}

    for p in discovered:
        upsert_plugin_discovery(db_path, plugin_id=p.manifest.id, version=p.manifest.version)

    rows = list_plugin_registry(db_path, include_deleted=False)

    items: list[dict[str, Any]] = []
    for r in rows:
        d = discovered_by_id.get(r.plugin_id)
        name = d.manifest.name if d else None
        schema = d.manifest.config_schema if d else None
        cfg = r.config if isinstance(r.config, dict) else {}

        fields: list[PluginConfigField] = []
        if isinstance(schema, dict):
            fields = _schema_fields(schema, cfg)

        items.append(
            {
                "plugin_id": r.plugin_id,
                "name": name,
                "version": r.version,
                "enabled": r.enabled,
                "discovered": d is not None,
                "fields": fields,
                "config_json": json.dumps(cfg, ensure_ascii=False, indent=2),
            }
        )

    return templates.TemplateResponse(
        request,
        "plugins.html",
        {
            "title": "Plugins • FaceForge",
            "active": "plugins",
            "flash": _flash_from_request(request),
            "items": items,
        },
    )


@router.post("/plugins/{plugin_id}/enable")
async def ui_plugins_enable(request: Request, plugin_id: str) -> RedirectResponse:
    db_path = _get_db_path(request)

    paths = getattr(request.app.state, "faceforge_paths", None)
    if paths is None:
        raise HTTPException(status_code=500, detail="Server not initialized")

    discovered = {p.manifest.id: p for p in discover_plugins(plugins_dir=paths.plugins_dir)}
    if plugin_id not in discovered:
        return RedirectResponse(
            url="/ui/plugins?msg=Plugin+not+discovered&kind=bad", status_code=302
        )

    upsert_plugin_discovery(
        db_path, plugin_id=plugin_id, version=discovered[plugin_id].manifest.version
    )
    row = set_plugin_enabled(db_path, plugin_id=plugin_id, enabled=True)
    if row is None:
        return RedirectResponse(url="/ui/plugins?msg=Plugin+not+found&kind=bad", status_code=302)

    return RedirectResponse(url="/ui/plugins?msg=Plugin+enabled&kind=ok", status_code=302)


@router.post("/plugins/{plugin_id}/disable")
async def ui_plugins_disable(request: Request, plugin_id: str) -> RedirectResponse:
    db_path = _get_db_path(request)

    paths = getattr(request.app.state, "faceforge_paths", None)
    if paths is None:
        raise HTTPException(status_code=500, detail="Server not initialized")

    discovered = {p.manifest.id: p for p in discover_plugins(plugins_dir=paths.plugins_dir)}
    if plugin_id not in discovered:
        return RedirectResponse(
            url="/ui/plugins?msg=Plugin+not+discovered&kind=bad", status_code=302
        )

    upsert_plugin_discovery(
        db_path, plugin_id=plugin_id, version=discovered[plugin_id].manifest.version
    )
    row = set_plugin_enabled(db_path, plugin_id=plugin_id, enabled=False)
    if row is None:
        return RedirectResponse(url="/ui/plugins?msg=Plugin+not+found&kind=bad", status_code=302)

    return RedirectResponse(url="/ui/plugins?msg=Plugin+disabled&kind=ok", status_code=302)


@router.post("/plugins/{plugin_id}/config")
async def ui_plugins_config_save(request: Request, plugin_id: str) -> RedirectResponse:
    db_path = _get_db_path(request)

    paths = getattr(request.app.state, "faceforge_paths", None)
    if paths is None:
        raise HTTPException(status_code=500, detail="Server not initialized")

    discovered = {p.manifest.id: p for p in discover_plugins(plugins_dir=paths.plugins_dir)}
    if plugin_id not in discovered:
        return RedirectResponse(
            url="/ui/plugins?msg=Plugin+not+discovered&kind=bad", status_code=302
        )

    schema = discovered[plugin_id].manifest.config_schema
    if not isinstance(schema, dict):
        return RedirectResponse(url="/ui/plugins?msg=No+config+schema&kind=bad", status_code=302)

    form = await request.form()
    cfg: dict[str, Any] = {}

    props = schema.get("properties")
    if isinstance(props, dict):
        for key, sch in props.items():
            if not isinstance(key, str) or not isinstance(sch, dict):
                continue
            raw = form.get(key)

            enum = sch.get("enum") if isinstance(sch.get("enum"), list) else None
            t = sch.get("type")

            if enum is not None:
                cfg[key] = raw
                continue

            if t == "boolean":
                cfg[key] = str(raw).strip().lower() == "true"
            elif t == "integer":
                cfg[key] = int(raw) if raw not in (None, "") else None
            elif t == "number":
                cfg[key] = float(raw) if raw not in (None, "") else None
            elif t == "string":
                cfg[key] = str(raw) if raw is not None else ""
            else:
                # Fallback: parse as JSON.
                try:
                    cfg[key] = json.loads(str(raw)) if raw not in (None, "") else None
                except Exception:
                    return RedirectResponse(
                        url=f"/ui/plugins?msg=Invalid+JSON+for+{key}&kind=bad",
                        status_code=302,
                    )

    errors = _validate_plugin_config(schema, cfg)
    if errors:
        return RedirectResponse(url="/ui/plugins?msg=Invalid+config&kind=bad", status_code=302)

    row = set_plugin_config(db_path, plugin_id=plugin_id, config=cfg)
    if row is None:
        return RedirectResponse(url="/ui/plugins?msg=Plugin+not+found&kind=bad", status_code=302)

    return RedirectResponse(url="/ui/plugins?msg=Config+saved&kind=ok", status_code=302)
