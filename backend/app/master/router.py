import uuid
from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, File, Query, Request, Response, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.permissions import ACTION_LABELS, MODULES, Action
from app.auth.principal import CurrentUser, Principal
from app.core import access
from app.core.db import get_session
from app.core.errors import AppError, ForbiddenError, NotFoundError
from app.core.pagination import PageParams, page_params
from app.master import crud
from app.master.crud import EntitySpec
from app.master.specs import REGISTRY, SPECS
from app.services.export import Column, Kind, xlsx_response
from app.services.numbering import today_jakarta

router = APIRouter(prefix="/master", tags=["master"])

for _s in SPECS:
    access.register(_s.key, access.module_checker(_s.read_module, _s.write_module))
Session = Annotated[AsyncSession, Depends(get_session)]
Pages = Annotated[PageParams, Depends(page_params)]
MAX_UPLOAD = 5 * 1024 * 1024
RESERVED = {"q", "active", "page", "page_size"}


def _spec(entity: str) -> EntitySpec:
    spec = REGISTRY.get(entity)
    if spec is None:
        raise NotFoundError("NOT_FOUND", "Jenis data master tidak dikenal.")
    return spec


def _need(principal: Principal, spec: EntitySpec, action: Action) -> None:
    module = spec.read_module if action in (Action.VIEW, Action.EXPORT) else spec.write_module
    if not principal.can(module, action):
        raise ForbiddenError(
            "PERMISSION_DENIED",
            f"Anda tidak memiliki izin {ACTION_LABELS[action]} data {spec.label} "
            f"({MODULES[module]}).",
        )


def _filters(spec: EntitySpec, request: Request) -> dict[str, str]:
    allowed = set(spec.filters)
    return {k: v for k, v in request.query_params.items() if k in allowed and v != ""}


def _validation(exc: ValidationError) -> AppError:
    fields = [
        {"field": ".".join(str(x) for x in e["loc"]), "message": crud._msg(e)} for e in exc.errors()
    ]
    summary = "; ".join(f"{f['field']} {f['message']}" for f in fields[:3])
    return AppError(
        "VALIDATION_ERROR", f"Data tidak valid: {summary}.", status_code=422, details=fields
    )


@router.get("")
async def entities(principal: CurrentUser) -> list[dict[str, Any]]:
    return [
        {"key": s.key, "label": s.label, "group": s.group}
        for s in SPECS
        if principal.can(s.read_module, "view")
    ]


@router.get("/{entity}/meta")
async def meta(entity: str, principal: CurrentUser) -> dict[str, Any]:
    spec = _spec(entity)
    _need(principal, spec, Action.VIEW)
    return {
        "key": spec.key,
        "label": spec.label,
        "fields": crud.field_meta(spec, principal),
        "filters": list(spec.filters),
        "title_field": spec.title_field,
        "has_active": spec.has_active,
        "can": {
            a: principal.can(
                spec.write_module if a in ("create", "edit", "delete") else spec.read_module, a
            )
            for a in ("create", "edit", "delete", "export")
        },
    }


@router.get("/{entity}")
async def list_rows(
    entity: str,
    request: Request,
    principal: CurrentUser,
    session: Session,
    pages: Pages,
    q: Annotated[str | None, Query(max_length=100)] = None,
    active: bool | None = None,
) -> dict[str, Any]:
    spec = _spec(entity)
    _need(principal, spec, Action.VIEW)
    stmt = crud.list_query(spec, q=q, active=active, filters=_filters(spec, request))
    total = await crud.count(session, stmt)
    rows = (await session.execute(stmt.offset(pages.offset).limit(pages.page_size))).scalars()
    return {
        "items": [crud.to_dict(spec, r, principal) for r in rows],
        "total": total,
        "page": pages.page,
        "page_size": pages.page_size,
    }


@router.get("/{entity}/options")
async def options(entity: str, principal: CurrentUser, session: Session) -> list[dict[str, str]]:
    """Active codes for dropdowns of fields that reference this entity."""
    spec = _spec(entity)
    _need(principal, spec, Action.VIEW)
    stmt = crud.list_query(spec, q=None, active=True if spec.has_active else None, filters={})
    rows = (await session.execute(stmt.limit(500))).scalars()
    return [{"value": r.code, "label": f"{r.code} · {getattr(r, spec.title_field)}"} for r in rows]


