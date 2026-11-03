import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { StatusPill } from '@/components/ui/status-pill';
import { useAuth } from '@/features/auth/AuthProvider';
import { SalesTiles } from '@/features/crm/SalesTiles';
import { ClosingSoonCard } from '@/features/tenders/ClosingSoonCard';
import { getHealth } from '@/lib/api';
import { formatDate } from '@/lib/format';

export function DashboardPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const health = useQuery({ queryKey: ['health'], queryFn: getHealth, refetchInterval: 30_000 });

  let pill = <StatusPill tone="info">{t('dashboard.apiChecking')}</StatusPill>;
  if (health.isError) pill = <StatusPill tone="danger">{t('dashboard.apiError')}</StatusPill>;
  else if (health.data?.db === 'ok')
    pill = <StatusPill tone="success">{t('dashboard.apiOk')}</StatusPill>;
  else if (health.data) pill = <StatusPill tone="warning">{t('dashboard.apiDegraded')}</StatusPill>;

  return (
    <div className="flex flex-col gap-4">
      <p className="eyebrow">
        {t('app.tenant')} · {formatDate(new Date())}
      </p>
      <p className="text-body text-fg-secondary">{t('dashboard.welcome')}</p>
      {can('crm', 'view') && <SalesTiles />}
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {can('tender', 'view') && <ClosingSoonCard />}
        <Card>
          <CardHeader>
            <CardTitle>{t('dashboard.systemStatus')}</CardTitle>
            {health.data && (
              <CardDescription>
                {t('dashboard.version', { version: health.data.version })}
              </CardDescription>
            )}
          </CardHeader>
          <CardContent>{pill}</CardContent>
        </Card>
      </div>
    </div>
  );
}
