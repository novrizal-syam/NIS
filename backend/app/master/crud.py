"""Spec-driven CRUD for master data.

Each entity is declared once (EntitySpec); the router, validation, CSV import, Excel
export, sensitive-field stripping, audit and the /meta used by the generic UI all derive
from it, so every master list behaves the same way.
"""

import csv
import io
import re
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model, field_validator
from sqlalchemy import Select, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.core.errors import AppError, ConflictError, ForbiddenError, NotFoundError
from app.core.models import Base
from app.services import audit
from app.services.audit import AuditAction

Kind = Literal["text", "int", "decimal", "idr", "bool", "date", "choice", "ref", "docs"]
MASK = "***"


class ExpiringDoc(BaseModel):
    """Legal document / certificate with an expiry date (alerts in later phases)."""

    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    number: str | None = Field(default=None, max_length=60)
    expiry_date: date | None = None


@dataclass(frozen=True)
class FieldSpec:
    name: str
    label: str
    kind: Kind = "text"
    required: bool = False
    max_length: int | None = None
    choices: tuple[tuple[str, str], ...] = ()
    ref: str | None = None  # entity key whose code this field holds
    in_list: bool = True
    sensitive: str | None = None  # salary | nik | bank_account | tax_id
    key: bool = False  # part of the natural key: required, not editable after create
    importable: bool = True
    min_value: int | None = None
    max_value: int | None = None
    default: Any = None


@dataclass(frozen=True)
class EntitySpec:
    key: str
    label: str
    model: type[Base]
    fields: tuple[FieldSpec, ...]
    search: tuple[str, ...] = ("code", "name")
    filters: tuple[str, ...] = ()
    read_module: str = "master"
    write_module: str = "master"
    sort: tuple[str, ...] = ("code",)
    title_field: str = "name"
    has_active: bool = True
    description: str = ""
    group: str = "umum"
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def key_fields(self) -> list[FieldSpec]:
        return [f for f in self.fields if f.key]

    def field(self, name: str) -> FieldSpec:
        return next(f for f in self.fields if f.name == name)


NBSP = chr(0xA0)  # Excel exports often use non-breaking spaces as separators


# --- value parsing (CSV and API share the same rules) ----------------------------------------


def _parse_number(raw: str, *, decimal_places: int | None) -> Decimal:
    s = raw.strip().replace("Rp", "").replace(" ", "").replace(NBSP, "")
    if "," in s:  # id-ID: 1.250.000,50
        s = s.replace(".", "").replace(",", ".")
    elif decimal_places == 0 and re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):
        s = s.replace(".", "")  # 1.250.000 as whole rupiah
    try:
        value = Decimal(s)
    except InvalidOperation as exc:
        raise ValueError("harus berupa angka") from exc
    if not value.is_finite():
        raise ValueError("harus berupa angka")
    return value


def _parse_csv_value(f: FieldSpec, raw: str) -> Any:
    raw = raw.strip()
    if raw == "":
        return None
    if f.kind == "int":
        return int(_parse_number(raw, decimal_places=0))
    if f.kind == "idr":
        return _parse_number(raw, decimal_places=0)
    if f.kind == "decimal":
        return _parse_number(raw, decimal_places=None)
    if f.kind == "bool":
        v = raw.lower()
        if v in {"ya", "y", "true", "1", "yes", "aktif"}:
            return True
        if v in {"tidak", "t", "false", "0", "no", "nonaktif"}:
            return False
        raise ValueError("isi Ya atau Tidak")
    if f.kind == "date":
        for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(raw, fmt).date()  # noqa: DTZ007 - a date, no time
            except ValueError:
                continue
        raise ValueError("format tanggal TTTT-BB-HH atau HH/BB/TTTT")
    if f.kind == "choice":
        by_label = {lbl.lower(): val for val, lbl in f.choices}
        return by_label.get(raw.lower(), raw)
    return raw


# --- dynamic schemas --------------------------------------------------------------------------


