import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { StatusPill } from '@/components/ui/status-pill';
import { formatIDR } from '@/lib/format';
import { useSalesDashboard } from './api';

const pct = (s: string) => `${s.replace('.', ',')}%`;

/** Sales tiles for the dashboard (crm view permission; figures follow the user's data scope). */
export function SalesTiles() {
  const { t } = useTranslation();
  const q = useSalesDashboard(true);
  const d = q.data;
  if (!d) return null;
  const progress = Math.min(
    100,
    Number(d.contract_target) > 0
      ? (Number(d.new_contract_value) / Number(d.contract_target)) * 100
      : 0,
  );
  const onTarget = d.win_rate !== null && Number(d.win_rate) >= Number(d.win_rate_target);

  return (
    <section aria-labelledby="sales-heading" className="flex flex-col gap-2">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="sales-heading" className="font-heading text-section-title text-fg">
          {t('crm.dash.title', { year: d.year })}
        </h2>
        <span className="text-caption text-fg-muted">
          {d.scope === 'own' ? t('crm.dash.scopeOwn') : t('crm.dash.scopeAll')}
        </span>
      </div>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Card>
          <CardHeader>
            <CardDescription>{t('crm.dash.open')}</CardDescription>
            <CardTitle className="text-section-title tabular-nums">{formatIDR(d.open_pipeline)}</CardTitle>
          </CardHeader>
          <CardContent className="text-small text-fg-secondary">
            <Link to="/peluang" className="underline">
              {t('crm.dash.openCount', { count: d.open_count })}
            </Link>
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>{t('crm.dash.weighted')}</CardDescription>
            <CardTitle className="text-section-title tabular-nums">{formatIDR(d.weighted_pipeline)}</CardTitle>
          </CardHeader>
          <CardContent className="text-small text-fg-secondary">
            {t('crm.dash.weightedHelp')}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>{t('crm.dash.winRate')}</CardDescription>
            <CardTitle className="text-section-title tabular-nums">{d.win_rate ? pct(d.win_rate) : '–'}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-wrap items-center gap-2 text-small text-fg-secondary">
            {d.win_rate !== null && (
              <StatusPill tone={onTarget ? 'success' : 'warning'}>
                {t('crm.dash.target', { value: pct(d.win_rate_target) })}
              </StatusPill>
            )}
            {t('crm.dash.decided', { won: d.won_count, lost: d.lost_count })}
          </CardContent>
        </Card>
        <Card>
          <CardHeader>
            <CardDescription>{t('crm.dash.newContracts')}</CardDescription>
            <CardTitle className="text-section-title tabular-nums">{formatIDR(d.new_contract_value)}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-1 text-small text-fg-secondary">
            <div
              role="progressbar"
              aria-label={t('crm.dash.newContracts')}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(progress)}
              className="h-2 overflow-hidden rounded-pill bg-surface-muted"
            >
              <div className="h-full bg-brand-gold" style={{ width: `${progress}%` }} />
            </div>
            {t('crm.dash.ofTarget', { target: formatIDR(d.contract_target) })}
          </CardContent>
        </Card>
      </div>
    </section>
  );
}
