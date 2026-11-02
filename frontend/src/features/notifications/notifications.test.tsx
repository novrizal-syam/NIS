import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { HistoryPanel } from '@/features/audit/HistoryPanel';
import { AttachmentsPanel } from '@/features/dms/AttachmentsPanel';
import { session } from '@/lib/api';
import { json, mockApi } from '@/test/mockApi';
import { renderApp } from '@/test/render';

beforeEach(() => {
  localStorage.clear();
  session.setToken(null);
});
afterEach(() => vi.unstubAllGlobals());

const wrap = (ui: React.ReactNode) =>
  render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>);

describe('notification bell', () => {
  it('shows unread count, opens the list and follows the link', async () => {
    const { calls } = mockApi({
      handlers: {
        'GET /api/notifications/count': () => json({ unread: 2 }),
        'GET /api/notifications': () =>
          json({
            total: 2,
            unread: 2,
            items: [
              {
                id: 'n1',
                kind: 'approval_incoming',
                title: 'Persetujuan baru: PR-26-031',
                body: 'Seal kit',
                link: '/persetujuan',
                created_at: '2026-10-07T01:00:00Z',
                read: false,
              },
              {
                id: 'n2',
                kind: 'expiry_alert',
                title: 'BOSIET EMP-001 berakhir dalam 30 hari',
                body: '',
                link: '/master/employees',
                created_at: '2026-10-06T01:00:00Z',
                read: true,
              },
            ],
          }),
        'POST /api/notifications/n1/read': () => new Response(null, { status: 204 }),
        'GET /api/workflow/inbox': () =>
          json({ items: [], total: 0, page: 1, page_size: 25, counts: {} }),
      },
    });
    const user = userEvent.setup();
    renderApp('/');
    const bell = await screen.findByRole('button', { name: 'Notifikasi, 2 belum dibaca' });
    await user.click(bell);
    await user.click(await screen.findByRole('button', { name: /PR-26-031/ }));
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Persetujuan Saya' }),
    ).toBeInTheDocument();
    expect(calls.some((c) => c.key === 'POST /api/notifications/n1/read')).toBe(true);
  });
});

describe('history panel', () => {
  it('lists changes with before and after', async () => {
    mockApi({
      handlers: {
        'GET /api/audit/history/vendors/v1': () =>
          json({
            total: 1,
            page: 1,
            page_size: 10,
            items: [
              {
                id: 'a1',
                at: '2026-10-07T01:00:00Z',
                actor_name: 'Rina Wijaya',
                action: 'update',
                action_label: 'Ubah',
                entity_type: 'vendors',
                entity_id: 'v1',
                before: { status: 'qualified' },
                after: { status: 'blacklisted' },
                changed: ['status'],
                note: null,
                request_id: null,
              },
            ],
          }),
      },
    });
    wrap(<HistoryPanel entityType="vendors" entityId="v1" />);
    const item = (await screen.findByText('Rina Wijaya')).closest('li')!;
    expect(within(item).getByText('Ubah')).toBeInTheDocument();
    expect(within(item).getByText('qualified')).toHaveClass('line-through');
    expect(within(item).getByText('blacklisted')).toBeInTheDocument();
  });
});

describe('attachments panel', () => {
  it('refuses files over 20 MB before uploading', async () => {
    const { calls } = mockApi({
      handlers: { 'GET /api/attachments': () => json([]) },
    });
    const user = userEvent.setup();
    wrap(<AttachmentsPanel entityType="vendors" entityId="v1" canWrite />);
    expect(await screen.findByText('Belum ada lampiran.')).toBeInTheDocument();
    const big = new File(['x'], 'besar.pdf', { type: 'application/pdf' });
    Object.defineProperty(big, 'size', { value: 21 * 1024 * 1024 });
    await user.upload(screen.getByLabelText('Pilih file lampiran'), big);
    expect(await screen.findByRole('alert')).toHaveTextContent('maksimal 20 MB');
    expect(calls.some((c) => c.key === 'POST /api/attachments')).toBe(false);
  });

  it('hides upload controls without write access', async () => {
    mockApi({
      handlers: {
        'GET /api/attachments': () =>
          json([
            {
              id: 'f1',
              group_id: 'g1',
              version: 2,
              versions: 2,
              filename: 'siup.pdf',
              content_type: 'application/pdf',
              size: 2048,
              uploaded_by: 'Rina',
              uploaded_at: '2026-10-07T01:00:00Z',
              note: null,
            },
          ]),
      },
    });
    wrap(<AttachmentsPanel entityType="vendors" entityId="v1" canWrite={false} />);
    expect(await screen.findByText('siup.pdf')).toBeInTheDocument();
    expect(screen.getByText(/v2 · 2 KB · Rina/)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Unggah lampiran/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Unduh siup.pdf' })).toBeInTheDocument();
  });
});
