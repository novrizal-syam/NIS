"""Manual journals (DOA manual_journal -> Lead Controller) and the opening-balance import.

Opening balance (once, as of the go-live date), one workbook with sheets:
  GL     account, debit, credit, memo            (any postable account except the control
                                                  accounts below, which come from their sheets)
  AR     client, invoice_no, invoice_date, due_date, amount     -> Dr 1210, open AR items
  AP     vendor, invoice_no, invoice_date, due_date, amount     -> Cr 2110, open AP items
  Stock  warehouse, item, qty, value                            -> Dr 1310, stock balances
  Assets asset, cost, accumulated_depreciation                  -> Dr 1510 / Cr 1590
The whole workbook must balance (equity, e.g. 3200 retained earnings, in GL); nothing is
written when any row is wrong.
"""

import io
import re
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from openpyxl import load_workbook
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.principal import Principal
from app.billing.models import CustomerInvoice
from app.core.errors import AppError, ConflictError
from app.finance.models import ManualJournal, VendorInvoice
from app.inventory import stock_service as stock
from app.master.models import Account, Asset, Client, Item, Vendor, Warehouse
from app.services import audit, ledger, numbering
from app.services.audit import AuditAction
from app.setup import service as settings_store
from app.workflow import engine
from app.workflow.models import ApprovalRequest

DOC = "manual_journal"
OPENING_KEY = "ledger.opening_date"
CONTROL = {"1210": "AR", "2110": "AP", "1310": "Stock", "1510": "Assets", "1590": "Assets"}
ZERO = Decimal(0)


# ---------------------------------------------------------------- manual journals


def _lines(raw: list[dict[str, Any]]) -> list[ledger.JLine]:
    out = []
    for r in raw:
        out.append(
            ledger.JLine(
                str(r["account"]),
                debit=Decimal(str(r.get("debit") or 0)),
                credit=Decimal(str(r.get("credit") or 0)),
                memo=r.get("memo") or None,
                project_id=uuid.UUID(r["project_id"]) if r.get("project_id") else None,
                cost_element=r.get("cost_element") or None,
                cost_center=r.get("cost_center") or None,
                asset=r.get("asset") or None,
                partner_type=r.get("partner_type") or None,
                partner_code=r.get("partner_code") or None,
            )
        )
    return out


async def _validate(session: AsyncSession, entry_date: date, raw: list[dict[str, Any]]) -> Decimal:
    lines = _lines(raw)
    if len(lines) < 2:
        raise ledger.LedgerError("JOURNAL_TOO_SHORT", "Jurnal minimal terdiri dari dua baris.")
    debit = sum((x.debit for x in lines), ZERO)
    credit = sum((x.credit for x in lines), ZERO)
    for x in lines:
        if x.debit < 0 or x.credit < 0 or (x.debit > 0) == (x.credit > 0):
            raise ledger.LedgerError(
                "JOURNAL_LINE_INVALID", f"Baris {x.account}: isi debit atau kredit, tidak keduanya."
            )
    if debit != credit:
        raise ledger.LedgerError(
            "JOURNAL_UNBALANCED", f"Jurnal tidak seimbang: debit {debit} ≠ kredit {credit}."
        )
    codes = {x.account for x in lines}
    ok = {
        a.code
        for a in (await session.execute(select(Account).where(Account.code.in_(codes)))).scalars()
        if a.is_active and a.is_postable
    }
    if bad := sorted(codes - ok):
        raise ledger.LedgerError(
            "ACCOUNT_NOT_POSTABLE", f"Akun tidak bisa diposting: {', '.join(bad)}."
        )
    await ledger.check_period(session, entry_date)
    return debit


async def create_manual(
    session: AsyncSession,
    actor: Principal,
    entry_date: date,
    description: str,
    raw: list[dict[str, Any]],
) -> ManualJournal:
    total = await _validate(session, entry_date, raw)
    mj = ManualJournal(
        number=await numbering.next(session, "MJ", on=entry_date),
        entry_date=entry_date,
        description=description.strip(),
        lines=raw,
        total=total,
        status="draft",
        created_by=actor.id,
    )
    session.add(mj)
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.CREATE,
        entity_type=DOC,
        entity_id=mj.id,
        actor_id=actor.id,
        after={"number": mj.number, "total": total, "lines": len(raw)},
    )
    return mj


