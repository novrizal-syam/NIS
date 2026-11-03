import { useState } from 'react';
import { useTranslation } from 'react-i18next';
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
import { LEAD_STATUSES, SOURCES, exportPath, useLeads, type LeadStatus } from './api';
import { FilterTile, LeadStatusPill } from './CrmPills';
import { LeadDialog } from './LeadDialog';

export function LeadsPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [q, setQ] = useState('');
  const [source, setSource] = useState('');
  const [status, setStatus] = useState<LeadStatus | ''>('');
  const [mine, setMine] = useState(false);
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<string | 'new' | null>(null);
  const filters = { q, source, status, mine };
  const leads = useLeads({ ...filters, page });
  const data = leads.data;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap gap-2">
        {LEAD_STATUSES.map((s) => (
          <FilterTile
            key={s}
            label={t(`crm.leadStatus.${s}`)}
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
            placeholder={t('crm.searchLeads')}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
          />
        </Field>
        <Field label={t('crm.source')} className="w-full sm:w-48">
          <Select
            value={source}
            onChange={(e) => {
              setSource(e.target.value);
              setPage(1);
            }}
          >
            <option value="">{t('master.all')}</option>
            {SOURCES.map((s) => (
              <option key={s} value={s}>
                {t(`crm.sources.${s}`)}
              </option>
            ))}
          </Select>
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
        {can('crm', 'export') && (
          <Button
            variant="secondary"
            onClick={() => void downloadFile(exportPath('leads', filters), 'lead.xlsx')}
          >
            <Icon name="download" /> {t('list.export')}
          </Button>
        )}
        {can('crm', 'create') && (
          <Button variant="primary" onClick={() => setOpen('new')}>
            <Icon name="add" /> {t('crm.newLead')}
          </Button>
        )}
      </div>

      <Card className="overflow-hidden">
        <Table>
          <THead>
            <TR>
              <TH>{t('crm.number')}</TH>
              <TH>{t('crm.company')}</TH>
              <TH>{t('crm.need')}</TH>
              <TH>{t('crm.source')}</TH>
              <TH className="text-right">{t('crm.estimatedValue')}</TH>
              <TH>{t('master.status')}</TH>
              <TH>{t('crm.owner')}</TH>
              <TH>{t('crm.created')}</TH>
            </TR>
          </THead>
          <TBody>
            {data?.items.length === 0 && (
              <TR>
                <TD colSpan={8} className="py-8 text-center text-fg-secondary">
                  {t('crm.noLeads')}
                </TD>
              </TR>
            )}
            {data?.items.map((l) => (
              <TR key={l.id}>
                <TD className="whitespace-nowrap">
                  <button
                    type="button"
                    onClick={() => setOpen(l.id)}
                    className="font-semibold text-fg underline-offset-2 hover:underline"
                  >
                    {l.number}
                  </button>
                </TD>
                <TD className="min-w-48">
                  {l.company_name}
                  {l.contact_name && (
                    <span className="block text-caption text-fg-muted">{l.contact_name}</span>
                  )}
                </TD>
                <TD className="min-w-56">{l.need}</TD>
                <TD>{t(`crm.sources.${l.source}`)}</TD>
                <TD className="whitespace-nowrap text-right tabular-nums">
                  {l.estimated_value ? formatIDR(l.estimated_value) : '–'}
                </TD>
                <TD>
                  <span className="flex flex-col items-start gap-1">
                    <LeadStatusPill status={l.status} />
                    {l.opportunity_number && (
                      <span className="text-caption text-fg-muted">{l.opportunity_number}</span>
                    )}
                  </span>
                </TD>
                <TD>{l.owner_name ?? '–'}</TD>
                <TD className="whitespace-nowrap">{formatDate(l.created_at)}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
        <Pagination page={page} pageSize={25} total={data?.total ?? 0} onPage={setPage} />
      </Card>

      {open && <LeadDialog id={open === 'new' ? null : open} onClose={() => setOpen(null)} />}
    </div>
  );
}
