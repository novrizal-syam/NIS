import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input, Select } from '@/components/ui/input';
import { Pagination } from '@/components/ui/pagination';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { useAuth } from '@/features/auth/AuthProvider';
import { downloadFile } from '@/lib/api';
import { formatDate, formatIDR } from '@/lib/format';
import { contractExportPath, useContracts } from './api';
import { ContractStatusPill, UsageBar } from './ContractBits';

export function ContractsPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [q, setQ] = useState('');
  const [status, setStatus] = useState('');
  const [page, setPage] = useState(1);
  const list = useContracts({ q, status, page });
  const data = list.data;

  return (
    <div className="flex flex-col gap-4">
      <p className="text-body text-fg-secondary">
        {t('contract.summary', { count: data?.total ?? 0 })}{' '}
        <span className="font-semibold tabular-nums text-fg">
          {data ? formatIDR(data.total_value) : '–'}
        </span>
      </p>
      <div className="flex flex-wrap items-end gap-2">
        <Field label={t('master.search')} className="min-w-0 flex-1">
          <Input
            type="search"
            value={q}
            placeholder={t('contract.search')}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
          />
        </Field>
        <Field label={t('master.status')} className="w-full sm:w-48">
          <Select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value);
              setPage(1);
            }}
          >
            <option value="">{t('master.all')}</option>
            {(['active', 'completed', 'terminated'] as const).map((s) => (
              <option key={s} value={s}>
                {t(`contract.status.${s}`)}
              </option>
            ))}
          </Select>
        </Field>
        {can('contract', 'export') && (
          <Button
            variant="secondary"
            onClick={() => void downloadFile(contractExportPath({ q, status }), 'kontrak.xlsx')}
          >
            <Icon name="download" /> {t('list.export')}
          </Button>
        )}
      </div>
      <p className="text-caption text-fg-muted">{t('contract.fromWonHint')}</p>
      <Card className="overflow-hidden">
        <Table>
          <THead>
            <TR>
              <TH>{t('crm.number')}</TH>
              <TH>{t('contract.titleCol')}</TH>
              <TH>{t('contract.po')}</TH>
              <TH className="text-right">{t('contract.value')}</TH>
              <TH>{t('contract.usage')}</TH>
              <TH>{t('contract.period')}</TH>
              <TH>{t('master.status')}</TH>
            </TR>
          </THead>
          <TBody>
            {data?.items.length === 0 && (
              <TR>
                <TD colSpan={7} className="py-8 text-center text-fg-secondary">
                  {t('contract.empty')}
                </TD>
              </TR>
            )}
            {data?.items.map((c) => (
              <TR key={c.id}>
                <TD className="whitespace-nowrap">
                  <Link
                    to={`/kontrak/${c.id}`}
                    className="font-semibold text-fg underline-offset-2 hover:underline"
                  >
                    {c.number}
                  </Link>
                </TD>
                <TD className="min-w-56">
                  {c.title}
                  <span className="block text-caption text-fg-muted">{c.company_name}</span>
                </TD>
                <TD>{c.po_number ?? '–'}</TD>
                <TD className="whitespace-nowrap text-right tabular-nums">{formatIDR(c.value)}</TD>
                <TD className="min-w-32">
                  <UsageBar pct={c.usage_pct} />
                </TD>
                <TD className="whitespace-nowrap">
                  {c.start_date ? formatDate(c.start_date) : '–'} –{' '}
                  {c.end_date ? formatDate(c.end_date) : '–'}
                </TD>
                <TD>
                  <ContractStatusPill status={c.status} />
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
        <Pagination page={page} pageSize={25} total={data?.total ?? 0} onPage={setPage} />
      </Card>
    </div>
  );
}
