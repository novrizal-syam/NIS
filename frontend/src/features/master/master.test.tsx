import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { session } from '@/lib/api';
import { json, mockApi } from '@/test/mockApi';
import { renderApp } from '@/test/render';
import type { EntityMeta } from './api';

const META: EntityMeta = {
  key: 'employees',
  label: 'Karyawan',
  title_field: 'full_name',
  has_active: true,
  filters: ['is_field'],
  can: { create: true, edit: true, delete: false, export: true },
  fields: [
    {
      name: 'code',
      label: 'NIP',
      kind: 'text',
      required: true,
      key: true,
      max_length: 20,
      choices: [],
      ref: null,
      in_list: true,
      sensitive: false,
      min_value: null,
      max_value: null,
      default: null,
    },
    {
      name: 'full_name',
      label: 'Nama lengkap',
      kind: 'text',
      required: true,
      key: false,
      max_length: 120,
      choices: [],
      ref: null,
      in_list: true,
      sensitive: false,
      min_value: null,
      max_value: null,
      default: null,
    },
    {
      name: 'is_field',
      label: 'Personel lapangan',
      kind: 'bool',
      required: false,
      key: false,
      max_length: null,
      choices: [],
      ref: null,
      in_list: true,
      sensitive: false,
      min_value: null,
      max_value: null,
      default: null,
    },
    {
      name: 'basic_salary',
      label: 'Gaji pokok',
      kind: 'idr',
      required: false,
      key: false,
      max_length: null,
      choices: [],
      ref: null,
      in_list: true,
      sensitive: true,
      min_value: 0,
      max_value: null,
      default: null,
    },
  ],
};

const rowsPage = (total: number) =>
  json({
    items: [
      {
        id: 'e1',
        code: 'EMP-001',
        full_name: 'Agus Operator',
        is_field: true,
        basic_salary: '9500000',
        is_active: true,
        is_demo: true,
      },
    ].slice(0, total),
    total,
    page: 1,
    page_size: 25,
  });

beforeEach(() => {
  localStorage.clear();
  session.setToken(null);
});
afterEach(() => vi.unstubAllGlobals());

describe('generic master data screen', () => {
  it('renders columns from metadata with id-ID money and the entity title', async () => {
    mockApi({
      handlers: {
        'GET /api/master/employees/meta': () => json(META),
        'GET /api/master/employees': () => rowsPage(1),
      },
    });
    renderApp('/master/employees');
    expect(await screen.findByRole('heading', { level: 1, name: 'Karyawan' })).toBeInTheDocument();
    const row = (await screen.findByRole('button', { name: 'EMP-001' })).closest('tr')!;
    expect(within(row).getByText('Rp 9.500.000')).toBeInTheDocument();
    expect(within(row).getByText('Ya')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Ekspor Excel/ })).toBeInTheDocument();
  });

  it('validates required fields and shows server field errors', async () => {
    const { calls } = mockApi({
      handlers: {
        'GET /api/master/employees/meta': () => json(META),
        'GET /api/master/employees': () => rowsPage(0),
        'POST /api/master/employees': () =>
          json(
            {
              code: 'DUPLICATE_CODE',
              message: 'Karyawan dengan kode EMP-001 sudah ada.',
            },
            409,
          ),
      },
    });
    const user = userEvent.setup();
    renderApp('/master/employees');
    await user.click(await screen.findByRole('button', { name: /Tambah/ }));
    const dialog = await screen.findByRole('dialog', { name: 'Tambah Karyawan' });
    await user.click(within(dialog).getByRole('button', { name: 'Simpan' }));
    expect(within(dialog).getAllByText('Wajib diisi.')).toHaveLength(2);
    expect(calls.some((c) => c.key === 'POST /api/master/employees')).toBe(false);

    await user.type(within(dialog).getByLabelText(/NIP/), 'EMP-001');
    await user.type(within(dialog).getByLabelText(/Nama lengkap/), 'Agus');
    await user.type(within(dialog).getByLabelText(/Gaji pokok/), '9.500.000');
    await user.click(within(dialog).getByRole('button', { name: 'Simpan' }));
    expect(await within(dialog).findByRole('alert')).toHaveTextContent('sudah ada');
    const body = JSON.parse(
      String(calls.find((c) => c.key === 'POST /api/master/employees')!.init!.body),
    ) as Record<string, unknown>;
    expect(body).toMatchObject({
      code: 'EMP-001',
      full_name: 'Agus',
      basic_salary: '9500000',
      is_active: true,
    });
  });

  it('shows the import error report', async () => {
    mockApi({
      handlers: {
        'GET /api/master/employees/meta': () => json(META),
        'GET /api/master/employees': () => rowsPage(0),
        'POST /api/master/employees/import': () =>
          json({
            ok: false,
            created: 0,
            updated: 0,
            errors: [{ row: 3, field: 'full_name', message: 'wajib diisi' }],
          }),
      },
    });
    const user = userEvent.setup();
    renderApp('/master/employees');
    await user.click(await screen.findByRole('button', { name: /Impor CSV/ }));
    const dialog = await screen.findByRole('dialog');
    await user.upload(
      within(dialog).getByLabelText('File CSV'),
      new File(['code;full_name\n'], 'k.csv', { type: 'text/csv' }),
    );
    await user.click(within(dialog).getByRole('button', { name: /^Impor$/ }));
    const report = await within(dialog).findByRole('table');
    expect(within(report).getByText('Nama lengkap')).toBeInTheDocument();
    expect(within(report).getByText('wajib diisi')).toBeInTheDocument();
    expect(within(dialog).getByText(/Tidak ada data yang disimpan/)).toBeInTheDocument();
  });
});
