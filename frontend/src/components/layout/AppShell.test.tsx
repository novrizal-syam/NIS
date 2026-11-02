import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import { AppRoutes } from '@/app/App';
import { ThemeProvider } from '@/theme/ThemeProvider';

function renderAt(path: string) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <ThemeProvider>
      <QueryClientProvider client={qc}>
        <MemoryRouter
          initialEntries={[path]}
          future={{ v7_startTransition: true, v7_relativeSplatPath: true }}
        >
          <AppRoutes />
        </MemoryRouter>
      </QueryClientProvider>
    </ThemeProvider>,
  );
}

beforeEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.theme;
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify({ status: 'ok', db: 'ok', version: '0.1.0' }))),
  );
});

afterEach(() => vi.unstubAllGlobals());

describe('AppShell', () => {
  it('shows grouped menu with "Segera" on unbuilt items', () => {
    renderAt('/');
    const nav = screen.getAllByRole('navigation', { name: 'Menu utama' })[0]!;
    expect(within(nav).getByText('Procure to Pay')).toBeInTheDocument();
    expect(within(nav).getByText('SDM & Dokumen')).toBeInTheDocument();
    const lead = within(nav).getByRole('link', { name: /Lead\s*Segera/ });
    expect(lead).toHaveAttribute('href', '/segera/leads');
  });

  it('shows the page title in the top bar and API status', async () => {
    renderAt('/');
    expect(screen.getByRole('heading', { level: 1, name: 'Dasbor' })).toBeInTheDocument();
    expect(await screen.findByText('API dan database terhubung')).toBeInTheDocument();
  });

  it('renders the coming-soon page for unbuilt modules', () => {
    renderAt('/segera/purchaseOrders');
    expect(screen.getByRole('heading', { level: 1, name: 'Purchase Order' })).toBeInTheDocument();
    expect(screen.getByText(/belum tersedia/)).toBeInTheDocument();
  });

  it('switches theme from the user menu and remembers it', async () => {
    const user = userEvent.setup();
    renderAt('/');
    await user.click(screen.getByRole('button', { name: 'Menu pengguna' }));
    await user.click(screen.getByRole('button', { name: /Gelap/ }));
    expect(document.documentElement.dataset.theme).toBe('dark');
    expect(localStorage.getItem('nustrad.theme')).toBe('dark');
    await user.click(screen.getByRole('button', { name: /Sistem/ }));
    expect(document.documentElement.dataset.theme).toBeUndefined();
  });

  it('switches language to English', async () => {
    const user = userEvent.setup();
    renderAt('/');
    await user.click(screen.getByRole('button', { name: 'Menu pengguna' }));
    await user.click(screen.getByRole('button', { name: 'EN' }));
    expect(screen.getByRole('heading', { level: 1, name: 'Dashboard' })).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: 'ID' }));
  });
});

describe('LoginPage', () => {
  it('shows Indonesian validation errors', async () => {
    const user = userEvent.setup();
    renderAt('/login');
    expect(screen.getByText('PT Global Energi KITA', { exact: false })).toBeInTheDocument();
    await user.type(screen.getByLabelText(/Email/), 'bukan-email');
    await user.click(screen.getByRole('button', { name: 'Masuk' }));
    expect(await screen.findByText(/Format email tidak valid/)).toBeInTheDocument();
    expect(screen.getByText('Kata sandi wajib diisi.')).toBeInTheDocument();
  });
});