def _py_type(f: FieldSpec) -> Any:
    if f.kind == "int":
        return int
    if f.kind in ("decimal", "idr"):
        return Decimal
    if f.kind == "bool":
        return bool
    if f.kind == "date":
        return date
    if f.kind == "choice":
        return Literal[tuple(v for v, _ in f.choices)]
    if f.kind == "docs":
        return list[ExpiringDoc]
    return str


def _field_def(f: FieldSpec, *, for_update: bool) -> tuple[Any, Any]:
    t = _py_type(f)
    kw: dict[str, Any] = {}
    if f.max_length and f.kind in ("text", "ref"):
        kw["max_length"] = f.max_length
        kw["min_length"] = 1 if (f.required or f.key) else 0
    if f.min_value is not None:
        kw["ge"] = f.min_value
    if f.max_value is not None:
        kw["le"] = f.max_value
    if for_update or not (f.required or f.key):
        default = [] if f.kind == "docs" and not for_update else f.default
        return (t | None, Field(default=default, **kw))
    return (t, Field(**kw))


def _validators(spec: EntitySpec) -> dict[str, Any]:
    idr_fields = [f.name for f in spec.fields if f.kind == "idr"]
    text_fields = [f.name for f in spec.fields if f.kind in ("text", "ref")]
    validators: dict[str, Any] = {}
    if idr_fields:

        def _whole(cls: Any, v: Decimal | None) -> Decimal | None:
            if v is not None and v != v.to_integral_value():
                raise ValueError("rupiah harus bilangan bulat tanpa sen")
            return v

        validators["_idr"] = field_validator(*idr_fields, check_fields=False)(_whole)
    if text_fields:

        def _strip(cls: Any, v: str | None) -> str | None:
            if isinstance(v, str):
                v = v.strip()
                return v or None
            return v

        validators["_strip"] = field_validator(*text_fields, mode="before", check_fields=False)(
            _strip
        )
    return validators


def create_schema(spec: EntitySpec) -> type[BaseModel]:
    fields = {f.name: _field_def(f, for_update=False) for f in spec.fields}
    if spec.has_active:
        fields["is_active"] = (bool, Field(default=True))
    return create_model(  # type: ignore[call-overload,no-any-return]
        f"{spec.key}_create",
        __config__=ConfigDict(extra="forbid"),
        __validators__=_validators(spec),
        **fields,
    )


def update_schema(spec: EntitySpec) -> type[BaseModel]:
    fields = {f.name: _field_def(f, for_update=True) for f in spec.fields if not f.key}
    if spec.has_active:
        fields["is_active"] = (bool | None, Field(default=None))
    return create_model(  # type: ignore[call-overload,no-any-return]
        f"{spec.key}_update",
        __config__=ConfigDict(extra="forbid"),
        __validators__=_validators(spec),
        **fields,
    )


def _docs_json(value: list[Any]) -> list[dict[str, Any]]:
    return [ExpiringDoc.model_validate(d).model_dump(mode="json") for d in value]


# --- serialization ----------------------------------------------------------------------------


def _out_value(f: FieldSpec | None, v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, Decimal):
        if f is not None and f.kind == "idr":
            return format(v.quantize(Decimal(1)), "f")
        return format(v.normalize(), "f")
    if isinstance(v, date | datetime | uuid.UUID):
        return v.isoformat() if not isinstance(v, uuid.UUID) else str(v)
    return v


def to_dict(spec: EntitySpec, row: Any, principal: Principal | None) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": str(row.id),
        "is_demo": row.is_demo,
        "created_at": row.created_at.isoformat(),
        "updated_at": row.updated_at.isoformat(),
    }
    if spec.has_active:
        out["is_active"] = row.is_active
    for f in spec.fields:
        if f.sensitive and principal is not None and not principal.can_see(f.sensitive):
            continue  # UU 27/2022 PDP: not even the key is sent
        out[f.name] = _out_value(f, getattr(row, f.name))
    return out


