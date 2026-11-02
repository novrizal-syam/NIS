import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { session } from '@/lib/api';
import { json, mockApi } from '@/test/mockApi';
import { renderApp } from '@/test/render';
import type { InboxItem } from './api';

const item = (n: number, doc_type = 'purchase_requisition'): InboxItem => ({
  request_id: `r${n}`,
  doc_type,
  doc_type_label: doc_type === 'cash_advance' ? 'Uang muka kerja' : 'Purchase Requisition',
  doc_number: `PR-26-03${n}`,
  title: `Pompa booster ${n}`,
  amount: '12500000',
  currency: 'IDR',
  requester_name: 'Budi Engineer',
  submitted_at: '2026-10-07T01:00:00Z',
  step_label: 'head_of_operation',
  due_at: '2026-10-09T01:00:00Z',
  overdue: n === 2,
  escalated: false,
});

function inbox(items: InboxItem[]) {
  return () =>
    json({
      items,
      total: items.length,
      page: 1,
      page_size: 25,
      counts: { purchase_requisition: items.length },
    });
}

beforeEach(() => {
  localStorage.clear();
  session.setToken(null);
  session.setActiveRole(null);
});
afterEach(() => vi.unstubAllGlobals());

describe('Persetujuan Saya', () => {
  it('lists waiting documents with id-ID money and a count badge', async () => {
    mockApi({
      handlers: {
        'GET /api/workflow/inbox': inbox([item(1), item(2)]),
        'GET /api/workflow/inbox/count': () => json({ count: 2 }),
      },
    });
    renderApp('/persetujuan');
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Persetujuan Saya' }),
    ).toBeInTheDocument();
    const row = (await screen.findByText('PR-26-031')).closest('tr')!;
    expect(within(row).getByText('Rp 12.500.000')).toBeInTheDocument();
    const nav = screen.getAllByRole('navigation', { name: 'Menu utama' })[0]!;
    expect(within(nav).getByRole('link', { name: /Persetujuan Saya\s*2/ })).toBeInTheDocument();
  });

  it('allows bulk approve only after choosing one document type', async () => {
    const { calls } = mockApi({
      handlers: {
        'GET /api/workflow/inbox': inbox([item(1), item(2)]),
        'POST /api/workflow/approvals/bulk': () =>
          json([
            { request_id: 'r1', ok: true, code: null, message: null },
            { request_id: 'r2', ok: true, code: null, message: null },
          ]),
      },
    });
    const user = userEvent.setup();
    renderApp('/persetujuan');
    await screen.findByText('PR-26-031');
    const bulk = screen.getByRole('button', { name: /Setujui terpilih/ });
    expect(bulk).toBeDisabled();
    expect(screen.getByLabelText('Pilih PR-26-031')).toBeDisabled();

    await user.selectOptions(screen.getByLabelText('Jenis dokumen'), 'purchase_requisition');
    await user.click(await screen.findByLabelText('Pilih semua di halaman ini'));
    await user.click(screen.getByRole('button', { name: 'Setujui terpilih (2)' }));
    expect(await screen.findByText('2 dokumen disetujui.')).toBeInTheDocument();
    const body = JSON.parse(
      String(calls.find((c) => c.key === 'POST /api/workflow/approvals/bulk')!.init!.body),
    ) as { doc_type: string; request_ids: string[] };
    expect(body).toEqual({ doc_type: 'purchase_requisition', request_ids: ['r1', 'r2'] });
  });

  it('requires a reason to reject', async () => {
    const { calls } = mockApi({
      handlers: {
        'GET /api/workflow/inbox': inbox([item(1)]),
        'POST /api/workflow/requests/r1/reject': () => json({}),
      },
    });
    const user = userEvent.setup();
    renderApp('/persetujuan');
    const row = (await screen.findByText('PR-26-031')).closest('tr')!;
    await user.click(within(row).getByRole('button', { name: 'Tolak' }));
    const dialog = await screen.findByRole('dialog', { name: 'Tolak PR-26-031' });
    await user.click(within(dialog).getByRole('button', { name: 'Tolak' }));
    expect(within(dialog).getByText('Alasan wajib diisi.')).toBeInTheDocument();
    // Focus stays in the field while typing (regression: focus jumped to the close button).
    await user.click(within(dialog).getByLabelText(/Alasan/));
    expect(calls.some((c) => c.key.endsWith('/reject'))).toBe(false);

    await user.type(within(dialog).getByLabelText(/Alasan/), 'Spesifikasi belum lengkap');
    await user.click(within(dialog).getByRole('button', { name: 'Tolak' }));
    expect(await screen.findByText(/PR-26-031 ditolak/)).toBeInTheDocument();
    const sent = calls.find((c) => c.key.endsWith('/reject'))!;
    expect(JSON.parse(String(sent.init!.body))).toEqual({ comment: 'Spesifikasi belum lengkap' });
  });

  it('shows the backend reason when approval is refused (segregation of duties)', async () => {
    mockApi({
      handlers: {
        'GET /api/workflow/inbox': inbox([item(1)]),
        'POST /api/workflow/requests/r1/approve': () =>
          json(
            {
              code: 'SOD_SELF_APPROVAL',
              message: 'Anda tidak dapat menyetujui atau menolak dokumen yang Anda ajukan sendiri.',
            },
            403,
          ),
      },
    });
    const user = userEvent.setup();
    renderApp('/persetujuan');
    const row = (await screen.findByText('PR-26-031')).closest('tr')!;
    await user.click(within(row).getByRole('button', { name: 'Setujui' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('dokumen yang Anda ajukan sendiri');
  });
});

describe('Dialog focus', () => {
  it('keeps focus in the textarea while typing', async () => {
    mockApi({ handlers: { 'GET /api/workflow/inbox': inbox([item(1)]) } });
    const user = userEvent.setup();
    renderApp('/persetujuan');
    const row = (await screen.findByText('PR-26-031')).closest('tr')!;
    await user.click(within(row).getByRole('button', { name: 'Tolak' }));
    const dialog = await screen.findByRole('dialog');
    const field = within(dialog).getByLabelText(/Alasan/);
    await user.click(field);
    await user.keyboard('abc');
    expect(field).toHaveFocus();
    expect(field).toHaveValue('abc');
    await user.keyboard('{Escape}');
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });
});
