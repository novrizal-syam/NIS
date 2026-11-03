import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
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
import {
  QUOTATION_STATUSES,
  quotationExportPath,
  useQuotations,
  type QuotationStatus,
} from './api';
import { MarginPill, QuotationStatusPill } from './QuotationPills';

export function QuotationsPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [q, setQ] = useState('');
  const [status, setStatus] = useState<QuotationStatus | ''>('');
  const [page, setPage] = useState(1);
  const list = useQuotations({ q, status, page });
  const data = list.data;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap gap-2">
        {QUOTATION_STATUSES.map((s) => (
          <FilterTile
            key={s}
            label={t(`quotation.status.${s}`)}
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
            placeholder={t('quotation.search')}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
          />
        </Field>
        {can('quotation', 'export') && (
          <Button
            variant="secondary"
            onClick={() => void downloadFile(quotationExportPath({ q, status }), 'penawaran.xlsx')}
          >
            <Icon name="download" /> {t('list.export')}
          </Button>
        )}
      </div>
      <p className="text-caption text-fg-muted">{t('quotation.fromOppHint')}</p>
      <Card className="overflow-hidden">
        <Table>
          <THead>
            <TR>
              <TH>{t('crm.number')}</TH>
              <TH>{t('crm.oppTitle')}</TH>
              <TH>{t('master.status')}</TH>
              <TH className="text-right">{t('quotation.total')}</TH>
              <TH className="text-right">{t('quotation.margin')}</TH>
              <TH>{t('quotation.validUntil')}</TH>
              <TH>{t('crm.owner')}</TH>
            </TR>
          </THead>
          <TBody>
            {data?.items.length === 0 && (
              <TR>
                <TD colSpan={7} className="py-8 text-center text-fg-secondary">
                  {t('quotation.empty')}
                </TD>
              </TR>
            )}
            {data?.items.map((r) => (
              <TR key={r.id}>
                <TD className="whitespace-nowrap">
                  <Link
                    to={`/penawaran/${r.id}`}
                    className="font-semibold text-fg underline-offset-2 hover:underline"
                  >
                    {r.label}
                  </Link>
                </TD>
                <TD className="min-w-56">
                  {r.opportunity_title}
                  <span className="block text-caption text-fg-muted">
                    {r.opportunity_number} · {r.company_name}
                  </span>
                </TD>
                <TD>
                  <QuotationStatusPill status={r.status} />
                </TD>
                <TD className="whitespace-nowrap text-right tabular-nums">
                  {formatIDR(r.total_price)}
                </TD>
                <TD className="text-right">
                  <MarginPill pct={r.margin_pct} warning={r.margin_warning} />
                </TD>
                <TD className="whitespace-nowrap">
                  {r.valid_until ? formatDate(r.valid_until) : '–'}
                </TD>
                <TD>{r.owner_name ?? '–'}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
        <Pagination page={page} pageSize={25} total={data?.total ?? 0} onPage={setPage} />
      </Card>
    </div>
  );
}