async def update_manual(
    session: AsyncSession,
    actor: Principal,
    mj: ManualJournal,
    entry_date: date,
    description: str,
    raw: list[dict[str, Any]],
) -> ManualJournal:
    if mj.status != "draft":
        raise ConflictError("NOT_DRAFT", f"{mj.number} tidak lagi draf.")
    mj.total = await _validate(session, entry_date, raw)
    mj.entry_date, mj.description, mj.lines = entry_date, description.strip(), raw
    await session.flush()
    await audit.record(
        session,
        action=AuditAction.UPDATE,
        entity_type=DOC,
        entity_id=mj.id,
        actor_id=actor.id,
        after={"total": mj.total},
    )
    return mj


async def submit_manual(
    session: AsyncSession, actor: Principal, mj: ManualJournal
) -> ApprovalRequest:
    if mj.status != "draft":
        raise ConflictError("NOT_DRAFT", f"{mj.number} tidak lagi draf.")
    await _validate(session, mj.entry_date, mj.lines)
    req = await engine.submit(
        session,
        actor,
        doc_type=DOC,
        doc_id=mj.id,
        doc_number=mj.number,
        title=f"Jurnal manual {mj.number}: {mj.description[:80]}",
        amount=mj.total,
    )
    mj.status, mj.request_id, mj.reject_reason = "awaiting_approval", req.id, None
    await session.flush()
    return req


async def _on_approved(session: AsyncSession, request: ApprovalRequest) -> None:
    mj = await session.get(ManualJournal, uuid.UUID(request.doc_id), with_for_update=True)
    if mj is None or mj.status != "awaiting_approval":
        return
    acted = [s.acted_by for s in request.steps if s.acted_by]
    entry = await ledger.post_journal(
        session,
        entry_date=mj.entry_date,
        description=mj.description,
        lines=_lines(mj.lines),
        source_type=DOC,
        source_id=mj.id,
        source_number=mj.number,
        by=acted[-1] if acted else None,
        event="manual",
    )
    mj.status, mj.journal_id = "posted", entry.id
    await session.flush()


async def _on_rejected(session: AsyncSession, request: ApprovalRequest) -> None:
    mj = await session.get(ManualJournal, uuid.UUID(request.doc_id), with_for_update=True)
    if mj is None or mj.status != "awaiting_approval":
        return
    acted = [s for s in request.steps if s.acted_by]
    mj.status, mj.request_id = "draft", None
    mj.reject_reason = (acted[-1].comment if acted else None) or None
    await session.flush()


engine.register_document(DOC, on_approved=_on_approved, on_rejected=_on_rejected)


# ---------------------------------------------------------------- opening balance


@dataclass
class OpeningResult:
    gl_lines: int = 0
    ar_items: int = 0
    ap_items: int = 0
    stock_rows: int = 0
    assets: int = 0
    total: Decimal = ZERO
    journal: str | None = None
    errors: list[str] = field(default_factory=list)


def _norm(v: Any) -> str:
    return re.sub(r"\s+", " ", str(v or "").strip().lower())


def _num(v: Any) -> Decimal | None:
    if v in (None, ""):
        return ZERO
    try:
        if isinstance(v, (int, float, Decimal)):
            return Decimal(str(v))
        s = str(v).strip().replace("Rp", "").replace(" ", "")
        if "," in s and "." in s:
            s = s.replace(".", "").replace(",", ".")
        elif s.count(".") > 1:
            s = s.replace(".", "")
        elif "," in s:
            s = s.replace(",", ".")
        return Decimal(s)
    except InvalidOperation:
        return None


def _day(v: Any) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    try:
        return date.fromisoformat(str(v).strip())
    except ValueError:
        return None


