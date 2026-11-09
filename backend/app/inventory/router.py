"""Inventory API: stock, transfers, stock opname, reorder, valuation, goods receipt, MR."""

import uuid
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.permissions import Scope
from app.auth.principal import CurrentUser, Principal, require, scope_filter
from app.core import access
from app.core.db import get_session
from app.core.errors import ForbiddenError, NotFoundError
from app.core.pagination import PageParams, page_params
from app.finance.models import JournalEntry
from app.inventory import gr_service, mr_service
from app.inventory import stock_service as stock
from app.inventory.models import (
    GoodsReceipt,
    MaterialRequest,
    StockBalance,
    StockCount,
    StockMove,
    StockTransfer,
    StockTransferLine,
)
from app.master.models import CostElement, Item, Vendor, Warehouse
from app.procurement import po_service
from app.procurement.models import PurchaseOrder, PurchaseRequisition
from app.project.models import Project, ProjectWbs
from app.services import budget_control as bc
from app.services import ledger
from app.services.export import Column, xlsx_response
from app.services.numbering import today_jakarta

router = APIRouter(prefix="/inventory", tags=["inventory"])
Session = Annotated[AsyncSession, Depends(get_session)]
Viewer = Annotated[Principal, Depends(require("inventory", "view"))]
Creator = Annotated[Principal, Depends(require("inventory", "create"))]
Editor = Annotated[Principal, Depends(require("inventory", "edit"))]
Exporter = Annotated[Principal, Depends(require("inventory", "export"))]
Paging = Annotated[PageParams, Depends(page_params)]


def _m(v: Decimal | None) -> str | None:
    return format(v, "f") if v is not None else None


def _q(v: Decimal) -> str:
    return format(v.normalize(), "f") if v else "0"


def _project_scoped(principal: Principal, module: str, project_id: uuid.UUID) -> bool:
    scope = principal.scope_for(module, "view")
    return scope == Scope.ALL or (scope is not None and project_id in principal.project_ids)


async def _journal(session: AsyncSession, jid: uuid.UUID | None) -> dict[str, Any] | None:
    if jid is None:
        return None
    entry = await session.get(JournalEntry, jid)
    assert entry is not None
    return {
        "number": entry.number,
        "entry_date": entry.entry_date.isoformat(),
        "total": _m(entry.total),
        "lines": [
            {
                "account_code": x.account_code,
                "debit": _m(x.debit),
                "credit": _m(x.credit),
                "cost_element_code": x.cost_element_code,
                "partner_code": x.partner_code,
            }
            for x in await ledger.lines_of(session, entry.id)
        ],
    }


# ---------------------------------------------------------------- warehouses & stock


@router.get("/warehouses")
async def warehouses(_: CurrentUser, session: Session) -> list[dict[str, Any]]:
    rows = await session.execute(
        select(Warehouse).where(Warehouse.is_active).order_by(Warehouse.kind, Warehouse.code)
    )
    return [
        {"code": w.code, "name": w.name, "kind": w.kind, "project_code": w.project_code}
        for w in rows.scalars()
    ]


def _stock_query(warehouse: str | None, q: str | None) -> Select[Any]:
    stmt = (
        select(StockBalance, Item.name, Item.uom, Item.reorder_point)
        .join(Item, Item.code == StockBalance.item_code)
        .where((StockBalance.qty != 0) | (StockBalance.value != 0))
    )
    if warehouse:
        stmt = stmt.where(StockBalance.warehouse_code == warehouse)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Item.code.ilike(like), Item.name.ilike(like)))
    return stmt.order_by(StockBalance.warehouse_code, StockBalance.item_code)


def _stock_row(b: StockBalance, name: str, uom: str, rop: Decimal) -> dict[str, Any]:
    return {
        "warehouse_code": b.warehouse_code,
        "item_code": b.item_code,
        "name": name,
        "uom": uom,
        "qty": _q(b.qty),
        "avg_cost": _m(stock.avg_cost(b)),
        "value": _m(b.value),
        "reorder_point": _q(rop),
    }


