import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input, Select } from '@/components/ui/input';
import { StatusPill } from '@/components/ui/status-pill';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { FormError } from '@/features/auth/AuthLayout';
import { useAuth } from '@/features/auth/AuthProvider';
import { ApiError, api, downloadFile } from '@/lib/api';
import { formatIDR } from '@/lib/format';

const errText = (e: unknown, fallback: string) =>
  e instanceof ApiError ? e.message : e ? fallback : null;

interface ProcessMap {
  lanes: string[];
  phases: string[];
  cells: {
    lane: string;
    phase: string;
    key: string;
    count: number;
    link: string;
    attention: boolean;
  }[];
}

export function ProcessMapCard() {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['dashboard', 'map'],
    queryFn: () => api<ProcessMap>('/dashboard/process-map'),
    refetchInterval: 60_000,
  });
  const m = q.data;
  return (
    <Card className="overflow-x-auto">
      <CardHeader>
        <CardTitle>{t('dash.map.title')}</CardTitle>
        <CardDescription>{t('dash.map.hint')}</CardDescription>
      </CardHeader>
      <CardContent>
        <FormError message={errText(q.error, t('auth.unexpected'))} />
        {m && (
          <div
            className="grid min-w-[720px] gap-1 text-small"
            style={{ gridTemplateColumns: `8rem repeat(${m.phases.length}, minmax(0, 1fr))` }}
          >
            <div />
            {m.phases.map((ph) => (
              <div key={ph} className="eyebrow px-1 pb-1">
                {t(`dash.phases.${ph}`)}
              </div>
            ))}
            {m.lanes.map((lane) => (
              <div key={lane} className="contents">
                <div className="flex items-center rounded-md bg-surface-inverse px-2 py-2 font-semibold text-fg-on-inverse">
                  {t(`dash.lanes.${lane}`)}
                </div>
                {m.phases.map((ph) => (
                  <div
                    key={ph}
                    className="flex min-h-14 flex-col gap-1 rounded-md bg-surface-muted p-1"
                  >
                    {m.cells
                      .filter((c) => c.lane === lane && c.phase === ph)
                      .map((c) => (
                        <Link
                          key={c.key}
                          to={c.link}
                          className="flex items-center justify-between gap-1 rounded bg-surface-raised px-2 py-1 hover:ring-1 hover:ring-border-strong"
                        >
                          <span className="truncate">{t(`dash.cells.${c.key}`)}</span>
                          <span
                            className={`rounded-pill px-1.5 font-semibold tabular-nums ${
                              c.attention ? 'bg-brand-gold text-on-gold' : 'text-fg-secondary'
                            }`}
                          >
                            {c.count}
                          </span>
                        </Link>
                      ))}
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

interface Tile {
  key: string;
  value: string | number | null;
  unit: string;
  link: string | null;
  tone: 'neutral' | 'warning' | 'danger';
}

function tileValue(
  v: Tile['value'],
  unit: string,
  t: (k: string, o?: Record<string, unknown>) => string,
): string {
  if (v === null || v === undefined) return '-';
  if (unit === 'idr') return formatIDR(String(v));
  if (unit === 'days') return t('dash.days', { n: String(v).replace('.', ',') });
  return String(v);
}

export function RoleDashboards() {
  const { t } = useTranslation();
  const kinds = useQuery({
    queryKey: ['dashboard', 'roles'],
    queryFn: () => api<string[]>('/dashboard/roles'),
  });
  const [pick, setPick] = useState<string | null>(null);
  const kind = pick ?? kinds.data?.[0] ?? null;
  const tiles = useQuery({
    queryKey: ['dashboard', 'role', kind],
    queryFn: () => api<{ tiles: Tile[] }>(`/dashboard/roles/${kind}`),
    enabled: !!kind,
  });
  if (!kinds.data?.length) return null;
  return (
    <Card>
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
        <CardTitle>{t(`dash.roles.${kind}`)}</CardTitle>
        {kinds.data.length > 1 && (
          <Select
            aria-label={t('dash.pickDashboard')}
            value={kind ?? ''}
            onChange={(e) => setPick(e.target.value)}
            className="w-48"
          >
            {kinds.data.map((k) => (
              <option key={k} value={k}>
                {t(`dash.roles.${k}`)}
              </option>
            ))}
          </Select>
        )}
      </CardHeader>
      <CardContent>
        <FormError message={errText(tiles.error, t('auth.unexpected'))} />
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
          {tiles.data?.tiles.map((x) => {
            const body = (
              <div
                className={`rounded-md border p-3 ${
                  x.tone === 'danger'
                    ? 'border-danger'
                    : x.tone === 'warning'
                      ? 'border-warning'
                      : 'border-border'
                }`}
              >
                <div className="text-small text-fg-secondary">{t(`dash.tiles.${x.key}`)}</div>
                <div className="text-h4 font-heading tabular-nums">
                  {tileValue(x.value, x.unit, t)}
                </div>
              </div>
            );
            return x.link ? (
              <Link key={x.key} to={x.link} className="block">
                {body}
              </Link>
            ) : (
              <div key={x.key}>{body}</div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

interface OkrRow {
  key: string;
  actual: string | null;
  target: string;
  unit: string;
  status: 'on_track' | 'off_track' | 'n/a';
  year_target?: string;
}

function okrValue(v: string | null, unit: string): string {
  if (v === null) return '-';
  if (unit === 'idr') return formatIDR(v);
  if (unit === 'pct') return `${v.replace('.', ',')}%`;
  if (unit === 'x') return `${v.replace('.', ',')}×`;
  return v;
}

export function OkrCard() {
  const { t } = useTranslation();
  const { me } = useAuth();
  const qc = useQueryClient();
  const year = new Date().getFullYear();
  const okr = useQuery({
    queryKey: ['dashboard', 'okr', year],
    queryFn: () =>
      api<{ year: number; as_of: string; rows: OkrRow[] }>(`/dashboard/okr?year=${year}`),
  });
  const [editing, setEditing] = useState(false);
  const targets = useQuery({
    queryKey: ['dashboard', 'targets', year],
    queryFn: () => api<Record<string, number>>(`/dashboard/okr/targets/${year}`),
    enabled: editing,
  });
  const [draft, setDraft] = useState<Record<string, string>>({});
  const save = useMutation({
    mutationFn: () =>
      api(`/dashboard/okr/targets/${year}`, {
        method: 'PUT',
        body: JSON.stringify(
          Object.fromEntries(
            Object.entries({ ...targets.data, ...draft }).map(([k, v]) => [
              k,
              Number(String(v).replace(/\./g, '').replace(',', '.')),
            ]),
          ),
        ),
      }),
    onSuccess: () => {
      setEditing(false);
      void qc.invalidateQueries({ queryKey: ['dashboard'] });
    },
  });
  const canEdit = me?.roles.some((r) =>
    ['director', 'head_of_finance', 'super_admin'].includes(r.code),
  );
  const month = new Date().getMonth() + 1;
  return (
    <Card className="overflow-x-auto">
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
        <div>
          <CardTitle>{t('dash.okr.title', { year })}</CardTitle>
          <CardDescription>{t('dash.okr.hint')}</CardDescription>
        </div>
        <div className="flex flex-wrap gap-2">
          {canEdit && (
            <Button variant="ghost" onClick={() => setEditing(!editing)}>
              <Icon name="tune" /> {t('dash.okr.targets')}
            </Button>
          )}
          <Button
            onClick={() =>
              void downloadFile(
                `/dashboard/management-pack/${year}/${month}`,
                `laporan-manajemen-${year}-${month}.pdf`,
              )
            }
          >
            <Icon name="picture_as_pdf" /> {t('dash.okr.pack')}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <FormError message={errText(okr.error ?? save.error, t('auth.unexpected'))} />
        <Table>
          <THead>
            <TR>
              <TH>{t('dash.okr.objective')}</TH>
              <TH className="text-right">{t('dash.okr.actual')}</TH>
              <TH className="text-right">{t('dash.okr.target')}</TH>
              <TH>{t('dash.okr.status')}</TH>
            </TR>
          </THead>
          <TBody>
            {okr.data?.rows.map((r) => (
              <TR key={r.key}>
                <TD>{t(`dash.okr.rows.${r.key}`)}</TD>
                <TD className="text-right tabular-nums">{okrValue(r.actual, r.unit)}</TD>
                <TD className="text-right tabular-nums">
                  {okrValue(r.target, r.unit)}
                  {r.year_target && (
                    <div className="text-small text-fg-secondary">
                      {t('dash.okr.yearTarget', { v: formatIDR(r.year_target) })}
                    </div>
                  )}
                </TD>
                <TD>
                  <StatusPill
                    tone={
                      r.status === 'on_track'
                        ? 'success'
                        : r.status === 'off_track'
                          ? 'danger'
                          : 'neutral'
                    }
                  >
                    {t(`dash.okr.statuses.${r.status === 'n/a' ? 'na' : r.status}`)}
                  </StatusPill>
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
        {editing && targets.data && (
          <div className="flex flex-wrap items-end gap-2">
            {Object.entries(targets.data).map(([k, v]) => (
              <Field key={k} label={t(`dash.okr.rows.${k}`)} className="w-48">
                <Input
                  inputMode="decimal"
                  value={draft[k] ?? String(v)}
                  onChange={(e) => setDraft({ ...draft, [k]: e.target.value })}
                />
              </Field>
            ))}
            <Button variant="primary" onClick={() => save.mutate()}>
              {t('dash.okr.save')}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