def _audit_snapshot(spec: EntitySpec, row: Any) -> dict[str, Any]:
    snap = to_dict(spec, row, None)
    for f in spec.fields:
        if f.sensitive and snap.get(f.name) is not None:
            snap[f.name] = MASK  # audit records that it changed, not the value
    for k in ("created_at", "updated_at", "id"):
        snap.pop(k, None)
    return snap


# --- service ----------------------------------------------------------------------------------


def _check_sensitive_write(spec: EntitySpec, principal: Principal, data: dict[str, Any]) -> None:
    for f in spec.fields:
        if f.sensitive and f.name in data and not principal.can_see(f.sensitive):
            raise ForbiddenError(
                "SENSITIVE_FIELD_DENIED",
                f"Anda tidak berizin mengisi atau mengubah {f.label}.",
            )


async def _check_refs(
    session: AsyncSession, spec: EntitySpec, data: dict[str, Any], registry: dict[str, EntitySpec]
) -> None:
    for f in spec.fields:
        if f.ref and data.get(f.name):
            target = registry[f.ref]
            col = target.model.code  # type: ignore[attr-defined]
            found = (
                await session.execute(select(target.model.id).where(col == data[f.name]))  # type: ignore[attr-defined]
            ).first()
            if not found:
                raise AppError(
                    "REFERENCE_NOT_FOUND",
                    f"{f.label} '{data[f.name]}' tidak ditemukan di {target.label}.",
                    status_code=422,
                    details=[{"field": f.name, "message": "tidak ditemukan"}],
                )


def _key_filter(spec: EntitySpec, data: dict[str, Any]) -> list[Any]:
    return [getattr(spec.model, f.name) == data[f.name] for f in spec.key_fields]


async def _find_by_key(session: AsyncSession, spec: EntitySpec, data: dict[str, Any]) -> Any:
    return (
        await session.execute(select(spec.model).where(*_key_filter(spec, data)))
    ).scalar_one_or_none()


def _key_text(spec: EntitySpec, data: dict[str, Any]) -> str:
    return " / ".join(str(data[f.name]) for f in spec.key_fields)


async def create(
    session: AsyncSession,
    spec: EntitySpec,
    principal: Principal,
    data: dict[str, Any],
    registry: dict[str, EntitySpec],
) -> Any:
    _check_sensitive_write(spec, principal, {k: v for k, v in data.items() if v is not None})
    await _check_refs(session, spec, data, registry)
    if await _find_by_key(session, spec, data):
        raise ConflictError(
            "DUPLICATE_CODE", f"{spec.label} dengan kode {_key_text(spec, data)} sudah ada."
        )
    payload = {k: v for k, v in data.items() if v is not None}
    for f in spec.fields:
        if f.kind == "docs" and f.name in payload:
            payload[f.name] = _docs_json(payload[f.name])
    row: Any = spec.model(**payload, created_by=principal.id)
    session.add(row)
    await session.flush()
    await session.refresh(row)
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type=spec.key,
        entity_id=row.id,
        actor_id=principal.id,
        after=_audit_snapshot(spec, row),
    )
    return row


async def get(session: AsyncSession, spec: EntitySpec, row_id: uuid.UUID) -> Any:
    row = await session.get(spec.model, row_id)
    if row is None:
        raise NotFoundError("NOT_FOUND", f"{spec.label} tidak ditemukan.")
    return row


async def update(
    session: AsyncSession,
    spec: EntitySpec,
    principal: Principal,
    row: Any,
    data: dict[str, Any],
    registry: dict[str, EntitySpec],
) -> Any:
    _check_sensitive_write(spec, principal, data)
    await _check_refs(session, spec, data, registry)
    before = _audit_snapshot(spec, row)
    for k, v in data.items():
        f = next((x for x in spec.fields if x.name == k), None)
        if f is not None and f.kind == "docs" and v is not None:
            v = _docs_json(v)
        setattr(row, k, v)
    await session.flush()
    await session.refresh(row)
    after = _audit_snapshot(spec, row)
    if after != before:
        await audit.record(
            session,
            action=AuditAction.UPDATE,
            entity_type=spec.key,
            entity_id=row.id,
            actor_id=principal.id,
            before=before,
            after=after,
        )
    return row


