import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { AppShell } from '@/components/layout/AppShell';
import { AuthProvider } from '@/features/auth/AuthProvider';
import { AuditPage } from '@/features/audit/AuditPage';
import { ChangePasswordPage } from '@/features/auth/ChangePasswordPage';
import { ForgotPasswordPage } from '@/features/auth/ForgotPasswordPage';
import { ResetPasswordPage } from '@/features/auth/ResetPasswordPage';
import { LoginPage } from '@/features/auth/LoginPage';
import { RequireAuth } from '@/features/auth/RequireAuth';
import { TotpSetupPage } from '@/features/auth/TotpSetupPage';
import { KomponenPage } from '@/features/dev/KomponenPage';
import { ComingSoonPage } from '@/features/home/ComingSoonPage';
import { LeadsPage } from '@/features/crm/LeadsPage';
import { OpportunitiesPage } from '@/features/crm/OpportunitiesPage';
import { OpportunityDetailPage } from '@/features/crm/OpportunityDetailPage';
import { ContractPage } from '@/features/contracts/ContractPage';
import { ContractsPage } from '@/features/contracts/ContractsPage';
import { DashboardPage } from '@/features/home/DashboardPage';
import {
  BillingPage,
  ClientSignPage,
  InvoicePage,
  TicketPage,
} from '@/features/billing/BillingPages';
import { DorFormPage, DorNewPage } from '@/features/dor/DorForm';
import { LedgerPage } from '@/features/finance/LedgerPage';
import { TreasuryPage } from '@/features/treasury/TreasuryPage';
import { AssetPage, MaintenancePage, WorkOrderPage } from '@/features/maintenance/MaintenancePages';
import { QhsePage } from '@/features/qhse/QhsePage';
import { DorListPage, DorPage } from '@/features/dor/DorPages';
import {
  VendorInvoiceNewPage,
  VendorInvoicePage,
  VendorInvoicesPage,
} from '@/features/finance/VendorInvoicePages';
import { GrListPage, GrNewPage, GrPage } from '@/features/inventory/GrPages';
import { MrListPage, MrNewPage, MrPage } from '@/features/inventory/MrPages';
import { CountPage, StockPage } from '@/features/inventory/StockPages';
import { PrListPage } from '@/features/procurement/PrListPage';
import { PoListPage, PoPage } from '@/features/procurement/PoPages';
import { PrNewPage, PrPage } from '@/features/procurement/PrPage';
import { RfqListPage, RfqPage } from '@/features/procurement/RfqPages';
import { TenderPage } from '@/features/tenders/TenderPage';
import { TendersPage } from '@/features/tenders/TendersPage';
import { ProjectPage } from '@/features/projects/ProjectPage';
import { ProjectsPage } from '@/features/projects/ProjectsPage';
import { QuotationPage } from '@/features/quotations/QuotationPage';
import { QuotationsPage } from '@/features/quotations/QuotationsPage';
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
        <Route path="/activate" element={<AcceptInvitePage />} />
        <Route path="/undangan/:token" element={<AcceptInvitePage />} />
        <Route path="/lupa-password" element={<ForgotPasswordPage />} />
        <Route path="/reset-password" element={<ResetPasswordPage />} />
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
          <Route path="lead" element={<LeadsPage />} />
          <Route path="peluang" element={<OpportunitiesPage />} />
          <Route path="peluang/:id" element={<OpportunityDetailPage />} />
          <Route path="penawaran" element={<QuotationsPage />} />
          <Route path="penawaran/:id" element={<QuotationPage />} />
          <Route path="tender" element={<TendersPage />} />
          <Route path="tender/:id" element={<TenderPage />} />
          <Route path="pengadaan/pr" element={<PrListPage />} />
          <Route path="pengadaan/pr/baru" element={<PrNewPage />} />
          <Route path="pengadaan/pr/:id" element={<PrPage />} />
          <Route path="pengadaan/rfq" element={<RfqListPage />} />
          <Route path="pengadaan/rfq/:id" element={<RfqPage />} />
          <Route path="pengadaan/po" element={<PoListPage />} />
          <Route path="pengadaan/po/:id" element={<PoPage />} />
          <Route path="gudang/gr" element={<GrListPage />} />
          <Route path="gudang/gr/baru" element={<GrNewPage />} />
          <Route path="gudang/gr/:id" element={<GrPage />} />
          <Route path="gudang/mr" element={<MrListPage />} />
          <Route path="gudang/mr/baru" element={<MrNewPage />} />
          <Route path="gudang/mr/:id" element={<MrPage />} />
          <Route path="gudang/stok" element={<StockPage />} />
          <Route path="gudang/opname/:id" element={<CountPage />} />
          <Route path="tagihan" element={<BillingPage />} />
          <Route path="tagihan/tiket/:id" element={<TicketPage />} />
          <Route path="tagihan/invoice/:id" element={<InvoicePage />} />
          <Route path="tanda-tangan/:token" element={<ClientSignPage />} />
          <Route path="pemeliharaan" element={<MaintenancePage />} />
          <Route path="pemeliharaan/aset/:code" element={<AssetPage />} />
          <Route path="pemeliharaan/wo/:id" element={<WorkOrderPage />} />
          <Route path="qhse" element={<QhsePage />} />
          <Route path="operasi/dor" element={<DorListPage />} />
          <Route path="operasi/dor/baru" element={<DorNewPage />} />
          <Route path="operasi/dor/isi/:clientId" element={<DorFormPage />} />
          <Route path="operasi/dor/:id" element={<DorPage />} />
          <Route path="keuangan/buku-besar" element={<LedgerPage />} />
          <Route path="keuangan/treasury" element={<TreasuryPage />} />
          <Route path="keuangan/tagihan-vendor" element={<VendorInvoicesPage />} />
          <Route path="keuangan/tagihan-vendor/baru" element={<VendorInvoiceNewPage />} />
          <Route path="keuangan/tagihan-vendor/:id" element={<VendorInvoicePage />} />
          <Route path="kontrak" element={<ContractsPage />} />
          <Route path="kontrak/:id" element={<ContractPage />} />
          <Route path="proyek" element={<ProjectsPage />} />
          <Route path="proyek/:id" element={<ProjectPage />} />
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