@router.get("/stock")
async def list_stock(
    _: Viewer,
    session: Session,
    paging: Paging,
    warehouse: str | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    stmt = _stock_query(warehouse, q)
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    value = (
        await session.execute(select(func.coalesce(func.sum(stmt.subquery().c.value), 0)))
    ).scalar_one()
    rows = (await session.execute(stmt.offset(paging.offset).limit(paging.page_size))).all()
    return {
        "items": [_stock_row(*r) for r in rows],
        "total": total,
        "total_value": _m(Decimal(value)),
        "page": paging.page,
        "page_size": paging.page_size,
    }


@router.get("/stock/export")
async def export_stock(
    _: Exporter, session: Session, warehouse: str | None = None, q: str | None = None
) -> StreamingResponse:
    rows = [_stock_row(*r) for r in (await session.execute(_stock_query(warehouse, q))).all()]
    columns = [
        Column("Gudang", "warehouse_code", width=12),
        Column("Item", "item_code", width=12),
        Column("Nama", "name", width=32),
        Column("Satuan", "uom", width=8),
        Column("Qty", "qty", width=10),
        Column("Harga rata-rata", "avg_cost", "idr"),
        Column("Nilai", "value", "idr"),
    ]
    return xlsx_response(f"stok-{today_jakarta():%Y%m%d}.xlsx", "Stok", columns, rows)


@router.get("/stock/availability")
async def availability(
    _: CurrentUser, session: Session, item: str, site: str | None = None
) -> dict[str, Any]:
    """Quantity at a site and at Base (MR form hint)."""
    base = (
        await session.execute(
            select(Warehouse.code).where(Warehouse.kind == "base", Warehouse.is_active).limit(1)
        )
    ).scalar_one_or_none()
    return {
        "site": _q(await stock.on_hand(session, item, site)) if site else "0",
        "base": _q(await stock.on_hand(session, item, base)) if base else "0",
    }


@router.get("/moves")
async def list_moves(
    _: Viewer,
    session: Session,
    paging: Paging,
    item: str | None = None,
    warehouse: str | None = None,
) -> dict[str, Any]:
    stmt = select(StockMove)
    if item:
        stmt = stmt.where(StockMove.item_code == item)
    if warehouse:
        stmt = stmt.where(StockMove.warehouse_code == warehouse)
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        await session.execute(
            stmt.order_by(StockMove.at.desc(), StockMove.id)
            .offset(paging.offset)
            .limit(paging.page_size)
        )
    ).scalars()
    return {
        "items": [
            {
                "at": m.at.isoformat(),
                "item_code": m.item_code,
                "warehouse_code": m.warehouse_code,
                "kind": m.kind,
                "qty": _q(m.qty),
                "value": _m(m.value),
                "qty_after": _q(m.qty_after),
                "value_after": _m(m.value_after),
                "doc_number": m.doc_number,
            }
            for m in rows
        ],
        "total": total,
        "page": paging.page,
        "page_size": paging.page_size,
    }


@router.get("/reorder")
async def reorder(_: Viewer, session: Session) -> list[dict[str, Any]]:
    return [
        {
            **r,
            "on_hand": _q(r["on_hand"]),
            "reorder_point": _q(r["reorder_point"]),
            "suggested_qty": _q(r["suggested_qty"]),
            "last_price": _m(r["last_price"]),
            "est_value": _m(r["est_value"]),
        }
        for r in await stock.reorder_suggestions(session)
    ]


@router.get("/valuation")
async def valuation(_: Viewer, session: Session) -> dict[str, Any]:
    v = await stock.valuation(session)
    return {
        "rows": [
            {**r, "qty": _q(r["qty"]), "avg_cost": _m(r["avg_cost"]), "value": _m(r["value"])}
            for r in v["rows"]
        ],
        "total": _m(v["total"]),
        "ledger_1310": _m(v["ledger_1310"]),
        "difference": _m(v["difference"]),
        "reconciled": v["reconciled"],
    }


# ---------------------------------------------------------------- transfers


class QtyLineBody(BaseModel):
    item_code: str = Field(min_length=1, max_length=30)
    qty: Decimal = Field(gt=0, max_digits=18, decimal_places=2)


class TransferBody(BaseModel):
    from_warehouse: str
    to_warehouse: str
    note: str | None = Field(default=None, max_length=500)
    lines: list[QtyLineBody] = Field(min_length=1)


