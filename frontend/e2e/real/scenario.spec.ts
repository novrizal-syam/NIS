/**
 * The whole money chain against the REAL backend (no mocks), each step done by the person who
 * does it in GEK, with the key screens checked in the browser. Runs only with E2E_REAL=1 and a
 * seeded e2e backend on :8000 (see README). It closes and reopens the current month, so run the
 * real suite with one worker: `E2E_REAL=1 npx playwright test e2e/real --workers=1`.
 *
 * PR → approval → RFQ (3 vendors) → award → PO → GR (BAST) → vendor invoice (3-way match)
 * → DOR → ticket signed with a disputed line → invoice + faktur → bank receipt → payroll
 * (SoD) → payment run (preparer / approver / releaser) → PPN paid and filed → month close
 * (and reopen); plus CAPEX to capitalisation and SOP release → training acknowledgement.
 */
import { expect, request, test, type APIRequestContext, type Page } from '@playwright/test';

const PASSWORD = 'E2e-Rahasia-2026';
const API = 'http://localhost:8000';
const U = {
  engineer: 'engineer@e2e.gek.co.id',
  hoo: 'hoo@e2e.gek.co.id',
  proc: 'proc@e2e.gek.co.id',
  planner: 'planner@e2e.gek.co.id',
  ap: 'ap@e2e.gek.co.id',
  fe: 'fe@e2e.gek.co.id',
  sup: 'sup@e2e.gek.co.id',
  billing: 'billing@e2e.gek.co.id',
  hcbp: 'hcbp@e2e.gek.co.id',
  hof: 'hof@e2e.gek.co.id',
  cashier: 'cashier@e2e.gek.co.id',
  tax: 'tax@e2e.gek.co.id',
  controller: 'controller@e2e.gek.co.id',
  director: 'director@e2e.gek.co.id',
  qhse: 'qhse@e2e.gek.co.id',
  aic: 'aic@e2e.gek.co.id',
};
const PDF = Buffer.from('%PDF-1.7\n1 0 obj<<>>endobj\n%%EOF');
// 1x1 PNG (what the signature pad sends).
const PNG =
  'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAAAAAA6fptVAAAACklEQVR4nGNgAAAAAgABSK+kcQAAAABJRU5ErkJggg==';

test.skip(!process.env.E2E_REAL, 'set E2E_REAL=1 with a seeded e2e backend on :8000');
test.describe.configure({ mode: 'serial' });
test.setTimeout(300_000);
test.use({ actionTimeout: 15_000 });
expect.configure({ timeout: 10_000 });

type Json = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

/** One signed-in API user (bearer token, own request context). */
class As {
  private constructor(
    private readonly ctx: APIRequestContext,
    private readonly token: string,
  ) {}

  static async login(email: string): Promise<As> {
    const ctx = await request.newContext({ baseURL: API });
    const r = await ctx.post('/api/auth/login', { data: { email, password: PASSWORD } });
    expect(r.status(), `login ${email}`).toBe(200);
    return new As(ctx, ((await r.json()) as Json).access_token as string);
  }

  private get h() {
    return { Authorization: `Bearer ${this.token}` };
  }

  async get(url: string, status = 200): Promise<Json> {
    const r = await this.ctx.get(url, { headers: this.h });
    expect(r.status(), `GET ${url}: ${await r.text()}`).toBe(status);
    return (await r.json()) as Json;
  }

  async post(url: string, data: unknown = {}, status: number | number[] = 200): Promise<Json> {
    const r = await this.ctx.post(url, { headers: this.h, data });
    const ok = Array.isArray(status) ? status : [status];
    expect(ok, `POST ${url}: ${r.status()} ${await r.text()}`).toContain(r.status());
    return (await r.json()) as Json;
  }

  async put(url: string, data: unknown, status = 200): Promise<Json> {
    const r = await this.ctx.put(url, { headers: this.h, data });
    expect(r.status(), `PUT ${url}: ${await r.text()}`).toBe(status);
    return (await r.json()) as Json;
  }

  async upload(entityType: string, entityId: string, note: string): Promise<string> {
    const r = await this.ctx.post('/api/attachments', {
      headers: this.h,
      multipart: {
        entity_type: entityType,
        entity_id: entityId,
        note,
        file: { name: 'dokumen.pdf', mimeType: 'application/pdf', buffer: PDF },
      },
    });
    expect(r.status(), `upload ${entityType}: ${await r.text()}`).toBe(201);
    return ((await r.json()) as Json).id as string;
  }

