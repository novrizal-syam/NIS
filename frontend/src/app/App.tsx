import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { AppShell } from '@/components/layout/AppShell';
import { AuthProvider } from '@/features/auth/AuthProvider';
import { AuditPage } from '@/features/audit/AuditPage';
import { ChangePasswordPage } from '@/features/auth/ChangePasswordPage';
import { LoginPage } from '@/features/auth/LoginPage';
import { RequireAuth } from '@/features/auth/RequireAuth';
import { TotpSetupPage } from '@/features/auth/TotpSetupPage';
import { KomponenPage } from '@/features/dev/KomponenPage';
import { ComingSoonPage } from '@/features/home/ComingSoonPage';
import { DashboardPage } from '@/features/home/DashboardPage';
import { NotFoundPage } from '@/features/home/NotFoundPage';
import { MasterIndexPage } from '@/features/master/MasterIndexPage';
import { MasterListPage } from '@/features/master/MasterListPage';
import { DoaRulesPage } from '@/features/workflow/DoaRulesPage';
import { InboxPage } from '@/features/workflow/InboxPage';
import { RequestDetailPage } from '@/features/workflow/RequestDetailPage';
import { PrivacyPage } from '@/features/onboarding/PrivacyPage';
import { ProfilePage } from '@/features/onboarding/ProfilePage';
import { RoleDetailPage } from '@/features/roles/RoleDetailPage';
import { RolesPage } from '@/features/roles/RolesPage';
import { AccessReviewPage } from '@/features/reports/AccessReviewPage';
import { SettingsPage } from '@/features/settings/SettingsPage';
import { SodPage } from '@/features/sod/SodPage';
import { AcceptInvitePage } from '@/features/users/AcceptInvitePage';
import { UsersPage } from '@/features/users/UsersPage';
import { SetupGate } from '@/features/setup/SetupGate';
import { SetupPage } from '@/features/setup/SetupPage';
import { ThemeProvider } from '@/theme/ThemeProvider';
import { ROUTER_FUTURE } from './routerConfig';

export function AppRoutes() {
  return (
    <SetupGate>
      <Routes>
        <Route path="/setup" element={<SetupPage />} />
        <Route path="/login" element={<LoginPage />} />
        <Route path="/undangan/:token" element={<AcceptInvitePage />} />
        <Route
          path="/akun/ganti-password"
          element={
            <RequireAuth allowPending>
              <ChangePasswordPage />
            </RequireAuth>
          }
        />
        <Route
          path="/akun/privasi"
          element={
            <RequireAuth allowPending>
              <PrivacyPage />
            </RequireAuth>
          }
        />
        <Route
          path="/akun/profil"
          element={
            <RequireAuth allowPending>
              <ProfilePage />
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
          <Route path="pengaturan" element={<SettingsPage />} />
          <Route path="pengguna" element={<UsersPage />} />
          <Route path="pengaturan/peran" element={<RolesPage />} />
          <Route path="pengaturan/sod" element={<SodPage />} />
          <Route path="pengaturan/tinjauan-akses" element={<AccessReviewPage />} />
          <Route path="pengaturan/peran/:id" element={<RoleDetailPage />} />
          <Route path="pengaturan/doa" element={<DoaRulesPage />} />
          <Route path="master" element={<MasterIndexPage />} />
          <Route path="master/:entity" element={<MasterListPage />} />
          <Route path="audit" element={<AuditPage />} />
          <Route path="segera/:key" element={<ComingSoonPage />} />
          {import.meta.env.DEV && <Route path="dev/komponen" element={<KomponenPage />} />}
          <Route path="*" element={<NotFoundPage />} />
        </Route>
      </Routes>
    </SetupGate>
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