def _sheet(wb: Any, name: str) -> list[tuple[int, dict[str, Any]]]:
    ws = next((wb[n] for n in wb.sheetnames if _norm(n) == name.lower()), None)
    if ws is None:
        return []
    it = ws.iter_rows(values_only=True)
    head = [_norm(h) for h in next(it, ())]
    out = []
    for i, r in enumerate(it, start=2):
        if any(c not in (None, "") for c in r):
            out.append((i, {head[k]: r[k] for k in range(min(len(head), len(r)))}))
    return out


async def import_opening(
    session: AsyncSession, actor: Principal, data: bytes, as_of: date
) -> OpeningResult:
    if await settings_store.get(session, OPENING_KEY, None):
        raise ConflictError(
            "OPENING_DONE", "Saldo awal sudah diimpor; koreksi dengan jurnal manual."
        )
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:
        raise AppError(
            "XLSX_INVALID", "Berkas bukan Excel (.xlsx) yang valid.", status_code=422
        ) from exc
    res = OpeningResult()
    err = res.errors.append
    accounts = {a.code: a for a in (await session.execute(select(Account))).scalars()}
    clients = {c.code for c in (await session.execute(select(Client))).scalars()}
    vendors = {v.code: v for v in (await session.execute(select(Vendor))).scalars()}
    items = {i.code for i in (await session.execute(select(Item))).scalars()}
    whs = {w.code for w in (await session.execute(select(Warehouse))).scalars()}
    assets = {a.code: a for a in (await session.execute(select(Asset))).scalars()}
    lines: list[ledger.JLine] = []
    ar: list[tuple[str, str, date, date, Decimal]] = []
    ap: list[tuple[str, str, date, date, Decimal]] = []
    stk: list[tuple[str, str, Decimal, Decimal]] = []
    ast: list[tuple[str, Decimal, Decimal]] = []

    for row, r in _sheet(wb, "GL"):
        code = str(r.get("account") or r.get("akun") or "").strip()
        d, c = _num(r.get("debit")), _num(r.get("credit") or r.get("kredit"))
        where = f"GL baris {row}"
        if code in CONTROL:
            err(f"{where}: akun {code} diisi dari sheet {CONTROL[code]}.")
        elif code not in accounts or not accounts[code].is_postable:
            err(f"{where}: akun {code} tidak dikenal atau bukan akun posting.")
        if d is None or c is None or (d > 0) == (c > 0):
            err(f"{where}: isi debit atau kredit (salah satu).")
            continue
        lines.append(ledger.JLine(code, debit=d, credit=c, memo=str(r.get("memo") or "Saldo awal")))
    for sheet, target, known in (("AR", ar, clients), ("AP", ap, set(vendors))):
        for row, r in _sheet(wb, sheet):
            who = str(r.get("client") or r.get("klien") or r.get("vendor") or "").strip()
            no = str(r.get("invoice_no") or r.get("no invoice") or "").strip()
            inv_d, due = _day(r.get("invoice_date")), _day(r.get("due_date"))
            amount = _num(r.get("amount") or r.get("jumlah"))
            where = f"{sheet} baris {row}"
            if who not in known:
                err(f"{where}: {who or '(kosong)'} tidak ada di Data Master.")
            if not no or len(no) > 20:
                err(f"{where}: nomor invoice wajib (maks. 20 karakter).")
            if inv_d is None or due is None:
                err(f"{where}: tanggal invoice dan jatuh tempo wajib (YYYY-MM-DD).")
            if amount is None or amount <= 0:
                err(f"{where}: jumlah harus > 0.")
            if not res.errors or not res.errors[-1].startswith(where):
                target.append((who, no, inv_d or as_of, due or as_of, amount or ZERO))
    for row, r in _sheet(wb, "Stock"):
        wh, it = (
            str(r.get("warehouse") or r.get("gudang") or "").strip(),
            str(r.get("item") or "").strip(),
        )
        qty, val = _num(r.get("qty")), _num(r.get("value") or r.get("nilai"))
        where = f"Stock baris {row}"
        if wh not in whs or it not in items:
            err(f"{where}: gudang {wh} atau item {it} tidak dikenal.")
        elif qty is None or val is None or qty <= 0 or val < 0:
            err(f"{where}: qty > 0 dan nilai ≥ 0.")
        else:
            stk.append((wh, it, qty, val))
    for row, r in _sheet(wb, "Assets"):
        code = str(r.get("asset") or r.get("aset") or "").strip()
        cost = _num(r.get("cost") or r.get("harga perolehan"))
        acc = _num(r.get("accumulated_depreciation") or r.get("akumulasi penyusutan"))
        where = f"Assets baris {row}"
        if code not in assets:
            err(f"{where}: aset {code} tidak ada di Data Master.")
        elif cost is None or acc is None or cost <= 0 or acc < 0 or acc > cost:
            err(f"{where}: harga perolehan > 0 dan akumulasi penyusutan 0..harga perolehan.")
        else:
            ast.append((code, cost, acc))
    if res.errors:
        return res

    for who, _no, _d, _due, amount in ar:
        lines.append(
            ledger.JLine("1210", debit=amount, partner_type="client", partner_code=who, memo=_no)
        )
    for who, _no, _d, _due, amount in ap:
        lines.append(
            ledger.JLine("2110", credit=amount, partner_type="vendor", partner_code=who, memo=_no)
        )
    stock_total = sum((v for *_x, v in stk), ZERO)
    if stock_total > 0:
        lines.append(ledger.JLine("1310", debit=stock_total, memo="Persediaan awal"))
    for code, cost, acc in ast:
        lines.append(ledger.JLine("1510", debit=cost, asset=code, memo="Aset tetap awal"))
        if acc > 0:
            lines.append(
                ledger.JLine("1590", credit=acc, asset=code, memo="Akumulasi penyusutan awal")
            )
    debit = sum((x.debit for x in lines), ZERO)
    credit = sum((x.credit for x in lines), ZERO)
    if debit != credit:
        res.errors.append(
            f"Saldo awal tidak seimbang: debit {debit} ≠ kredit {credit} "
            "(isi ekuitas, mis. 3200 laba ditahan, di sheet GL)."
        )
        return res
    entry = await ledger.post_journal(
        session,
        entry_date=as_of,
        description=f"Saldo awal per {as_of:%d/%m/%Y}",
        lines=lines,
        source_type="opening_balance",
        source_id=as_of.isoformat(),
        by=actor.id,
        event="opening_balance",
    )
    for who, no, inv_d, due, amount in ar:
        session.add(
            CustomerInvoice(
                number=no,
                client_code=who,
                status="sent",
                invoice_date=inv_d,
                due_date=due,
                subtotal=amount,
                total=amount,
                net_cash=amount,
                is_opening=True,
                created_by=actor.id,
            )
        )
    for who, no, inv_d, due, amount in ap:
        v = vendors[who]
        session.add(
            VendorInvoice(
                number=await numbering.next(session, "VI", on=as_of),
                vendor_code=who,
                po_id=None,
                invoice_no=no,
                invoice_date=inv_d,
                kind="goods",
                term_days=max((due - inv_d).days, 0),
                due_date=due,
                dpp=amount,
                ppn=ZERO,
                payable=amount,
                status="approved",
                is_opening=True,
                created_by=actor.id,
                note=f"Saldo awal {v.name}",
            )
        )
    doc = stock.Doc("opening_balance", as_of.isoformat(), "Saldo awal", actor.id)
    for wh, it, qty, val in stk:
        await stock.receive(session, it, wh, qty, val, doc, kind="opening")
    for code, cost, acc in ast:
        assets[code].acquisition_cost, assets[code].accumulated_depreciation = cost, acc
    await settings_store.put(session, OPENING_KEY, as_of.isoformat(), actor.id)
    res.gl_lines = len(lines)
    res.ar_items, res.ap_items, res.stock_rows, res.assets = len(ar), len(ap), len(stk), len(ast)
    res.total, res.journal = debit, entry.number
    await session.flush()
    await audit.record(
        session,
        action="import",
        entity_type="opening_balance",
        entity_id=as_of.isoformat(),
        actor_id=actor.id,
        after={
            "journal": entry.number,
            "total": debit,
            "ar": len(ar),
            "ap": len(ap),
            "stock": len(stk),
            "assets": len(ast),
        },
    )
    return res