  async approve(requestId: string): Promise<void> {
    await this.post(`/api/workflow/requests/${requestId}/approve`);
  }
}

/** Today and yesterday in Asia/Jakarta (UTC+7, no daylight saving). */
function jakarta(offsetDays = 0): string {
  return new Date(Date.now() + 7 * 3600_000 + offsetDays * 86_400_000).toISOString().slice(0, 10);
}

async function signIn(page: Page, email: string) {
  await page.goto('/login');
  await page.getByRole('textbox', { name: 'Email' }).fill(email);
  await page.getByRole('textbox', { name: 'Kata sandi' }).fill(PASSWORD);
  await page.getByRole('button', { name: 'Masuk', exact: true }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Dasbor' })).toBeVisible();
}

async function signOut(page: Page) {
  await page.getByRole('button', { name: 'Menu pengguna', exact: true }).click();
  await page.getByRole('button', { name: /Keluar/ }).click();
  await page.waitForURL(/\/login/, { timeout: 15_000 });
}

test('whole scenario: purchase to pay, operate to cash, payroll, tax, close, CAPEX, SOP', async ({
  page,
}) => {
  const today = jakarta();
  const yesterday = jakarta(-1);
  const [year, month] = today.split('-').map(Number) as [number, number];
  const as: Record<keyof typeof U, As> = Object.fromEntries(
    await Promise.all(Object.entries(U).map(async ([k, e]) => [k, await As.login(e)])),
  );
  const project = (await as.planner.get('/api/projects?q=PRJ-26-903')).items[0] as Json;
  expect(project.number).toBe('PRJ-26-903');

  // ------------------------------------------------------------ purchase to pay
  let po: Json = {};
  await test.step('PR approved by Head of Operation, RFQ to three vendors, award, PO', async () => {
    const pr = await as.engineer.post(
      '/api/procurement/prs',
      {
        project_id: project.id,
        wbs_code: 'EXEC',
        cost_element_code: 'EQUIP-RENT',
        need_date: jakarta(20),
        delivery_location: 'Lapangan Mahakam, sumur MHK-7',
        purpose: 'Sewa genset untuk well testing',
        lines: [
          {
            description: 'Sewa genset 500 kVA (hari)',
            qty: '10',
            uom: 'hari',
            est_price: '4000000',
          },
        ],
      },
      201,
    );
    const sub = await as.engineer.post(`/api/procurement/prs/${pr.id}/submit`);
    expect(sub.approvals[0].approver_role).toBe('head_of_operation');
    await as.hoo.approve(sub.request_id);

    let rfq = await as.proc.post(
      '/api/procurement/rfqs',
      {
        pr_id: pr.id,
        category: 'equipment_rental',
        vendor_codes: ['V-E2E-A', 'V-E2E-B', 'V-E2E-C'],
      },
      201,
    );
    for (const [code, price, days] of [
      ['V-E2E-A', '4000000', 10],
      ['V-E2E-B', '3600000', 20],
      ['V-E2E-C', '3800000', 5],
    ] as const) {
      const q = (rfq.quotes as Json[]).find((x) => x.vendor_code === code)!;
      rfq = await as.proc.put(`/api/procurement/rfqs/${rfq.id}/quotes/${q.id}`, {
        unit_prices: { '1': price },
        delivery_days: days,
        payment_terms: '30 hari',
        valid_until: jakarta(60),
      });
    }
    const award = await as.proc.post(`/api/procurement/rfqs/${rfq.id}/award`, {
      vendor_code: 'V-E2E-C', // best score: fast delivery outweighs the 5 % price gap
    });
    expect(award.status).toBe('awarded');
    po = await as.proc.post(`/api/procurement/rfqs/${rfq.id}/po`, {}, [200, 201]);
    po = await as.proc.post(`/api/procurement/pos/${po.id}/issue`);
    expect(po.status).toBe('issued');
    expect(po.budget.commit_by_po).toBe('38000000');
  });

  await test.step('PO screen shows the issued order', async () => {
    await signIn(page, U.proc);
    await page.goto(`/pengadaan/po/${po.id}`);
    await expect(page.getByText(po.number).first()).toBeVisible();
    await expect(page.getByText('PT Citra Genset').first()).toBeVisible();
    await signOut(page);
  });

  let vi: Json = {};
  await test.step('Service GR with BAST by the project owner, vendor invoice matched by AP', async () => {
    const gr = await as.planner.post(
      '/api/inventory/grs',
      { po_id: po.id, received_date: today, lines: [{ seq: 1, qty: '10' }] },
      201,
    );
    expect(gr.kind).toBe('service');
    await as.planner.upload('goods_receipt', gr.id, 'BAST');
    const posted = await as.planner.post(`/api/inventory/grs/${gr.id}/post`);
    expect(posted.po_status).toBe('closed');

    vi = await as.ap.post(
      '/api/finance/vendor-invoices',
      {
        po_id: po.id,
        invoice_no: 'INV/CITRA/2026/0091',
        tax_invoice_no: '010.000-26.00000091',
        invoice_date: today,
        kind: 'service',
        dpp: '38000000',
        lines: [{ seq: 1, qty: '10', unit_price: '3800000' }],
      },
      201,
    );
    // PPN 11 % of DPP, PPh 23 2 % withheld on services.
    expect([vi.ppn, vi.pph23, vi.payable]).toEqual(['4180000', '760000', '41420000']);
    await as.ap.upload('vendor_invoice', vi.id, 'Invoice + faktur');
    vi = await as.ap.post(`/api/finance/vendor-invoices/${vi.id}/match`);
    expect(vi.status).toBe('approved');
  });

  // ------------------------------------------------------------ operate to cash
  let invoice: Json = {};
  await test.step('DOR approved, ticket signed with a disputed chemicals line', async () => {
    const opts = await as.fe.get(`/api/operations/dors/form-options?project_id=${project.id}`);
    const rate = (kind: string) =>
      (opts.rates as Json[]).find((r) => r.kind === kind)!.id as string;
    const dor = await as.fe.post(
      '/api/operations/dors/sync',
      {
        project_id: project.id,
        client_id: crypto.randomUUID(),
        base_version: null,
        dor: {
          report_date: yesterday,
          site_warehouse: 'WH-903',
          activities: 'Flowing sumur MHK-7 melalui separator, sampling tiap 2 jam.',
          technical: { oil_rate: 850, choke: 32 },
          hse: { incidents: 0, toolbox_talks: 1 },
          equipment: [
            {
              asset_code: 'AST-E2E-3',
              rate_id: rate('equipment'),
              operating: '18',
              standby: '4',
              breakdown: '0',
              rig: '2',
            },
          ],
          crew: [
            {
              employee_code: 'E-E2E-3',
              rate_id: rate('personnel'),
              hours: '10',
              overtime_hours: '2',
            },
          ],
          consumables: [{ item_code: 'ITM-E2E', rate_id: rate('consumable'), qty: '2' }],
        },
      },
      201,
    );
    const sub = await as.fe.post(`/api/operations/dors/${dor.id}/submit`);
    await as.sup.approve(sub.request_id);

    const tk = await as.billing.post(
      '/api/billing/tickets',
      { project_id: project.id, date_from: yesterday, date_to: yesterday },
      201,
    );
    const chem = (tk.lines as Json[]).find((x) => x.kind === 'consumable')!;
    const signed = await as.billing.post(`/api/billing/tickets/${tk.id}/sign`, {
      signer_name: 'Pak Company Man',
      signature: PNG,
      acceptance_no: 'SES-4500099999',
      disputes: [{ line_id: chem.id, reason: 'Pemakaian kimia belum disepakati' }],
    });
    expect(signed.status).toBe('signed');
    expect(signed.disputed_value).toBe('13200000');
    const disputes = await as.billing.get('/api/billing/disputes');
    expect(JSON.stringify(disputes)).toContain('Pemakaian kimia belum disepakati');

    invoice = await as.billing.post(
      '/api/billing/invoices',
      { ticket_ids: [tk.id], invoice_date: today },
      201,
    );
    expect(invoice.subtotal).toBe(signed.value);
    invoice = await as.billing.post(`/api/billing/invoices/${invoice.id}/faktur`, {
      faktur_number: '04002600000000991',
      faktur_date: today,
    });
    expect(invoice.status).toBe('faktur_issued');
    await as.billing.post(`/api/billing/invoices/${invoice.id}/send`, {
      email: 'ap@kkks-e2e.co.id',
    });
  });

  await test.step('Bank receipt matched by invoice number; PPh 23 withheld by the client', async () => {
    const amount = Number(invoice.net_cash).toLocaleString('id-ID');
    const csv = `Tanggal;Keterangan;Jumlah;Referensi\n${today};TRF PT KKKS ${invoice.number};${amount};FT991\n`;
    const ctx = await request.newContext({ baseURL: API });
    const login = await ctx.post('/api/auth/login', {
      data: { email: U.billing, password: PASSWORD },
    });
    const token = ((await login.json()) as Json).access_token as string;
    const r = await ctx.post('/api/billing/bank-import', {
      headers: { Authorization: `Bearer ${token}` },
      multipart: { file: { name: 'mutasi.csv', mimeType: 'text/csv', buffer: Buffer.from(csv) } },
    });
    expect(r.status(), await r.text()).toBe(200);
    await ctx.dispose();
    const line = ((await as.billing.get('/api/billing/bank-lines')) as unknown as Json[]).find(
      (l) => l.suggested_invoice_number === invoice.number,
    )!;
    const receipt = await as.billing.post(`/api/billing/bank-lines/${line.id}/confirm`, {
      invoice_id: invoice.id,
    });
    expect(receipt.cash).toBe(invoice.net_cash);
    expect(receipt.pph23).toBe(invoice.pph23_expected);
  });

  await test.step('Invoice screen shows it paid', async () => {
    await signIn(page, U.billing);
    await page.goto(`/tagihan/invoice/${invoice.id}`);
    await expect(page.getByText(invoice.number).first()).toBeVisible();
    await expect(page.getByText('Lunas').first()).toBeVisible();
    await signOut(page);
  });

  // ------------------------------------------------------------ payroll and payment run
  let run: Json = {};
  await test.step('Payroll from DOR days; the calculator cannot approve, Head of Finance does', async () => {
    const d = new Date(`${today}T00:00:00Z`);
    const [py, pm] =
      d.getUTCDate() > 25 ? (month === 12 ? [year + 1, 1] : [year, month + 1]) : [year, month];
    run = await as.hcbp.post('/api/payroll/runs', { year: py, month: pm });
    expect(run.status).toBe('calculated');
    const detail = await as.hcbp.get(`/api/payroll/runs/${run.id}`);
    const slip = (detail.payslips as Json[]).find((x) => x.employee_code === 'E-E2E-3')!;
    expect(slip.site_days).toBeGreaterThanOrEqual(1);
    expect(slip.overtime_hours).toBe('2.00');
    const sub = await as.hcbp.post(`/api/payroll/runs/${run.id}/submit`);
    await as.hof.approve(sub.request_id);
    run = await as.hof.get(`/api/payroll/runs/${run.id}`);
    expect(run.status).toBe('approved');
  });

  await test.step('Payment run: AP prepares, Head of Finance approves, cashier releases', async () => {
    const bank = ((await as.ap.get('/api/treasury/bank-accounts')) as unknown as Json[]).find(
      (b) => b.code === 'BA-MDR-IDR',
    )!;
    const pr = await as.ap.post(
      '/api/treasury/payment-runs',
      {
        pay_date: today,
        bank_account_id: bank.id,
        items: [
          { kind: 'vendor_invoice', vendor_invoice_id: vi.id, amount: vi.payable },
          { kind: 'payroll', payroll_run_id: run.id, amount: run.net },
        ],
      },
      [200, 201],
    );
    const sub = await as.ap.post(`/api/treasury/payment-runs/${pr.id}/submit`);
    // The preparer may not release; three different people.
    await as.ap.post(`/api/treasury/payment-runs/${pr.id}/release`, {}, 403);
    await as.hof.approve(sub.request_id);
    const released = await as.cashier.post(`/api/treasury/payment-runs/${pr.id}/release`);
    expect(released.status).toBe('released');
    expect((await as.ap.get(`/api/finance/vendor-invoices/${vi.id}`)).status).toBe('paid');
    expect((await as.hof.get(`/api/payroll/runs/${run.id}`)).status).toBe('paid');
  });

  // ------------------------------------------------------------ tax and close
  await test.step('PPN for the month: billing code, paid with NTPN, filed', async () => {
    const ws = await as.tax.get(`/api/tax/periods/${year}/${month}`);
    const ppn = (ws.returns as Json[]).find((r) => r.tax_type === 'ppn')!;
    expect(Number(ppn.output_tax)).toBeGreaterThan(0);
    expect(Number(ppn.input_tax)).toBeGreaterThan(0);
    const url = `/api/tax/returns/${ppn.id}`;
    if (Number(ppn.amount) > 0) {
      await as.tax.post(`${url}/billing`, { billing_code: '123456789012345' });
      await as.tax.post(`${url}/pay`, {
        ntpn: 'ABCD1234EFGH5678',
        paid_on: today,
        method: 'direct',
      });
    }
    const filed = await as.tax.post(`${url}/file`, { bpe_no: 'BPE-E2E-0001', filed_on: today });
    expect(filed.status).toBe('filed');
  });

  await test.step('Month close by the Lead Controller, then reopened by Head of Finance', async () => {
    const url = `/api/close/periods/${year}/${month}`;
    const st = await as.controller.get(url);
    const blocking = (st.checks as Json[]).filter((c) => c.blocking && !c.ok);
    expect(blocking, JSON.stringify(blocking)).toEqual([]);
    const closed = await as.controller.post(`${url}/close`, {
      note: 'Penyusutan dan PPh dicatat terpisah; skenario end-to-end.',
    });
    expect(closed.status).toBe('closed');
    await signIn(page, U.controller);
    await page.goto('/keuangan/tutup-buku');
    await expect(page.getByText(/ditutup/i).first()).toBeVisible();
    await signOut(page);
    const reopened = await as.hof.post(`${url}/reopen`, {
      reason: 'Skenario end-to-end: periode dibuka kembali',
    });
    expect(reopened.status).toBe('open');
  });

  // ------------------------------------------------------------ CAPEX
  await test.step('CAPEX: Director approves, milestone to AUC, BAST, capitalised', async () => {
    const cpx = await as.hoo.post(
      '/api/capex',
      {
        title: 'Separator 3 fasa 1440 psi (E2E)',
        rjpp_ref: 'RJPP 2026-2030 · Well testing',
        asset_class: 'Well testing',
        equipment_type_code: 'WT-SEP',
        amount: '1000000000',
        funding: 'equity',
        day_rate: '25000000',
        internal_day_rate: '12000000',
        utilisation_pct: '55',
        opex_pct: '6',
        life_years: 8,
        salvage_pct: '10',
        rental_annual: '900000000',
        strategic_fit: 5,
        risk: 4,
        tax_group: 'kelompok_2',
      },
      [200, 201],
    );
    const sub = await as.hoo.post(`/api/capex/${cpx.id}/submit`);
    await as.director.approve(sub.request_id);
    const url = `/api/capex/${cpx.id}`;
    const m1 = await as.controller.post(`${url}/milestones`, {
      amount: '950000000',
      description: 'Termin 1 fabrikasi',
      vendor_code: 'V-E2E-A',
    });
    expect(m1.auc).toBe('950000000');
    const bast = await as.aic.upload('capex', cpx.id, 'BAST commissioning');
    await as.aic.post(`${url}/commission`, { attachment_id: bast, asset_code: 'AST-SEP-E2E' });
    const cap = await as.controller.post(`${url}/capitalise`, { on: today });
    expect(cap.status).toBe('capitalised');
    expect(cap.asset).toEqual({ code: 'AST-SEP-E2E', cost: '950000000' });
  });

  // ------------------------------------------------------------ SOP to training
  await test.step('SOP released by the Director assigns training to field engineers', async () => {
    const doc = await as.qhse.post(
      '/api/dms/controlled',
      {
        code: 'GEK-BPM-001-SOP-E2E',
        title: 'SOP Isolasi energi (LOTO) E2E',
        kind: 'sop',
        affected_roles: ['field_engineer'],
      },
      [200, 201],
    );
    const att = await as.qhse.upload('controlled_doc', doc.id, 'Revisi 0');
    const rev = await as.qhse.post(
      `/api/dms/controlled/${doc.id}/revisions`,
      { change_summary: 'Rev 0', attachment_id: att },
      [200, 201],
    );
    const sub = await as.qhse.post(`/api/dms/controlled/${doc.id}/revisions/${rev.id}/submit`);
    await as.director.approve(sub.request_id);
  });

  await test.step('Field engineer sees and acknowledges the SOP in Pelatihan', async () => {
    const mine = (await as.fe.get('/api/lms/my')) as unknown as Json[];
    const task = mine.find((a) => a.document?.code === 'GEK-BPM-001-SOP-E2E')!;
    expect(task.kind).toBe('acknowledge');
    await signIn(page, U.fe);
    await page.goto('/pelatihan');
    await expect(page.getByText('SOP Isolasi energi (LOTO) E2E').first()).toBeVisible();
    await signOut(page);
    const done = await as.fe.post(`/api/lms/assignments/${task.id}/acknowledge`);
    expect(done.status).toBe('completed');
  });

  await test.step('Director sees the live process map', async () => {
    await signIn(page, U.director);
    await expect(page.getByText('Peta proses').first()).toBeVisible();
    await expect(page.getByText('Belanja & kas keluar').first()).toBeVisible();
  });
});