@router.get("/transfers")
async def list_transfers(_: Viewer, session: Session, paging: Paging) -> dict[str, Any]:
    stmt = select(StockTransfer)
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = list(
        (
            await session.execute(
                stmt.order_by(StockTransfer.created_at.desc())
                .offset(paging.offset)
                .limit(paging.page_size)
            )
        ).scalars()
    )
    lines: dict[uuid.UUID, list[dict[str, str]]] = {}
    if rows:
        for x in (
            await session.execute(
                select(StockTransferLine).where(
                    StockTransferLine.transfer_id.in_([t.id for t in rows])
                )
            )
        ).scalars():
            lines.setdefault(x.transfer_id, []).append(
                {"item_code": x.item_code, "qty": _q(x.qty), "value": _m(x.value) or "0"}
            )
    return {
        "items": [
            {
                "id": str(t.id),
                "number": t.number,
                "from_warehouse": t.from_warehouse,
                "to_warehouse": t.to_warehouse,
                "value": _m(t.value),
                "note": t.note,
                "created_at": t.created_at.isoformat(),
                "lines": lines.get(t.id, []),
            }
            for t in rows
        ],
        "total": total,
        "page": paging.page,
        "page_size": paging.page_size,
    }


@router.post("/transfers", status_code=201)
async def create_transfer(body: TransferBody, actor: Editor, session: Session) -> dict[str, Any]:
    tr = await stock.transfer(
        session,
        actor,
        from_wh=body.from_warehouse,
        to_wh=body.to_warehouse,
        lines=[stock.QtyLine(x.item_code, x.qty) for x in body.lines],
        note=body.note,
    )
    await session.commit()
    return {"id": str(tr.id), "number": tr.number, "value": _m(tr.value)}


# ---------------------------------------------------------------- stock opname


class CountLineBody(BaseModel):
    item_code: str = Field(min_length=1, max_length=30)
    counted_qty: Decimal = Field(ge=0, max_digits=18, decimal_places=2)
    reason: str | None = Field(default=None, max_length=300)


class CountBody(BaseModel):
    warehouse_code: str
    count_date: date
    note: str | None = Field(default=None, max_length=500)
    lines: list[CountLineBody] = Field(min_length=1)


async def _count_detail(
    session: AsyncSession, principal: Principal, sc: StockCount
) -> dict[str, Any]:
    names = dict(
        (await session.execute(select(Item.code, Item.name))).tuples().all()
    )  # small master table
    return {
        "id": str(sc.id),
        "number": sc.number,
        "warehouse_code": sc.warehouse_code,
        "count_date": sc.count_date.isoformat(),
        "status": sc.status,
        "note": sc.note,
        "variance_value": _m(sc.variance_value),
        "reject_reason": sc.reject_reason,
        "request_id": str(sc.request_id) if sc.request_id else None,
        "journal": await _journal(session, sc.journal_id),
        "can_submit": principal.can("inventory", "edit") and sc.status in ("draft", "rejected"),
        "lines": [
            {
                "item_code": x.item_code,
                "name": names.get(x.item_code, x.item_code),
                "system_qty": _q(x.system_qty),
                "counted_qty": _q(x.counted_qty),
                "variance_qty": _q(x.counted_qty - x.system_qty),
                "unit_cost": _m(x.unit_cost),
                "variance_value": _m(x.variance_value),
                "reason": x.reason,
            }
            for x in await stock.count_lines(session, sc.id)
        ],
    }


@router.get("/counts")
async def list_counts(
    _: Viewer, session: Session, paging: Paging, status: str | None = None
) -> dict[str, Any]:
    stmt = select(StockCount)
    if status:
        stmt = stmt.where(StockCount.status == status)
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        await session.execute(
            stmt.order_by(StockCount.created_at.desc())
            .offset(paging.offset)
            .limit(paging.page_size)
        )
    ).scalars()
    return {
        "items": [
            {
                "id": str(c.id),
                "number": c.number,
                "warehouse_code": c.warehouse_code,
                "count_date": c.count_date.isoformat(),
                "status": c.status,
                "variance_value": _m(c.variance_value),
            }
            for c in rows
        ],
        "total": total,
        "page": paging.page,
        "page_size": paging.page_size,
    }


@router.post("/counts", status_code=201)
async def create_count(body: CountBody, actor: Editor, session: Session) -> dict[str, Any]:
    sc = await stock.create_count(
        session,
        actor,
        wh_code=body.warehouse_code,
        count_date=body.count_date,
        lines=[stock.CountLine(x.item_code, x.counted_qty, x.reason) for x in body.lines],
        note=body.note,
    )
    await session.commit()
    return await _count_detail(session, actor, sc)


