import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { AppShell } from '@/components/layout/AppShell';
import { AuthProvider } from '@/features/auth/AuthProvider';
import { ChangePasswordPage } from '@/features/auth/ChangePasswordPage';
import { LoginPage } from '@/features/auth/LoginPage';
import { RequireAuth } from '@/features/auth/RequireAuth';
import { TotpSetupPage } from '@/features/auth/TotpSetupPage';
import { KomponenPage } from '@/features/dev/KomponenPage';
import { ComingSoonPage } from '@/features/home/ComingSoonPage';
import { DashboardPage } from '@/features/home/DashboardPage';
import { NotFoundPage } from '@/features/home/NotFoundPage';
import { DoaRulesPage } from '@/features/workflow/DoaRulesPage';
import { InboxPage } from '@/features/workflow/InboxPage';
import { RequestDetailPage } from '@/features/workflow/RequestDetailPage';
import { ThemeProvider } from '@/theme/ThemeProvider';
import { ROUTER_FUTURE } from './routerConfig';

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route
        path="/akun/ganti-password"
        element={
          <RequireAuth allowPending>
            <ChangePasswordPage />
          </RequireAuth>
        }
      />
      <Route
        path="/akun/2fa"
        element={
          <RequireAuth allowPending>
            <TotpSetupPage />
          </RequireAuth>
        }
      />
      <Route
        element={
          <RequireAuth>
            <AppShell />
          </RequireAuth>
        }
      >
        <Route index element={<DashboardPage />} />
        <Route path="persetujuan" element={<InboxPage />} />
        <Route path="persetujuan/:id" element={<RequestDetailPage />} />
        <Route path="pengaturan/doa" element={<DoaRulesPage />} />
        <Route path="segera/:key" element={<ComingSoonPage />} />
        {import.meta.env.DEV && <Route path="dev/komponen" element={<KomponenPage />} />}
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}

/** Providers shared by the app and tests (router supplied by the caller). */
export function AppProviders({ children, client }: { children: ReactNode; client: QueryClient }) {
  return (
    <ThemeProvider>
      <QueryClientProvider client={client}>
        <AuthProvider>{children}</AuthProvider>
      </QueryClientProvider>
    </ThemeProvider>
  );
}

export function App() {
  const [queryClient] = useState(
    () => new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 30_000 } } }),
  );
  return (
    <AppProviders client={queryClient}>
      <BrowserRouter future={ROUTER_FUTURE}>
        <AppRoutes />
      </BrowserRouter>
    </AppProviders>
  );
}
