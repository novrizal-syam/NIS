import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input, Select } from '@/components/ui/input';
import { Pagination } from '@/components/ui/pagination';
import { StatusPill } from '@/components/ui/status-pill';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { FormError } from '@/features/auth/AuthLayout';
import { ApiError, downloadFile } from '@/lib/api';
import { listQueryString, useMeta, useOptions, useRows, type FieldMeta, type Row } from './api';
import { display, isNumeric } from './format';
import { ImportDialog } from './ImportDialog';
import { RowForm } from './RowForm';

function FilterSelect({
  f,
  value,
  onChange,
}: {
  f: FieldMeta;
  value: string;
  onChange: (v: string) => void;
}) {
  const { t } = useTranslation();
  const opts = useOptions(f.kind === 'ref' ? f.ref : null);
  const options =
    f.kind === 'choice'
      ? f.choices
      : f.kind === 'bool'
        ? [
            { value: 'true', label: t('master.yes') },
            { value: 'false', label: t('master.no') },
          ]
        : (opts.data ?? []);
  return (
    <Field label={f.label} className="w-full sm:w-48">
      <Select value={value} onChange={(e) => onChange(e.target.value)}>
        <option value="">{t('master.all')}</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </Select>
    </Field>
  );
}

export function MasterListPage() {
  const { t } = useTranslation();
  const { entity = '' } = useParams();
  const meta = useMeta(entity);
  const [q, setQ] = useState('');
  const [active, setActive] = useState('true');
  const [filters, setFilters] = useState<Record<string, string>>({});
  const [page, setPage] = useState(1);
  const [editing, setEditing] = useState<Row | 'new' | null>(null);
  const [importing, setImporting] = useState(false);

  const params = { q, active: meta.data?.has_active ? active : undefined, page, ...filters };
  const rows = useRows(entity, params);
  const activeCount = useRows(entity, { active: 'true', page_size: 1 });
  const inactiveCount = useRows(entity, { active: 'false', page_size: 1 });

  if (meta.error) {
    return (
      <FormError
        message={meta.error instanceof ApiError ? meta.error.message : t('auth.unexpected')}
      />
    );
  }
  if (!meta.data) return <p className="text-fg-secondary">{t('common.loading')}</p>;
  const m = meta.data;
  const columns = m.fields.filter((f) => f.in_list);
  const filterFields = m.filters
    .map((name) => m.fields.find((f) => f.name === name))
    .filter((f): f is FieldMeta => Boolean(f && ['choice', 'bool', 'ref'].includes(f.kind)));

  return (
    <div className="flex flex-col gap-4">
      <Link
        to="/master"
        className="inline-flex items-center gap-1 text-small font-semibold text-fg-accent"
      >
        <Icon name="arrow_back" /> {t('master.back')}
      </Link>

      {m.has_active && (
        <div className="flex flex-wrap gap-2">
          {[
            { key: 'true', label: t('master.activeCount'), n: activeCount.data?.total },
            { key: 'false', label: t('master.inactiveCount'), n: inactiveCount.data?.total },
          ].map((c) => (
            <button
              key={c.key}
              type="button"
              aria-pressed={active === c.key}
              onClick={() => {
                setActive(c.key);
                setPage(1);
              }}
              className={`rounded-card border bg-surface-raised px-3 py-2 text-left ${active === c.key ? 'border-border-strong' : 'border-border'}`}
            >
              <span className="block text-caption uppercase text-fg-muted">{c.label}</span>
              <span className="font-heading text-section-title tabular-nums text-fg">
                {c.n ?? '–'}
              </span>
            </button>
          ))}
        </div>
      )}

      <div className="flex flex-wrap items-end gap-2">
        <Field label={t('master.search')} className="min-w-0 flex-1">
          <Input
            type="search"
            value={q}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
          />
        </Field>
        {filterFields.map((f) => (
          <FilterSelect
            key={f.name}
            f={f}
            value={filters[f.name] ?? ''}
            onChange={(v) => {
              setFilters((all) => ({ ...all, [f.name]: v }));
              setPage(1);
            }}
          />
        ))}
        {m.has_active && (
          <Field label={t('master.status')} className="w-full sm:w-40">
            <Select
              value={active}
              onChange={(e) => {
                setActive(e.target.value);
                setPage(1);
              }}
            >
              <option value="true">{t('master.active')}</option>
              <option value="false">{t('master.inactive')}</option>
              <option value="">{t('master.all')}</option>
            </Select>
          </Field>
        )}
        {m.can.export && (
          <Button
            variant="secondary"
            onClick={() =>
              void downloadFile(
                `/master/${entity}/export?${listQueryString({ q, active: m.has_active ? active : undefined, ...filters })}`,
                `${entity}.xlsx`,
              )
            }
          >
            <Icon name="download" /> {t('list.export')}
          </Button>
        )}
        {m.can.create && m.can.edit && (
          <Button variant="secondary" onClick={() => setImporting(true)}>
            <Icon name="upload" /> {t('master.import')}
          </Button>
        )}
        {m.can.create && (
          <Button variant="primary" onClick={() => setEditing('new')}>
            <Icon name="add" /> {t('master.add')}
          </Button>
        )}
      </div>

      <Card>
        <Table>
          <caption className="sr-only">{m.label}</caption>
          <THead>
            <TR>
              {columns.map((f) => (
                <TH key={f.name} numeric={isNumeric(f)}>
                  {f.label}
                </TH>
              ))}
              {m.has_active && <TH>{t('master.status')}</TH>}
            </TR>
          </THead>
          <TBody>
            {rows.data?.items.length === 0 && (
              <TR>
                <TD colSpan={columns.length + 1} className="py-8 text-center text-fg-secondary">
                  {t('master.empty')}
                </TD>
              </TR>
            )}
            {rows.data?.items.map((r) => (
              <TR key={r.id}>
                {columns.map((f, i) => (
                  <TD
                    key={f.name}
                    numeric={isNumeric(f)}
                    className={i === 0 ? 'whitespace-nowrap' : undefined}
                  >
                    {i === 0 ? (
                      <button
                        type="button"
                        onClick={() => setEditing(r)}
                        className="font-semibold text-fg underline-offset-2 hover:underline"
                      >
                        {display(f, r[f.name], t)}
                      </button>
                    ) : (
                      display(f, r[f.name], t)
                    )}
                  </TD>
                ))}
                {m.has_active && (
                  <TD>
                    <StatusPill tone={r.is_active ? 'success' : 'neutral'}>
                      {r.is_active ? t('master.active') : t('master.inactive')}
                    </StatusPill>
                    {r.is_demo && (
                      <span className="ml-2 text-caption text-fg-muted">{t('master.demo')}</span>
                    )}
                  </TD>
                )}
              </TR>
            ))}
          </TBody>
        </Table>
        <Pagination page={page} pageSize={25} total={rows.data?.total ?? 0} onPage={setPage} />
      </Card>

      {editing && (
        <RowForm
          meta={m}
          row={editing === 'new' ? null : editing}
          onClose={() => setEditing(null)}
        />
      )}
      {importing && <ImportDialog meta={m} onClose={() => setImporting(false)} />}
    </div>
  );
}