async def _get_count(session: AsyncSession, cid: uuid.UUID, lock: bool = False) -> StockCount:
    sc = await session.get(StockCount, cid, with_for_update=lock)
    if sc is None:
        raise NotFoundError("NOT_FOUND", "Stock opname tidak ditemukan.")
    return sc


@router.get("/counts/{cid}")
async def get_count(cid: uuid.UUID, principal: Viewer, session: Session) -> dict[str, Any]:
    return await _count_detail(session, principal, await _get_count(session, cid))


@router.post("/counts/{cid}/submit")
async def submit_count(cid: uuid.UUID, actor: Editor, session: Session) -> dict[str, Any]:
    sc = await _get_count(session, cid, lock=True)
    await stock.submit_count(session, actor, sc)
    await session.commit()
    return await _count_detail(session, actor, sc)


async def _count_access(
    session: AsyncSession, principal: Principal, eid: str, mode: access.Mode
) -> bool:
    return principal.can("inventory", "view" if mode == "read" else "edit")


access.register(stock.COUNT_DOC, _count_access)


# ---------------------------------------------------------------- goods receipt


class GrLineBody(BaseModel):
    seq: int = Field(ge=1)
    qty: Decimal = Field(ge=0, max_digits=18, decimal_places=2)


class GrBody(BaseModel):
    po_id: uuid.UUID
    received_date: date
    warehouse_code: str | None = None
    delivery_note: str | None = Field(default=None, max_length=60)
    note: str | None = Field(default=None, max_length=2000)
    lines: list[GrLineBody] = Field(min_length=1)


def _may_view_po(principal: Principal, po: PurchaseOrder) -> bool:
    return (
        principal.scope_for("inventory", "view") is not None
        or _project_scoped(principal, "procurement", po.project_id)
        or po.created_by == principal.id
    )


async def _gr(session: AsyncSession, principal: Principal, gid: uuid.UUID) -> GoodsReceipt:
    gr = await session.get(GoodsReceipt, gid)
    po = await session.get(PurchaseOrder, gr.po_id) if gr else None
    if gr is None or po is None or not _may_view_po(principal, po):
        raise NotFoundError("NOT_FOUND", "GR tidak ditemukan atau Anda tidak berizin.")
    return gr


async def _gr_access(
    session: AsyncSession, principal: Principal, eid: str, mode: access.Mode
) -> bool:
    try:
        gr = await _gr(session, principal, uuid.UUID(eid))
    except (ValueError, NotFoundError):
        return False
    if mode == "read":
        return True
    po = await session.get(PurchaseOrder, gr.po_id)
    return (
        gr.status == "draft"
        and po is not None
        and await gr_service.may_receive(session, principal, po)
    )


access.register(gr_service.DOC, _gr_access)


async def _gr_detail(
    session: AsyncSession, principal: Principal, gr: GoodsReceipt
) -> dict[str, Any]:
    po = await session.get(PurchaseOrder, gr.po_id)
    assert po is not None
    vendor = (
        await session.execute(select(Vendor.name).where(Vendor.code == po.vendor_code))
    ).scalar_one()
    project = await session.get(Project, po.project_id)
    assert project is not None
    can = gr.status == "draft" and await gr_service.may_receive(session, principal, po)
    return {
        "id": str(gr.id),
        "number": gr.number,
        "kind": gr.kind,
        "status": gr.status,
        "po_id": str(po.id),
        "po_number": po.number,
        "po_status": po.status,
        "vendor_code": po.vendor_code,
        "vendor_name": vendor,
        "project_id": str(project.id),
        "project_number": project.number,
        "cost_element_code": po.cost_element_code,
        "received_date": gr.received_date.isoformat(),
        "warehouse_code": gr.warehouse_code,
        "delivery_note": gr.delivery_note,
        "note": gr.note,
        "amount": _m(gr.amount),
        "posted_at": gr.posted_at.isoformat() if gr.posted_at else None,
        "journal": await _journal(session, gr.journal_id),
        "can_post": can,
        "can_cancel": can,
        "lines": [
            {
                "seq": x.po_line_seq,
                "item_code": x.item_code,
                "description": x.description,
                "qty": _q(x.qty),
                "uom": x.uom,
                "unit_price": _m(x.unit_price),
                "amount": _m(x.amount),
                "to_stock": x.to_stock,
            }
            for x in await gr_service.lines_of(session, gr.id)
        ],
    }