async def delete(session: AsyncSession, spec: EntitySpec, principal: Principal, row: Any) -> None:
    before = _audit_snapshot(spec, row)
    try:
        async with session.begin_nested():
            await session.delete(row)
            await session.flush()
    except IntegrityError as exc:
        raise ConflictError(
            "IN_USE",
            f"{spec.label} ini masih dipakai data lain sehingga tidak bisa dihapus. "
            "Nonaktifkan saja.",
        ) from exc
    await audit.record(
        session,
        action=AuditAction.DELETE,
        entity_type=spec.key,
        entity_id=before.get("code", ""),
        actor_id=principal.id,
        before=before,
    )


def list_query(
    spec: EntitySpec,
    *,
    q: str | None,
    active: bool | None,
    filters: dict[str, str],
) -> Select[Any]:
    model = spec.model
    stmt = select(model)
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(*[getattr(model, c).ilike(like) for c in spec.search]))
    if active is not None and spec.has_active:
        stmt = stmt.where(model.is_active.is_(active))  # type: ignore[attr-defined]
    for name, value in filters.items():
        f = spec.field(name)
        col = getattr(model, name)
        if f.kind == "bool":
            stmt = stmt.where(col.is_(value.lower() in {"true", "1", "ya"}))
        else:
            stmt = stmt.where(col == value)
    return stmt.order_by(*[getattr(model, c) for c in spec.sort])


async def count(session: AsyncSession, stmt: Select[Any]) -> int:
    return int(
        (
            await session.execute(select(func.count()).select_from(stmt.order_by(None).subquery()))
        ).scalar_one()
    )


# --- CSV import -------------------------------------------------------------------------------


@dataclass
class ImportReport:
    created: int = 0
    updated: int = 0
    errors: list[dict[str, Any]] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


MAX_IMPORT_ROWS = 5000


def csv_template(spec: EntitySpec, principal: Principal) -> str:
    cols = [
        f.name
        for f in spec.fields
        if f.importable and (not f.sensitive or principal.can_see(f.sensitive))
    ]
    if spec.has_active:
        cols.append("is_active")
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(cols)
    return "﻿" + buf.getvalue()  # BOM so Excel opens UTF-8 correctly


def _read_csv(content: bytes) -> list[dict[str, str]]:
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = content.decode("cp1252")
    first = text.splitlines()[0] if text else ""
    delimiter = ";" if first.count(";") >= first.count(",") else ","
    return list(csv.DictReader(io.StringIO(text), delimiter=delimiter))


