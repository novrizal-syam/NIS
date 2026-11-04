import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input } from '@/components/ui/input';
import { Pagination } from '@/components/ui/pagination';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { useAuth } from '@/features/auth/AuthProvider';
import { FilterTile } from '@/features/crm/CrmPills';
import { downloadFile } from '@/lib/api';
import { formatDate, formatIDR } from '@/lib/format';
import { PR_STATUSES, prExportPath, usePrs, type PrStatus } from './api';
import { PrStatusPill } from './PrStatusPill';

export function PrListPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [q, setQ] = useState('');
  const [status, setStatus] = useState<PrStatus | ''>('');
  const [mine, setMine] = useState(false);
  const [page, setPage] = useState(1);
  const list = usePrs({ q, status, mine, page });
  const data = list.data;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap gap-2">
        {PR_STATUSES.map((s) => (
          <FilterTile
            key={s}
            label={t(`pr.status.${s}`)}
            value={data?.counts[s] ?? '–'}
            active={status === s}
            onClick={() => {
              setStatus(status === s ? '' : s);
              setPage(1);
            }}
          />
        ))}
      </div>
      <div className="flex flex-wrap items-end gap-2">
        <Field label={t('master.search')} className="min-w-0 flex-1">
          <Input
            type="search"
            value={q}
            placeholder={t('pr.search')}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
          />
        </Field>
        <label className="flex h-10 items-center gap-2 text-small text-fg-body">
          <input
            type="checkbox"
            checked={mine}
            onChange={(e) => {
              setMine(e.target.checked);
              setPage(1);
            }}
          />
          {t('crm.mineOnly')}
        </label>
        {can('procurement', 'export') && (
          <Button
            variant="secondary"
            onClick={() => void downloadFile(prExportPath({ q, status }), 'pr.xlsx')}
          >
            <Icon name="download" /> {t('list.export')}
          </Button>
        )}
        {can('procurement', 'create') && (
          <Link to="/pengadaan/pr/baru" className={buttonVariants({ variant: 'primary' })}>
            <Icon name="add" /> {t('pr.new')}
          </Link>
        )}
      </div>
      <Card className="overflow-hidden">
        <Table>
          <THead>
            <TR>
              <TH>{t('crm.number')}</TH>
              <TH>{t('pr.project')}</TH>
              <TH>{t('bcr.line')}</TH>
              <TH className="text-right">{t('pr.total')}</TH>
              <TH>{t('master.status')}</TH>
              <TH>{t('pr.needDate')}</TH>
              <TH>{t('pr.requester')}</TH>
            </TR>
          </THead>
          <TBody>
            {data?.items.length === 0 && (
              <TR>
                <TD colSpan={7} className="py-8 text-center text-fg-secondary">
                  {t('pr.empty')}
                </TD>
              </TR>
            )}
            {data?.items.map((r) => (
              <TR key={r.id}>
                <TD className="whitespace-nowrap">
                  <Link
                    to={`/pengadaan/pr/${r.id}`}
                    className="font-semibold text-fg underline-offset-2 hover:underline"
                  >
                    {r.number}
                  </Link>
                </TD>
                <TD className="min-w-48">
                  {r.project_number}
                  <span className="block text-caption text-fg-muted">{r.project_name}</span>
                </TD>
                <TD>
                  {r.wbs_code}/{r.cost_element_code}
                </TD>
                <TD className="whitespace-nowrap text-right tabular-nums">{formatIDR(r.total)}</TD>
                <TD>
                  <span className="flex flex-col items-start gap-1">
                    <PrStatusPill status={r.status} />
                    {r.status === 'blocked' && r.shortfall && (
                      <span className="text-caption text-danger">
                        {t('pr.short', { amount: formatIDR(r.shortfall) })}
                      </span>
                    )}
                  </span>
                </TD>
                <TD className="whitespace-nowrap">{formatDate(r.need_date)}</TD>
                <TD>{r.requester_name ?? '–'}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
        <Pagination page={page} pageSize={25} total={data?.total ?? 0} onPage={setPage} />
      </Card>
    </div>
  );
}