def _gr_query(principal: Principal, status: str | None, po_id: uuid.UUID | None) -> Select[Any]:
    stmt = select(GoodsReceipt, PurchaseOrder).join(
        PurchaseOrder, PurchaseOrder.id == GoodsReceipt.po_id
    )
    if principal.scope_for("inventory", "view") is None:
        scope = principal.scope_for("procurement", "view")
        if scope != Scope.ALL:
            stmt = stmt.where(
                PurchaseOrder.project_id.in_(principal.project_ids or {uuid.uuid4()})
                if scope is not None
                else GoodsReceipt.created_by == principal.id
            )
    if status:
        stmt = stmt.where(GoodsReceipt.status == status)
    if po_id:
        stmt = stmt.where(GoodsReceipt.po_id == po_id)
    return stmt


@router.get("/grs")
async def list_grs(
    principal: CurrentUser,
    session: Session,
    paging: Paging,
    status: str | None = None,
    po_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    stmt = _gr_query(principal, status, po_id)
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        await session.execute(
            stmt.order_by(GoodsReceipt.created_at.desc())
            .offset(paging.offset)
            .limit(paging.page_size)
        )
    ).all()
    return {
        "items": [
            {
                "id": str(g.id),
                "number": g.number,
                "kind": g.kind,
                "status": g.status,
                "po_id": str(p.id),
                "po_number": p.number,
                "vendor_code": p.vendor_code,
                "received_date": g.received_date.isoformat(),
                "warehouse_code": g.warehouse_code,
                "amount": _m(g.amount),
            }
            for g, p in rows
        ],
        "total": total,
        "page": paging.page,
        "page_size": paging.page_size,
    }


@router.get("/grs/export")
async def export_grs(principal: CurrentUser, session: Session) -> StreamingResponse:
    rows = (
        await session.execute(_gr_query(principal, None, None).order_by(GoodsReceipt.number))
    ).all()
    columns = [
        Column("Nomor", "number", width=14),
        Column("Jenis", "kind", width=10),
        Column("Status", "status", width=12),
        Column("PO", "po", width=14),
        Column("Vendor", "vendor", width=12),
        Column("Tanggal terima", "received", "date"),
        Column("Gudang", "warehouse", width=10),
        Column("Nilai", "amount", "idr"),
    ]
    return xlsx_response(
        f"gr-{today_jakarta():%Y%m%d}.xlsx",
        "GR",
        columns,
        (
            {
                "number": g.number,
                "kind": g.kind,
                "status": g.status,
                "po": p.number,
                "vendor": p.vendor_code,
                "received": g.received_date,
                "warehouse": g.warehouse_code,
                "amount": g.amount,
            }
            for g, p in rows
        ),
    )


@router.get("/receivable/{po_id}")
async def receivable(po_id: uuid.UUID, principal: CurrentUser, session: Session) -> dict[str, Any]:
    """Open quantities of a PO for the GR form."""
    po = await session.get(PurchaseOrder, po_id)
    if po is None or not _may_view_po(principal, po):
        raise NotFoundError("NOT_FOUND", "PO tidak ditemukan atau Anda tidak berizin.")
    lines = await po_service.lines_of(session, po.id)
    done = await gr_service.received_by_seq(session, po.id)
    vendor = (
        await session.execute(select(Vendor.name).where(Vendor.code == po.vendor_code))
    ).scalar_one()
    return {
        "po_id": str(po.id),
        "po_number": po.number,
        "po_status": po.status,
        "vendor_name": vendor,
        "kind": gr_service.kind_of(lines),
        "can_receive": po.status == "issued"
        and await gr_service.may_receive(session, principal, po),
        "lines": [
            {
                "seq": x.seq,
                "item_code": x.item_code,
                "description": x.description,
                "uom": x.uom,
                "ordered": _q(x.qty),
                "received": _q(done.get(x.seq, Decimal(0))),
                "open": _q(x.qty - done.get(x.seq, Decimal(0))),
                "unit_price": _m(x.unit_price),
            }
            for x in lines
        ],
    }


@router.post("/grs", status_code=201)
async def create_gr(body: GrBody, actor: CurrentUser, session: Session) -> dict[str, Any]:
    po = await session.get(PurchaseOrder, body.po_id, with_for_update=True)
    if po is None or not _may_view_po(actor, po):
        raise NotFoundError("NOT_FOUND", "PO tidak ditemukan atau Anda tidak berizin.")
    gr = await gr_service.create(
        session,
        actor,
        po,
        received_date=body.received_date,
        warehouse_code=body.warehouse_code or None,
        delivery_note=body.delivery_note,
        note=body.note,
        lines=[gr_service.LineIn(x.seq, x.qty) for x in body.lines],
    )
    await session.commit()
    return await _gr_detail(session, actor, gr)


