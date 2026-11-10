"""Phase 10e: main pages stay under 2 s with 50,000 transactions.

Opt-in (it seeds ~200k rows): `PERF=1 pytest tests/test_performance.py -s`. Seeds 50,000 posted
journals (100,000 lines) over ten months, 5,000 customer and 5,000 vendor invoices, 50,000 audit
records and 2,000 notifications with SQL, then times the main screens through the API."""

import os
import time
from collections.abc import Awaitable, Callable

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.auth.models import User

pytestmark = pytest.mark.skipif(os.environ.get("PERF") != "1", reason="set PERF=1 to run")
MakeUser = Callable[..., Awaitable[User]]
Login = Callable[..., Awaitable[dict[str, str]]]
LIMIT_S = 2.0
N = 50_000

SEED = [
    """INSERT INTO clients (code, name) VALUES ('C-PERF', 'PT Klien Uji')""",
    """INSERT INTO vendors (code, name, category) VALUES ('V-PERF', 'PT Vendor Uji', 'rental')""",
    """INSERT INTO journal_entries (number, entry_date, period, description, source_type,
            source_id, event, total, posted_at)
        SELECT 'PJ-' || g, d, to_char(d, 'YYYY-MM'), 'Transaksi uji ' || g, 'perf', g::text,
               'manual', 1000 + g, now()
        FROM generate_series(1, :n) g, LATERAL (SELECT date '2026-01-01' + (g % 300) AS d) x""",
    """INSERT INTO journal_lines (entry_id, seq, account_code, debit, credit, project_id)
        SELECT e.id, 1, (ARRAY['5300','6100','1210','5400'])[1 + (e.total::bigint % 4)],
               e.total, 0, NULL
        FROM journal_entries e WHERE e.source_type = 'perf'""",
    """INSERT INTO journal_lines (entry_id, seq, account_code, debit, credit)
        SELECT e.id, 2, (ARRAY['1110','4100','2110'])[1 + (e.total::bigint % 3)], 0, e.total
        FROM journal_entries e WHERE e.source_type = 'perf'""",
    """INSERT INTO customer_invoices (number, client_code, status, invoice_date, due_date, subtotal,
            dpp_other, ppn, total, net_cash)
        SELECT 'INV-P-' || g, 'C-PERF', (ARRAY['sent','paid','faktur_issued'])[1 + g % 3],
               date '2026-01-01' + (g % 300), date '2026-01-31' + (g % 300),
               10000000, 9166667, 1100000, 11100000, 10900000
        FROM generate_series(1, 5000) g""",
    """INSERT INTO vendor_invoices (number, vendor_code, invoice_no, invoice_date, kind, term_days,
            due_date, dpp, ppn, payable, status)
        SELECT 'VI-P-' || g, 'V-PERF', 'INV/P/' || g, date '2026-01-01' + (g % 300), 'service', 30,
               date '2026-01-31' + (g % 300), 5000000, 550000, 5450000,
               (ARRAY['approved','paid','draft'])[1 + g % 3]
        FROM generate_series(1, 5000) g""",
    """INSERT INTO audit_log (actor_id, action, entity_type, entity_id, after)
        SELECT NULL, 'update', 'perf', g::text, jsonb_build_object('n', g)
        FROM generate_series(1, :n) g""",
]

PAGES = [
    "/api/ledger/journals?page=1",
    "/api/ledger/journals?page=500&q=uji",
    "/api/ledger/reports/trial-balance",
    "/api/ledger/reports/general-ledger?account=1110&date_from=2026-06-01&date_to=2026-06-30",
    "/api/ledger/reports/profit-loss",
    "/api/ledger/reports/balance-sheet",
    "/api/ledger/reports/cash-flow?date_from=2026-01-01&date_to=2026-10-31",
    "/api/billing/invoices",
    "/api/billing/ar-aging",
    "/api/finance/vendor-invoices",
    "/api/audit?page=1",
    "/api/dashboard/process-map",
    "/api/dashboard/okr",
    "/api/dashboard/roles/finance",
    "/api/notifications",
]


async def test_main_pages_under_two_seconds_with_50k_transactions(
    client: AsyncClient,
    make_user: MakeUser,
    login: Login,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    user = await make_user("director", "lead_controller", "finance_officer")
    h = await login(user)
    async with sessionmaker() as s:
        for sql in SEED:
            await s.execute(text(sql), {"n": N} if ":n" in sql else {})
        await s.execute(
            text(
                "INSERT INTO notifications (user_id, kind, title, email_status) "
                "SELECT :u, 'perf', 'Uji ' || g, 'none' FROM generate_series(1, 2000) g"
            ),
            {"u": user.id},
        )
        await s.commit()
        await s.execute(text("ANALYZE"))
    timings = []
    for page in PAGES:
        await client.get(page, headers=h)  # warm-up (connection, caches)
        start = time.perf_counter()
        r = await client.get(page, headers=h)
        took = time.perf_counter() - start
        assert r.status_code == 200, (page, r.status_code, r.text[:200])
        timings.append((page, took))
    print("\nPage timings with 50,000 journals:")
    for page, took in timings:
        print(f"  {took * 1000:7.0f} ms  {page}")
    slow = [(p, round(t, 2)) for p, t in timings if t > LIMIT_S]
    assert slow == []
