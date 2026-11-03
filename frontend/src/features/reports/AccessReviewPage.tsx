import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Icon } from '@/components/ui/icon';
import { StatusPill } from '@/components/ui/status-pill';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { api, downloadFile } from '@/lib/api';
import { formatDateTime } from '@/lib/format';
import { cn } from '@/lib/utils';

interface Row {
  user_id: string;
  full_name: string;
  email: string;
  active: boolean;
  roles: string[];
  sensitive: string[];
  totp_enabled: boolean;
  requires_2fa: boolean;
  last_login_at: string | null;
  days_since_login: number | null;
  inactive_90: boolean;
  sod_exceptions: number;
}
interface Review {
  generated_at: string;
  inactive_days: number;
  summary: Record<
    'users' | 'inactive_90' | 'with_sensitive' | 'missing_2fa' | 'with_sod_exception',
    number
  >;
  rows: Row[];
}
type Filter = 'all' | 'inactive_90' | 'with_sensitive' | 'missing_2fa' | 'with_sod_exception';

const MATCH: Record<Filter, (r: Row) => boolean> = {
  all: () => true,
  inactive_90: (r) => r.inactive_90,
  with_sensitive: (r) => r.sensitive.length > 0,
  missing_2fa: (r) => r.requires_2fa && !r.totp_enabled,
  with_sod_exception: (r) => r.sod_exceptions > 0,
};

export function AccessReviewPage() {
  const { t } = useTranslation();
  const [filter, setFilter] = useState<Filter>('all');
  const review = useQuery({
    queryKey: ['reports', 'access-review'],
    queryFn: () => api<Review>('/reports/access-review'),
  });
  const data = review.data;
  const rows = (data?.rows ?? []).filter((r) => r.active && MATCH[filter](r));
  const tiles: { key: Filter; value: number | undefined; danger?: boolean }[] = [
    { key: 'all', value: data?.summary.users },
    { key: 'inactive_90', value: data?.summary.inactive_90, danger: true },
    { key: 'with_sensitive', value: data?.summary.with_sensitive },
    { key: 'missing_2fa', value: data?.summary.missing_2fa, danger: true },
    { key: 'with_sod_exception', value: data?.summary.with_sod_exception },
  ];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-body text-fg-secondary">
          {t('accessReview.intro', { days: data?.inactive_days ?? 90 })}
          {data && ` ${t('accessReview.generated', { at: formatDateTime(data.generated_at) })}`}
        </p>
        <div className="flex gap-2">
          <Button
            variant="secondary"
            onClick={() => void downloadFile('/reports/access-review.xlsx', 'tinjauan-akses.xlsx')}
          >
            <Icon name="download" /> Excel
          </Button>
          <Button
            variant="secondary"
            onClick={() => void downloadFile('/reports/access-review.pdf', 'tinjauan-akses.pdf')}
          >
            <Icon name="picture_as_pdf" /> PDF
          </Button>
        </div>
      </div>
      <div className="flex flex-wrap gap-2">
        {tiles.map((tile) => (
          <button
            key={tile.key}
            type="button"
            aria-pressed={filter === tile.key}
            onClick={() => setFilter(tile.key)}
            className={cn(
              'rounded-card border bg-surface-raised px-3 py-2 text-left',
              filter === tile.key ? 'border-border-strong' : 'border-border',
            )}
          >
            <span className="block text-caption uppercase text-fg-muted">
              {t(`accessReview.tiles.${tile.key}`)}
            </span>
            <span
              className={cn(
                'font-heading text-section-title tabular-nums',
                tile.danger && tile.value ? 'text-danger' : 'text-fg',
              )}
            >
              {tile.value ?? '–'}
            </span>
          </button>
        ))}
      </div>
      <Card>
        <Table>
          <caption className="sr-only">{t('accessReview.caption')}</caption>
          <THead>
            <TR>
              <TH>{t('users.user')}</TH>
              <TH>{t('users.roles')}</TH>
              <TH>{t('accessReview.sensitive')}</TH>
              <TH>2FA</TH>
              <TH>{t('users.lastLogin')}</TH>
              <TH numeric>{t('accessReview.days')}</TH>
              <TH>{t('accessReview.flags')}</TH>
            </TR>
          </THead>
          <TBody>
            {rows.length === 0 && (
              <TR>
                <TD colSpan={7} className="py-6 text-center text-fg-secondary">
                  {t('accessReview.empty')}
                </TD>
              </TR>
            )}
            {rows.map((r) => (
              <TR key={r.user_id}>
                <TD className="min-w-48">
                  <span className="font-semibold text-fg">{r.full_name}</span>
                  <span className="block text-caption text-fg-muted">{r.email}</span>
                </TD>
                <TD className="min-w-48">{r.roles.join(', ') || '–'}</TD>
                <TD>{r.sensitive.join(', ') || '–'}</TD>
                <TD>
                  {r.totp_enabled ? (
                    t('master.yes')
                  ) : r.requires_2fa ? (
                    <StatusPill tone="danger">{t('master.no')}</StatusPill>
                  ) : (
                    t('master.no')
                  )}
                </TD>
                <TD className="whitespace-nowrap">
                  {r.last_login_at ? formatDateTime(r.last_login_at) : '–'}
                </TD>
                <TD numeric>{r.days_since_login ?? '–'}</TD>
                <TD className="whitespace-nowrap">
                  {r.inactive_90 && (
                    <StatusPill tone="danger">
                      {t('accessReview.inactive', { days: data?.inactive_days ?? 90 })}
                    </StatusPill>
                  )}
                  {r.sod_exceptions > 0 && (
                    <StatusPill tone="warning" className="ml-1">
                      SoD
                    </StatusPill>
                  )}
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </Card>
    </div>
  );
}