@router.get("/grs/{gid}")
async def get_gr(gid: uuid.UUID, principal: CurrentUser, session: Session) -> dict[str, Any]:
    return await _gr_detail(session, principal, await _gr(session, principal, gid))


@router.post("/grs/{gid}/post")
async def post_gr(gid: uuid.UUID, actor: CurrentUser, session: Session) -> dict[str, Any]:
    gr = await _gr(session, actor, gid)
    await session.refresh(gr, with_for_update=True)
    await gr_service.post(session, actor, gr)
    await session.commit()
    return await _gr_detail(session, actor, gr)


@router.post("/grs/{gid}/cancel")
async def cancel_gr(gid: uuid.UUID, actor: CurrentUser, session: Session) -> dict[str, Any]:
    gr = await _gr(session, actor, gid)
    await session.refresh(gr, with_for_update=True)
    await gr_service.cancel(session, actor, gr)
    await session.commit()
    return await _gr_detail(session, actor, gr)


# ---------------------------------------------------------------- material request


class MrBody(BaseModel):
    project_id: uuid.UUID
    wbs_code: str = Field(min_length=1, max_length=20)
    cost_element_code: str = Field(default="CONSUMABLE", max_length=20)
    site_warehouse: str = Field(min_length=1, max_length=20)
    need_date: date
    purpose: str | None = Field(default=None, max_length=500)
    lines: list[QtyLineBody] = Field(min_length=1)


def _mr_filter(principal: Principal) -> Any:
    return scope_filter(
        principal,
        "inventory",
        "view",
        owner_col=MaterialRequest.requester_id,
        project_col=MaterialRequest.project_id,
    )


async def _mr(session: AsyncSession, principal: Principal, mid: uuid.UUID) -> MaterialRequest:
    mr = (
        await session.execute(
            select(MaterialRequest).where(MaterialRequest.id == mid, _mr_filter(principal))
        )
    ).scalar_one_or_none()
    if mr is None:
        raise NotFoundError("NOT_FOUND", "MR tidak ditemukan atau Anda tidak berizin.")
    return mr


async def _mr_access(
    session: AsyncSession, principal: Principal, eid: str, mode: access.Mode
) -> bool:
    try:
        mr = await _mr(session, principal, uuid.UUID(eid))
    except (ValueError, NotFoundError):
        return False
    return mode == "read" or mr.requester_id == principal.id


access.register(mr_service.DOC, _mr_access)


async def _mr_detail(session: AsyncSession, mr: MaterialRequest) -> dict[str, Any]:
    project = await session.get(Project, mr.project_id)
    wbs = await session.get(ProjectWbs, mr.wbs_id)
    pr = await session.get(PurchaseRequisition, mr.pr_id) if mr.pr_id else None
    requester = await session.get(User, mr.requester_id)
    assert project is not None and wbs is not None and requester is not None
    names = {
        c: (n, u)
        for c, n, u in (await session.execute(select(Item.code, Item.name, Item.uom))).tuples()
    }
    return {
        "id": str(mr.id),
        "number": mr.number,
        "status": mr.status,
        "status_label": mr_service.STATUS_LABELS.get(mr.status, mr.status),
        "project_id": str(project.id),
        "project_number": project.number,
        "project_name": project.name,
        "wbs_code": wbs.code,
        "cost_element_code": mr.cost_element_code,
        "site_warehouse": mr.site_warehouse,
        "base_warehouse": mr.base_warehouse,
        "requester_name": requester.full_name,
        "need_date": mr.need_date.isoformat(),
        "purpose": mr.purpose,
        "issued_value": _m(mr.issued_value),
        "created_at": mr.created_at.isoformat(),
        "pr": {"id": str(pr.id), "number": pr.number, "status": pr.status} if pr else None,
        "journal": await _journal(session, mr.journal_id),
        "lines": [
            {
                "seq": x.seq,
                "item_code": x.item_code,
                "name": names.get(x.item_code, (x.item_code, ""))[0],
                "uom": names.get(x.item_code, ("", ""))[1],
                "qty": _q(x.qty),
                "from_site": _q(x.from_site),
                "from_base": _q(x.from_base),
                "shortfall": _q(x.shortfall),
                "value": _m(x.value),
            }
            for x in await mr_service.lines_of(session, mr.id)
        ],
    }


