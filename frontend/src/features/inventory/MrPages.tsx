import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Button, buttonVariants } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input, Select, Textarea } from '@/components/ui/input';
import { Pagination } from '@/components/ui/pagination';
import { StatusPill, type StatusTone } from '@/components/ui/status-pill';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { FormError } from '@/features/auth/AuthLayout';
import { useAuth } from '@/features/auth/AuthProvider';
import { ApiError } from '@/lib/api';
import { formatDate, formatIDR } from '@/lib/format';
import { useCreateMr, useMr, useMrFormOptions, useMrs, type MrStatus } from './api';
import { JournalCard } from './JournalCard';

const errText = (e: unknown, fallback: string) =>
  e instanceof ApiError ? e.message : e ? fallback : null;
const qtyToApi = (v: string) => v.replace(/\./g, '').replace(',', '.').trim();
const qtyFmt = (v: string) => v.replace('.', ',');
const TONE: Record<MrStatus, StatusTone> = {
  issued: 'success',
  partial: 'warning',
  pr_created: 'info',
};

export function MrStatusPill({ status }: { status: MrStatus }) {
  const { t } = useTranslation();
  return <StatusPill tone={TONE[status]}>{t(`mr.status.${status}`)}</StatusPill>;
}

export function MrListPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const [q, setQ] = useState('');
  const [page, setPage] = useState(1);
  const list = useMrs({ q, page });
  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-end gap-2">
        <Field label={t('master.search')} className="min-w-0 flex-1">
          <Input
            type="search"
            value={q}
            placeholder={t('mr.search')}
            onChange={(e) => {
              setQ(e.target.value);
              setPage(1);
            }}
          />
        </Field>
        {can('inventory', 'create') && (
          <Link to="/gudang/mr/baru" className={buttonVariants({ variant: 'primary' })}>
            <Icon name="add" /> {t('mr.new')}
          </Link>
        )}
      </div>
      <Card className="overflow-hidden">
        <Table>
          <THead>
            <TR>
              <TH>{t('crm.number')}</TH>
              <TH>{t('pr.project')}</TH>
              <TH>{t('mr.site')}</TH>
              <TH>{t('pr.needDate')}</TH>
              <TH className="text-right">{t('mr.issuedValue')}</TH>
              <TH>{t('master.status')}</TH>
            </TR>
          </THead>
          <TBody>
            {list.data?.items.length === 0 && (
              <TR>
                <TD colSpan={6} className="py-8 text-center text-fg-secondary">
                  {t('mr.empty')}
                </TD>
              </TR>
            )}
            {list.data?.items.map((r) => (
              <TR key={r.id}>
                <TD className="whitespace-nowrap">
                  <Link
                    to={`/gudang/mr/${r.id}`}
                    className="font-semibold text-fg underline-offset-2 hover:underline"
                  >
                    {r.number}
                  </Link>
                </TD>
                <TD>{r.project_number}</TD>
                <TD>{r.site_warehouse}</TD>
                <TD className="whitespace-nowrap">{formatDate(r.need_date)}</TD>
                <TD className="whitespace-nowrap text-right tabular-nums">
                  {formatIDR(r.issued_value)}
                </TD>
                <TD>
                  <MrStatusPill status={r.status} />
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
        <Pagination page={page} pageSize={25} total={list.data?.total ?? 0} onPage={setPage} />
      </Card>
    </div>
  );
}

interface LineDraft {
  item: string;
  qty: string;
}

export function MrNewPage() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const options = useMrFormOptions();
  const create = useCreateMr();
  const [v, setV] = useState({
    project: '',
    wbs: '',
    element: 'CONSUMABLE',
    site: '',
    need: '',
    purpose: '',
  });
  const [lines, setLines] = useState<LineDraft[]>([{ item: '', qty: '1' }]);
  const o = options.data;
  const project = o?.projects.find((p) => p.id === v.project);
  const setLine = (i: number, patch: Partial<LineDraft>) =>
    setLines(lines.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  const ready =
    v.project &&
    v.wbs &&
    v.site &&
    v.need &&
    lines.length > 0 &&
    lines.every((l) => l.item && Number(qtyToApi(l.qty)) > 0) &&
    new Set(lines.map((l) => l.item)).size === lines.length;

  if (options.isLoading) return <p className="text-fg-secondary">{t('common.loading')}</p>;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('mr.new')}</CardTitle>
        <CardDescription>{t('mr.howTo')}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {o && o.projects.length === 0 && <FormError message={t('mr.noProjects')} />}
        <FormError message={errText(create.error ?? options.error, t('auth.unexpected'))} />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Field label={t('pr.project')} required>
            <Select
              value={v.project}
              onChange={(e) => {
                const p = o?.projects.find((x) => x.id === e.target.value);
                const site = o?.sites.find((s) => s.project_code === p?.number);
                setV({
                  ...v,
                  project: e.target.value,
                  wbs: p?.wbs[0]?.code ?? '',
                  site: site?.code ?? v.site,
                });
              }}
            >
              <option value="">{t('master.choose')}</option>
              {o?.projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.number} · {p.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="WBS" required>
            <Select value={v.wbs} onChange={(e) => setV({ ...v, wbs: e.target.value })}>
              {project?.wbs.map((w) => (
                <option key={w.code} value={w.code}>
                  {w.code} · {w.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t('project.costElement')} required>
            <Select value={v.element} onChange={(e) => setV({ ...v, element: e.target.value })}>
              {o?.cost_elements.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.code} · {c.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t('mr.site')} required>
            <Select value={v.site} onChange={(e) => setV({ ...v, site: e.target.value })}>
              <option value="">{t('master.choose')}</option>
              {o?.sites.map((s) => (
                <option key={s.code} value={s.code}>
                  {s.code} · {s.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t('pr.needDate')} required>
            <Input
              type="date"
              value={v.need}
              onChange={(e) => setV({ ...v, need: e.target.value })}
            />
          </Field>
        </div>
        <div className="overflow-x-auto">
          <Table>
            <THead>
              <TR>
                <TH>{t('mr.item')}</TH>
                <TH className="w-32 text-right">{t('quotation.qty')}</TH>
                <TH className="w-12" />
              </TR>
            </THead>
            <TBody>
              {lines.map((l, i) => {
                const item = o?.items.find((x) => x.code === l.item);
                return (
                  <TR key={i}>
                    <TD className="min-w-56">
                      <Select
                        aria-label={`${t('mr.item')} ${i + 1}`}
                        value={l.item}
                        onChange={(e) => setLine(i, { item: e.target.value })}
                      >
                        <option value="">{t('master.choose')}</option>
                        {o?.items.map((x) => (
                          <option key={x.code} value={x.code}>
                            {x.code} · {x.name} ({x.uom})
                          </option>
                        ))}
                      </Select>
                      {item && !item.last_price && (
                        <span className="text-caption text-warning">{t('mr.noPrice')}</span>
                      )}
                    </TD>
                    <TD>
                      <Input
                        aria-label={`${t('quotation.qty')} ${i + 1}`}
                        inputMode="decimal"
                        className="text-right"
                        value={l.qty}
                        onChange={(e) => setLine(i, { qty: e.target.value })}
                      />
                    </TD>
                    <TD>
                      {lines.length > 1 && (
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={t('quotation.removeLine')}
                          onClick={() => setLines(lines.filter((_, j) => j !== i))}
                        >
                          <Icon name="delete" />
                        </Button>
                      )}
                    </TD>
                  </TR>
                );
              })}
            </TBody>
          </Table>
        </div>
        <Button
          variant="secondary"
          size="sm"
          className="self-start"
          onClick={() => setLines([...lines, { item: '', qty: '1' }])}
        >
          <Icon name="add" /> {t('mr.addLine')}
        </Button>
        <Field label={t('pr.purpose')}>
          <Textarea
            rows={2}
            value={v.purpose}
            onChange={(e) => setV({ ...v, purpose: e.target.value })}
          />
        </Field>
        <Button
          variant="primary"
          className="self-end"
          disabled={!ready || create.isPending}
          onClick={() =>
            create.mutate(
              {
                project_id: v.project,
                wbs_code: v.wbs,
                cost_element_code: v.element,
                site_warehouse: v.site,
                need_date: v.need,
                purpose: v.purpose.trim() || null,
                lines: lines.map((l) => ({ item_code: l.item, qty: qtyToApi(l.qty) })),
              },
              { onSuccess: (mr) => navigate(`/gudang/mr/${mr.id}`) },
            )
          }
        >
          <Icon name="send" /> {t('mr.submit')}
        </Button>
      </CardContent>
    </Card>
  );
}

export function MrPage() {
  const { t } = useTranslation();
  const { id = '' } = useParams();
  const mr = useMr(id);
  if (mr.isLoading) return <p className="text-fg-secondary">{t('common.loading')}</p>;
  if (mr.error || !mr.data) return <FormError message={errText(mr.error, t('auth.unexpected'))} />;
  const d = mr.data;
  return (
    <div className="flex flex-col gap-4">
      <Link
        to="/gudang/mr"
        className="inline-flex items-center gap-1 text-small font-semibold text-fg-accent"
      >
        <Icon name="arrow_back" /> {t('mr.back')}
      </Link>
      <Card>
        <CardHeader>
          <p className="eyebrow">
            {d.number} · {d.project_number} · {d.wbs_code}/{d.cost_element_code}
          </p>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <CardTitle className="text-section-title">{d.purpose || d.project_name}</CardTitle>
            <MrStatusPill status={d.status} />
          </div>
          <CardDescription>
            {t('pr.requester')}: {d.requester_name} · {t('pr.needDate')}: {formatDate(d.need_date)}{' '}
            · {d.site_warehouse}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2 text-small">
          <p>
            {t('mr.issuedValue')}:{' '}
            <span className="font-semibold tabular-nums text-fg">{formatIDR(d.issued_value)}</span>
          </p>
          {d.pr && (
            <p className="rounded-control bg-info-tint px-3 py-2 text-fg-body">
              {t('mr.prCreated')}{' '}
              <Link to={`/pengadaan/pr/${d.pr.id}`} className="font-semibold underline">
                {d.pr.number}
              </Link>{' '}
              ({t(`pr.status.${d.pr.status}`)})
            </p>
          )}
        </CardContent>
      </Card>
      <div className="grid gap-4 lg:grid-cols-[1fr_24rem]">
        <Card>
          <CardContent className="overflow-x-auto pt-4">
            <Table>
              <THead>
                <TR>
                  <TH>{t('mr.item')}</TH>
                  <TH className="text-right">{t('mr.requested')}</TH>
                  <TH className="text-right">{t('mr.fromSite')}</TH>
                  <TH className="text-right">{t('mr.fromBase')}</TH>
                  <TH className="text-right">{t('mr.shortfall')}</TH>
                  <TH className="text-right">{t('mr.value')}</TH>
                </TR>
              </THead>
              <TBody>
                {d.lines.map((l) => (
                  <TR key={l.seq}>
                    <TD className="min-w-48">
                      {l.name}
                      <span className="block text-caption text-fg-muted">
                        {l.item_code} · {l.uom}
                      </span>
                    </TD>
                    <TD className="text-right tabular-nums">{qtyFmt(l.qty)}</TD>
                    <TD className="text-right tabular-nums">{qtyFmt(l.from_site)}</TD>
                    <TD className="text-right tabular-nums">{qtyFmt(l.from_base)}</TD>
                    <TD
                      className={
                        Number(l.shortfall) > 0
                          ? 'text-right font-semibold tabular-nums text-danger'
                          : 'text-right tabular-nums'
                      }
                    >
                      {qtyFmt(l.shortfall)}
                    </TD>
                    <TD className="whitespace-nowrap text-right tabular-nums">
                      {formatIDR(l.value)}
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          </CardContent>
        </Card>
        {d.journal && <JournalCard journal={d.journal} />}
      </div>
    </div>
  );
}
