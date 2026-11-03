import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Card } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { Pagination } from '@/components/ui/pagination';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { formatDateTime, formatIDR } from '@/lib/format';
import { daysUntil, useTenders } from './api';
import { PackagePill, ResultPill } from './TenderPills';

export function ClosingIn({ iso }: { iso: string | null }) {
  const { t } = useTranslation();
  if (!iso) return <>–</>;
  const d = daysUntil(iso);
  return (
    <span className="flex flex-col">
      <span className="whitespace-nowrap">{formatDateTime(iso)}</span>
      <span
        className={d <= 7 && d >= 0 ? 'text-caption text-warning' : 'text-caption text-fg-muted'}
      >
        {d < 0 ? t('tender.closed') : t('tender.daysLeft', { count: d })}
      </span>
    </span>
  );
}

export function TendersPage() {
  const { t } = useTranslation();
  const [q, setQ] = useState('');
  const [openOnly, setOpenOnly] = useState(true);
  const [page, setPage] = useState(1);
  const list = useTenders({ q, open_only: openOnly, page });
  const data = list.data;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-2">
        <Field label={t('master.search')} className="min-w-0 flex-1">
          <Input
            type="search"
            value={q}
            placeholder={t('tender.search')}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
          />
        </Field>
        <label className="flex h-10 items-center gap-2 text-small text-fg-body">
          <input
            type="checkbox"
            checked={openOnly}
            onChange={(e) => {
              setOpenOnly(e.target.checked);
              setPage(1);
            }}
          />
          {t('tender.openOnly')}
        </label>
      </div>
      <p className="text-caption text-fg-muted">{t('tender.fromOppHint')}</p>
      <Card className="overflow-hidden">
        <Table>
          <THead>
            <TR>
              <TH>{t('crm.number')}</TH>
              <TH>{t('crm.oppTitle')}</TH>
              <TH>{t('tender.closing')}</TH>
              <TH className="text-right">{t('tender.price')}</TH>
              <TH>{t('tender.packageCol')}</TH>
              <TH>{t('tender.resultCol')}</TH>
            </TR>
          </THead>
          <TBody>
            {data?.items.length === 0 && (
              <TR>
                <TD colSpan={6} className="py-8 text-center text-fg-secondary">
                  {t('tender.empty')}
                </TD>
              </TR>
            )}
            {data?.items.map((r) => (
              <TR key={r.id}>
                <TD className="whitespace-nowrap">
                  <Link
                    to={`/tender/${r.id}`}
                    className="font-semibold text-fg underline-offset-2 hover:underline"
                  >
                    {r.tender_number ?? r.opportunity_number}
                  </Link>
                  {r.tender_number && (
                    <span className="block text-caption text-fg-muted">{r.opportunity_number}</span>
                  )}
                </TD>
                <TD className="min-w-56">
                  {r.opportunity_title}
                  <span className="block text-caption text-fg-muted">{r.company_name}</span>
                </TD>
                <TD>
                  <ClosingIn iso={r.closing_at} />
                </TD>
                <TD className="whitespace-nowrap text-right tabular-nums">
                  {r.price ? formatIDR(r.price) : '–'}
                </TD>
                <TD>
                  <PackagePill status={r.package_status} />
                </TD>
                <TD>{r.result ? <ResultPill result={r.result} /> : '–'}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
        <Pagination page={page} pageSize={25} total={data?.total ?? 0} onPage={setPage} />
      </Card>
    </div>
  );
}
