import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { session } from '@/lib/api';
import { json, makeMe, mockApi } from '@/test/mockApi';
import { renderApp } from '@/test/render';

beforeEach(() => {
  localStorage.clear();
  session.setToken(null);
});
afterEach(() => vi.unstubAllGlobals());

it('lets a learner acknowledge a new SOP revision and hides manager tabs', async () => {
  let acked = false;
  mockApi({
    me: makeMe({
      roles: [{ code: 'field_engineer', name: 'Field Engineer' }],
      permissions: { lms: { view: 'own' } },
    }),
    handlers: {
      'GET /api/lms/my': () =>
        json(
          acked
            ? []
            : [
                {
                  id: 'a1',
                  kind: 'acknowledge',
                  reason: 'sop_revision',
                  course: null,
                  document: {
                    code: 'GEK-BPM-001-SOP-12',
                    revision: 1,
                    title: 'SOP Isolasi energi',
                    document_id: 'd1',
                    revision_id: 'r1',
                  },
                  due_date: '2026-11-23',
                  overdue: false,
                  status: 'assigned',
                  score: null,
                },
              ],
        ),
      'POST /api/lms/assignments/a1/acknowledge': () => {
        acked = true;
        return json({ id: 'a1', status: 'completed' });
      },
    },
  });
  const user = userEvent.setup();
  renderApp('/pelatihan');
  expect(await screen.findByText(/GEK-BPM-001-SOP-12 Rev\.1/)).toBeInTheDocument();
  expect(screen.getByText('Revisi SOP')).toBeInTheDocument();
  expect(screen.queryByRole('tab', { name: 'Matriks kompetensi' })).toBeNull();
  await user.click(screen.getByRole('button', { name: 'Saya sudah membaca dan memahami' }));
  expect(await screen.findByText('Tidak ada pelatihan yang menunggu.')).toBeInTheDocument();
});