@router.get("/mrs/form-options")
async def mr_form_options(principal: Creator, session: Session) -> dict[str, Any]:
    """Locked projects the user may request material for, with WBS, site warehouses, items."""
    stmt = select(Project).where(Project.status == "locked").order_by(Project.number)
    if principal.scope_for("inventory", "create") != Scope.ALL:
        stmt = stmt.where(Project.id.in_(principal.project_ids or {uuid.uuid4()}))
    projects = list((await session.execute(stmt)).scalars())
    wbs: dict[uuid.UUID, list[dict[str, str]]] = {}
    if projects:
        for w in (
            await session.execute(
                select(ProjectWbs)
                .where(ProjectWbs.project_id.in_([p.id for p in projects]))
                .order_by(ProjectWbs.seq)
            )
        ).scalars():
            wbs.setdefault(w.project_id, []).append({"code": w.code, "name": w.name})
    sites = (
        await session.execute(
            select(Warehouse)
            .where(Warehouse.kind == "site", Warehouse.is_active)
            .order_by(Warehouse.code)
        )
    ).scalars()
    items = (
        await session.execute(select(Item).where(Item.is_active).order_by(Item.code))
    ).scalars()
    elements = await session.execute(
        select(CostElement.code, CostElement.name)
        .where(CostElement.code != bc.CONTINGENCY)
        .order_by(CostElement.code)
    )
    return {
        "projects": [
            {"id": str(p.id), "number": p.number, "name": p.name, "wbs": wbs.get(p.id, [])}
            for p in projects
        ],
        "sites": [{"code": w.code, "name": w.name, "project_code": w.project_code} for w in sites],
        "items": [
            {"code": i.code, "name": i.name, "uom": i.uom, "last_price": _m(i.last_price)}
            for i in items
        ],
        "cost_elements": [{"code": c, "name": n} for c, n in elements.tuples()],
    }


@router.get("/mrs")
async def list_mrs(
    principal: Viewer,
    session: Session,
    paging: Paging,
    status: str | None = None,
    q: str | None = None,
) -> dict[str, Any]:
    stmt = (
        select(MaterialRequest, Project.number)
        .join(Project, Project.id == MaterialRequest.project_id)
        .where(_mr_filter(principal))
    )
    if status:
        stmt = stmt.where(MaterialRequest.status == status)
    if q and q.strip():
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(MaterialRequest.number.ilike(like), Project.number.ilike(like)))
    total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        await session.execute(
            stmt.order_by(MaterialRequest.created_at.desc())
            .offset(paging.offset)
            .limit(paging.page_size)
        )
    ).all()
    return {
        "items": [
            {
                "id": str(m.id),
                "number": m.number,
                "status": m.status,
                "status_label": mr_service.STATUS_LABELS.get(m.status, m.status),
                "project_number": pn,
                "site_warehouse": m.site_warehouse,
                "need_date": m.need_date.isoformat(),
                "issued_value": _m(m.issued_value),
                "has_pr": m.pr_id is not None,
            }
            for m, pn in rows
        ],
        "total": total,
        "page": paging.page,
        "page_size": paging.page_size,
    }


@router.post("/mrs", status_code=201)
async def create_mr(body: MrBody, actor: Creator, session: Session) -> dict[str, Any]:
    scope = actor.scope_for("inventory", "create")
    if scope != Scope.ALL and body.project_id not in actor.project_ids:
        raise ForbiddenError(
            "NOT_PROJECT_MEMBER", "Anda belum terdaftar di tim proyek ini; hubungi manajer proyek."
        )
    mr = await mr_service.create(
        session,
        actor,
        project_id=body.project_id,
        wbs_code=body.wbs_code.upper(),
        cost_element_code=body.cost_element_code,
        site_warehouse=body.site_warehouse,
        need_date=body.need_date,
        purpose=body.purpose,
        lines=[mr_service.LineIn(x.item_code, x.qty) for x in body.lines],
    )
    await session.commit()
    return await _mr_detail(session, mr)


@router.get("/mrs/{mid}")
async def get_mr(mid: uuid.UUID, principal: Viewer, session: Session) -> dict[str, Any]:
    return await _mr_detail(session, await _mr(session, principal, mid))