async def import_csv(
    session: AsyncSession,
    spec: EntitySpec,
    principal: Principal,
    content: bytes,
    registry: dict[str, EntitySpec],
) -> ImportReport:
    """All-or-nothing upsert by natural key. Errors are reported per row and field;
    nothing is saved unless every row is valid."""
    report = ImportReport()
    rows = _read_csv(content)
    if not rows:
        report.errors.append({"row": 1, "field": None, "message": "File kosong atau tanpa header."})
        return report
    if len(rows) > MAX_IMPORT_ROWS:
        report.errors.append(
            {"row": None, "field": None, "message": f"Maksimal {MAX_IMPORT_ROWS} baris per impor."}
        )
        return report

    allowed = {f.name: f for f in spec.fields if f.importable}
    if spec.has_active:
        allowed["is_active"] = FieldSpec("is_active", "Aktif", "bool")
    headers = [h.strip() for h in (rows[0].keys() if rows else []) if h]
    unknown = [h for h in headers if h not in allowed]
    if unknown:
        report.errors.append(
            {"row": 1, "field": None, "message": f"Kolom tidak dikenal: {', '.join(unknown)}."}
        )
    missing = [f.name for f in spec.key_fields if f.name not in headers]
    if missing:
        report.errors.append(
            {"row": 1, "field": None, "message": f"Kolom wajib tidak ada: {', '.join(missing)}."}
        )
    for h in headers:
        f = allowed.get(h)
        if f is not None and f.sensitive and not principal.can_see(f.sensitive):
            report.errors.append(
                {"row": 1, "field": h, "message": f"Anda tidak berizin mengimpor kolom {f.label}."}
            )
    if report.errors:
        return report

    create_model_ = create_schema(spec)
    update_model_ = update_schema(spec)
    seen: dict[str, int] = {}
    parsed: list[tuple[int, dict[str, Any], Any]] = []
    for i, raw in enumerate(rows, start=2):
        values: dict[str, Any] = {}
        row_errors = []
        for h in headers:
            try:
                values[h] = _parse_csv_value(allowed[h], raw.get(h) or "")
            except ValueError as exc:
                row_errors.append({"row": i, "field": h, "message": str(exc)})
        if row_errors:
            report.errors.extend(row_errors)
            continue
        key_text = (
            _key_text(spec, values) if all(values.get(f.name) for f in spec.key_fields) else ""
        )
        if key_text and key_text in seen:
            report.errors.append(
                {
                    "row": i,
                    "field": None,
                    "message": f"Kode {key_text} ganda (juga di baris {seen[key_text]}).",
                }
            )
            continue
        if key_text:
            seen[key_text] = i
        existing = await _find_by_key(session, spec, values) if key_text else None
        try:
            if existing is None:
                model = create_model_.model_validate(
                    {k: v for k, v in values.items() if v is not None}
                )
            else:
                model = update_model_.model_validate(
                    {k: v for k, v in values.items() if k not in {f.name for f in spec.key_fields}}
                )
        except ValidationError as exc:
            for err in exc.errors():
                loc = ".".join(str(x) for x in err["loc"])
                report.errors.append({"row": i, "field": loc or None, "message": _msg(err)})
            continue
        parsed.append((i, model.model_dump(exclude_unset=existing is not None), existing))

    if report.errors:
        return report
    for i, data, existing in parsed:
        try:
            async with session.begin_nested():
                if existing is None:
                    await create(session, spec, principal, data, registry)
                    report.created += 1
                else:
                    await update(session, spec, principal, existing, data, registry)
                    report.updated += 1
        except AppError as exc:
            report.errors.append({"row": i, "field": None, "message": exc.message})
    return report


_MESSAGES = {
    "missing": "wajib diisi",
    "string_too_long": "terlalu panjang",
    "string_too_short": "wajib diisi",
    "literal_error": "pilihan tidak valid",
    "greater_than_equal": "nilainya terlalu kecil",
    "less_than_equal": "nilainya terlalu besar",
    "decimal_parsing": "harus berupa angka",
    "int_parsing": "harus berupa angka bulat",
    "extra_forbidden": "kolom tidak dikenal",
}


def _msg(err: Any) -> str:
    if err["type"] == "value_error":
        return str(err.get("ctx", {}).get("error", err["msg"]))
    return _MESSAGES.get(err["type"], "nilai tidak valid")


def field_meta(spec: EntitySpec, principal: Principal) -> list[dict[str, Any]]:
    return [
        {
            "name": f.name,
            "label": f.label,
            "kind": f.kind,
            "required": f.required or f.key,
            "key": f.key,
            "max_length": f.max_length,
            "choices": [{"value": v, "label": lbl} for v, lbl in f.choices],
            "ref": f.ref,
            "in_list": f.in_list,
            "sensitive": f.sensitive is not None,
            "min_value": f.min_value,
            "max_value": f.max_value,
            "default": f.default,
        }
        for f in spec.fields
        if not f.sensitive or principal.can_see(f.sensitive)
    ]


def sequence_or_list(x: Sequence[Any]) -> list[Any]:
    return list(x)