@router.get("/{entity}/export")
async def export(
    entity: str,
    request: Request,
    principal: CurrentUser,
    session: Session,
    q: str | None = None,
    active: bool | None = None,
) -> StreamingResponse:
    spec = _spec(entity)
    _need(principal, spec, Action.EXPORT)
    stmt = crud.list_query(spec, q=q, active=active, filters=_filters(spec, request))
    rows = [crud.to_dict(spec, r, principal) for r in (await session.execute(stmt)).scalars()]
    kinds: dict[str, Kind] = {"idr": "idr", "int": "number", "date": "date"}
    columns = [
        Column(
            f["label"], f["name"], kinds.get(f["kind"], "text"), 28 if f["kind"] == "text" else 16
        )
        for f in crud.field_meta(spec, principal)
        if f["kind"] != "docs"
    ]
    if spec.has_active:
        columns.append(Column("Aktif", "is_active", width=8))
    for r in rows:
        if "is_active" in r:
            r["is_active"] = "Ya" if r["is_active"] else "Tidak"
        for c in columns:
            if c.kind == "date" and r.get(c.key):
                r[c.key] = date.fromisoformat(r[c.key])
    return xlsx_response(f"{spec.key}-{today_jakarta():%Y%m%d}.xlsx", spec.label, columns, rows)


@router.get("/{entity}/template")
async def template(entity: str, principal: CurrentUser) -> Response:
    spec = _spec(entity)
    _need(principal, spec, Action.CREATE)
    return Response(
        crud.csv_template(spec, principal),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="template-{spec.key}.csv"'},
    )


@router.post("/{entity}/import")
async def import_csv(
    entity: str,
    principal: CurrentUser,
    session: Session,
    file: Annotated[UploadFile, File()],
) -> dict[str, Any]:
    spec = _spec(entity)
    _need(principal, spec, Action.CREATE)
    _need(principal, spec, Action.EDIT)
    content = await file.read(MAX_UPLOAD + 1)
    if len(content) > MAX_UPLOAD:
        raise AppError("FILE_TOO_LARGE", "File impor maksimal 5 MB.", status_code=413)
    report = await crud.import_csv(session, spec, principal, content, REGISTRY)
    if report.ok:
        await session.commit()
    else:
        await session.rollback()
        report.created = report.updated = 0
    return {
        "ok": report.ok,
        "created": report.created,
        "updated": report.updated,
        "errors": report.errors[:200],
    }


@router.get("/{entity}/{row_id}")
async def get_row(
    entity: str, row_id: uuid.UUID, principal: CurrentUser, session: Session
) -> dict[str, Any]:
    spec = _spec(entity)
    _need(principal, spec, Action.VIEW)
    return crud.to_dict(spec, await crud.get(session, spec, row_id), principal)


@router.post("/{entity}", status_code=201)
async def create_row(
    entity: str, body: dict[str, Any], principal: CurrentUser, session: Session
) -> dict[str, Any]:
    spec = _spec(entity)
    _need(principal, spec, Action.CREATE)
    try:
        data = crud.create_schema(spec).model_validate(body).model_dump(exclude_unset=False)
    except ValidationError as exc:
        raise _validation(exc) from exc
    # Defaults the user did not send must not trip the sensitive-field check.
    data = {k: v for k, v in data.items() if k in body or v not in (None, [])}
    row = await crud.create(session, spec, principal, data, REGISTRY)
    await session.commit()
    return crud.to_dict(spec, row, principal)


@router.patch("/{entity}/{row_id}")
async def update_row(
    entity: str, row_id: uuid.UUID, body: dict[str, Any], principal: CurrentUser, session: Session
) -> dict[str, Any]:
    spec = _spec(entity)
    _need(principal, spec, Action.EDIT)
    try:
        data = crud.update_schema(spec).model_validate(body).model_dump(exclude_unset=True)
    except ValidationError as exc:
        raise _validation(exc) from exc
    row = await crud.get(session, spec, row_id)
    row = await crud.update(session, spec, principal, row, data, REGISTRY)
    await session.commit()
    return crud.to_dict(spec, row, principal)


@router.delete("/{entity}/{row_id}", status_code=204)
async def delete_row(
    entity: str, row_id: uuid.UUID, principal: CurrentUser, session: Session
) -> Response:
    spec = _spec(entity)
    _need(principal, spec, Action.DELETE)
    row = await crud.get(session, spec, row_id)
    await crud.delete(session, spec, principal, row)
    await session.commit()
    return Response(status_code=204)
