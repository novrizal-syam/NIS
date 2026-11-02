import { Fragment, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input, Select } from '@/components/ui/input';
import { Pagination } from '@/components/ui/pagination';
import { StatusPill } from '@/components/ui/status-pill';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { useAuth } from '@/features/auth/AuthProvider';
import { downloadFile } from '@/lib/api';
import { formatDateTime } from '@/lib/format';
import { useAudit, useAuditFacets } from './api';
import { Changes } from './Changes';

export function AuditPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const facets = useAuditFacets();
  const [filters, setFilters] = useState({
    entity_type: '',
    action: '',
    date_from: '',
    date_to: '',
    q: '',
  });
  const [page, setPage] = useState(1);
  const [open, setOpen] = useState<string | null>(null);
  const audit = useAudit({ ...filters, page });
  const set = (k: keyof typeof filters, v: string) => {
    setFilters((f) => ({ ...f, [k]: v }));
    setPage(1);
  };
  const qs = new URLSearchParams(Object.entries(filters).filter(([, v]) => v !== '')).toString();

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-2">
        <Field label={t('audit.search')} className="min-w-0 flex-1">
          <Input
            type="search"
            value={filters.q}
            placeholder={t('audit.searchPlaceholder')}
            onChange={(e) => set('q', e.target.value)}
          />
        </Field>
        <Field label={t('audit.entityType')} className="w-full sm:w-48">
          <Select value={filters.entity_type} onChange={(e) => set('entity_type', e.target.value)}>
            <option value="">{t('master.all')}</option>
            {facets.data?.entity_types.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t('audit.action')} className="w-full sm:w-44">
          <Select value={filters.action} onChange={(e) => set('action', e.target.value)}>
            <option value="">{t('master.all')}</option>
            {facets.data?.actions.map((o) => (
              <option key={o.value} value={o.value}>
                {o.label}
              </option>
            ))}
          </Select>
        </Field>
        <Field label={t('audit.from')} className="w-full sm:w-40">
          <Input
            type="date"
            value={filters.date_from}
            onChange={(e) => set('date_from', e.target.value)}
          />
        </Field>
        <Field label={t('audit.to')} className="w-full sm:w-40">
          <Input
            type="date"
            value={filters.date_to}
            onChange={(e) => set('date_to', e.target.value)}
          />
        </Field>
        {can('audit', 'export') && (
          <Button
            variant="secondary"
            onClick={() => void downloadFile(`/audit/export?${qs}`, 'jejak-audit.xlsx')}
          >
            <Icon name="download" /> {t('list.export')}
          </Button>
        )}
      </div>

      <Card>
        <Table>
          <caption className="sr-only">{t('audit.caption')}</caption>
          <THead>
            <TR>
              <TH>{t('audit.time')}</TH>
              <TH>{t('audit.user')}</TH>
              <TH>{t('audit.action')}</TH>
              <TH>{t('audit.entityType')}</TH>
              <TH>{t('audit.changed')}</TH>
              <TH />
            </TR>
          </THead>
          <TBody>
            {audit.data?.items.length === 0 && (
              <TR>
                <TD colSpan={6} className="py-8 text-center text-fg-secondary">
                  {t('audit.empty')}
                </TD>
              </TR>
            )}
            {audit.data?.items.map((e) => (
              <Fragment key={e.id}>
                <TR>
                  <TD className="whitespace-nowrap">{formatDateTime(e.at)}</TD>
                  <TD className="whitespace-nowrap">{e.actor_name}</TD>
                  <TD>
                    <StatusPill
                      tone={
                        ['delete', 'reject', 'login_failed', 'refresh_reuse'].includes(e.action)
                          ? 'danger'
                          : 'neutral'
                      }
                    >
                      {e.action_label}
                    </StatusPill>
                  </TD>
                  <TD className="whitespace-nowrap">
                    {e.entity_type}
                    <span className="block max-w-48 truncate text-caption text-fg-muted">
                      {e.entity_id}
                    </span>
                  </TD>
                  <TD className="min-w-48">{(e.changed ?? []).join(', ') || '–'}</TD>
                  <TD className="text-right">
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-expanded={open === e.id}
                      aria-label={t('audit.details')}
                      onClick={() => setOpen(open === e.id ? null : e.id)}
                    >
                      <Icon name={open === e.id ? 'expand_less' : 'expand_more'} />
                    </Button>
                  </TD>
                </TR>
                {open === e.id && (
                  <TR>
                    <TD colSpan={6} className="bg-surface-muted">
                      <Changes entry={e} />
                      {e.note && <p className="mt-1 text-small text-fg-secondary">{e.note}</p>}
                      {e.request_id && (
                        <p className="mt-1 text-caption text-fg-muted">request_id {e.request_id}</p>
                      )}
                    </TD>
                  </TR>
                )}
              </Fragment>
            ))}
          </TBody>
        </Table>
        <Pagination page={page} pageSize={25} total={audit.data?.total ?? 0} onPage={setPage} />
      </Card>
    </div>
  );
}
