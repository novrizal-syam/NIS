import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState } from 'react';
import { BrowserRouter, Route, Routes } from 'react-router-dom';
import { AppShell } from '@/components/layout/AppShell';
import { LoginPage } from '@/features/auth/LoginPage';
import { KomponenPage } from '@/features/dev/KomponenPage';
import { ComingSoonPage } from '@/features/home/ComingSoonPage';
import { DashboardPage } from '@/features/home/DashboardPage';
import { NotFoundPage } from '@/features/home/NotFoundPage';
import { ThemeProvider } from '@/theme/ThemeProvider';

export function AppRoutes() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<AppShell />}>
        <Route index element={<DashboardPage />} />
        <Route path="segera/:key" element={<ComingSoonPage />} />
        {import.meta.env.DEV && <Route path="dev/komponen" element={<KomponenPage />} />}
        <Route path="*" element={<NotFoundPage />} />
      </Route>
    </Routes>
  );
}

export function App() {
  const [queryClient] = useState(
    () => new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 30_000 } } }),
  );
  return (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
          <AppRoutes />
        </BrowserRouter>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
