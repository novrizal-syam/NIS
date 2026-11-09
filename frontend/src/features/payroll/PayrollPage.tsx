import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input, Select } from '@/components/ui/input';
import { StatusPill, type StatusTone } from '@/components/ui/status-pill';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { FormError } from '@/features/auth/AuthLayout';
import { useAuth } from '@/features/auth/AuthProvider';
import { moneyToApi } from '@/features/crm/api';
import { ApiError, api, downloadFile, postJson } from '@/lib/api';
import { formatDate, formatIDR } from '@/lib/format';

const errText = (e: unknown, fallback: string) =>
  e instanceof ApiError ? e.message : e ? fallback : null;
const nowJakarta = () =>
  new Intl.DateTimeFormat('en-CA', { timeZone: 'Asia/Jakarta' }).format(new Date());

interface Run {
  id: string;
  year: number;
  month: number;
  label: string;
  period_start: string;
  period_end: string;
  pay_date: string;
  status: string;
  status_label: string;
  request_id: string | null;
  reject_reason: string | null;
  journal_id: string | null;
  employees: number;
  gross: string;
  employer_bpjs: string;
  employee_bpjs: string;
  pph21: string;
  deductions: string;
  net: string;
  employer_cost: string;
}

interface Slip {
  id: string;
  employee_code: string;
  employee_name: string;
  position: string | null;
  is_field: boolean;
  ptkp_status: string;
  ter_category: string;
  site_days: number;
  overtime_hours: string;
  gross?: string;
  pph21?: string;
  net?: string;
  employer_cost?: string;
  ter_rate?: string;
  annual?: Record<string, string> | null;
}

interface RunDetail extends Run {
  allocation: { project_id: string; project: string | null; amount: string }[];
  office_cost: string;
  payslips: Slip[];
}

interface SlipDetail extends Slip {
  basic: string;
  fixed_allowance: string;
  field_allowance: string;
  overtime_pay: string;
  other_allowances: string;
  kes_ee: string;
  jht_ee: string;
  jp_ee: string;
  deductions: string;
  taxable: string;
  run: Run;
  days: {
    work_date: string;
    project_id: string;
    project: string | null;
    overtime_hours: string;
    source: string;
    note: string | null;
  }[];
  items: { kind: 'allowance' | 'deduction'; name: string; amount: string; taxable: boolean }[];
}

const TONES: Record<string, StatusTone> = {
  calculated: 'neutral',
  awaiting_approval: 'warning',
  approved: 'info',
  paid: 'success',
};

function usePayrollAction<R = unknown>() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: { path: string; body?: unknown; method?: string }) =>
      v.method
        ? api<R>(v.path, { method: v.method, body: JSON.stringify(v.body) })
        : postJson<R>(v.path, v.body ?? {}),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['payroll'] }),
  });
}

export function PayrollPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const runs = useQuery({
    queryKey: ['payroll', 'runs'],
    queryFn: () => api<Run[]>('/payroll/runs'),
  });
  const [open, setOpen] = useState<string | null>(null);
  const [y, m] = nowJakarta().split('-').map(Number);
  const [period, setPeriod] = useState({ year: y, month: m });
  const act = usePayrollAction<Run>();
  return (
    <div className="flex flex-col gap-4">
      <Card className="overflow-x-auto">
        <CardHeader>
          <CardTitle>{t('payroll.title')}</CardTitle>
          <CardDescription>{t('payroll.hint')}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          {can('payroll', 'create') && (
            <div className="flex flex-wrap items-end gap-2">
              <Field label={t('payroll.year')} className="w-28">
                <Input
                  type="number"
                  value={period.year}
                  onChange={(e) => setPeriod({ ...period, year: Number(e.target.value) })}
                />
              </Field>
              <Field label={t('payroll.month')} className="w-28">
                <Select
                  value={period.month}
                  onChange={(e) => setPeriod({ ...period, month: Number(e.target.value) })}
                >
                  {Array.from({ length: 12 }, (_, i) => i + 1).map((n) => (
                    <option key={n} value={n}>
                      {String(n).padStart(2, '0')}
                    </option>
                  ))}
                </Select>
              </Field>
              <Button
                variant="primary"
                disabled={act.isPending}
                onClick={() =>
                  act.mutate(
                    { path: '/payroll/runs', body: period },
                    { onSuccess: (r) => setOpen(r.id) },
                  )
                }
              >
                <Icon name="calculate" /> {t('payroll.calculate')}
              </Button>
            </div>
          )}
          <FormError message={errText(act.error ?? runs.error, t('auth.unexpected'))} />
          <Table>
            <THead>
              <TR>
                <TH>{t('payroll.period')}</TH>
                <TH className="text-right">{t('payroll.employees')}</TH>
                <TH className="text-right">{t('payroll.net')}</TH>
                <TH className="text-right">{t('payroll.cost')}</TH>
                <TH>{t('payroll.status')}</TH>
              </TR>
            </THead>
            <TBody>
              {runs.data?.map((r) => (
                <TR key={r.id}>
                  <TD>
                    <Button size="sm" variant="link" onClick={() => setOpen(r.id)}>
                      {r.label}
                    </Button>
                  </TD>
                  <TD className="text-right">{r.employees}</TD>
                  <TD className="text-right tabular-nums">{formatIDR(r.net)}</TD>
                  <TD className="text-right tabular-nums">{formatIDR(r.employer_cost)}</TD>
                  <TD>
                    <StatusPill tone={TONES[r.status] ?? 'neutral'}>{r.status_label}</StatusPill>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
          {runs.data?.length === 0 && (
            <p className="text-small text-fg-secondary">{t('payroll.empty')}</p>
          )}
        </CardContent>
      </Card>
      {open && <RunCard id={open} />}
    </div>
  );
}

function RunCard({ id }: { id: string }) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const run = useQuery({
    queryKey: ['payroll', 'run', id],
    queryFn: () => api<RunDetail>(`/payroll/runs/${id}`),
  });
  const act = usePayrollAction();
  const [slip, setSlip] = useState<string | null>(null);
  const r = run.data;
  if (!r) return <FormError message={errText(run.error, t('auth.unexpected'))} />;
  const editable = r.status === 'calculated' && can('payroll', 'edit');
  const base = `/payroll/runs/${r.id}`;
  const totals: [string, string][] = [
    ['gross', r.gross],
    ['employerBpjs', r.employer_bpjs],
    ['employeeBpjs', r.employee_bpjs],
    ['pph21', r.pph21],
    ['deductions', r.deductions],
    ['net', r.net],
    ['cost', r.employer_cost],
  ];
  return (
    <>
      <Card className="overflow-x-auto">
        <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
          <div>
            <CardTitle>{r.label}</CardTitle>
            <CardDescription>
              {t('payroll.periodRange', {
                from: formatDate(r.period_start),
                to: formatDate(r.period_end),
                pay: formatDate(r.pay_date),
              })}
            </CardDescription>
          </div>
          <StatusPill tone={TONES[r.status] ?? 'neutral'}>{r.status_label}</StatusPill>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          {r.reject_reason && (
            <p role="alert" className="text-small text-danger">
              {t('payroll.rejected')}: {r.reject_reason}
            </p>
          )}
          <div className="grid gap-2 sm:grid-cols-4">
            {totals.map(([k, v]) => (
              <div key={k} className="rounded-md border border-border p-3">
                <div className="text-small text-fg-secondary">{t(`payroll.totals.${k}`)}</div>
                <div className="text-h4 font-heading tabular-nums">{formatIDR(v)}</div>
              </div>
            ))}
          </div>
          {r.allocation.length > 0 && (
            <div>
              <h3 className="mb-2 font-heading text-body font-semibold">
                {t('payroll.allocation')}
              </h3>
              <Table>
                <TBody>
                  {r.allocation.map((a) => (
                    <TR key={a.project_id}>
                      <TD>{a.project ?? a.project_id}</TD>
                      <TD className="text-right tabular-nums">{formatIDR(a.amount)}</TD>
                    </TR>
                  ))}
                  <TR>
                    <TD>{t('payroll.officeCost')}</TD>
                    <TD className="text-right tabular-nums">{formatIDR(r.office_cost)}</TD>
                  </TR>
                </TBody>
              </Table>
            </div>
          )}
          <Table>
            <THead>
              <TR>
                <TH>{t('payroll.employee')}</TH>
                <TH>PTKP / TER</TH>
                <TH className="text-right">{t('payroll.siteDays')}</TH>
                <TH className="text-right">{t('payroll.overtime')}</TH>
                <TH className="text-right">{t('payroll.totals.gross')}</TH>
                <TH className="text-right">PPh 21</TH>
                <TH className="text-right">{t('payroll.totals.net')}</TH>
              </TR>
            </THead>
            <TBody>
              {r.payslips.map((s) => (
                <TR key={s.id}>
                  <TD>
                    {s.net !== undefined ? (
                      <Button size="sm" variant="link" onClick={() => setSlip(s.id)}>
                        {s.employee_name}
                      </Button>
                    ) : (
                      s.employee_name
                    )}
                    <div className="text-small text-fg-secondary">
                      {s.employee_code} · {s.is_field ? t('payroll.field') : t('payroll.office')}
                    </div>
                  </TD>
                  <TD>
                    {s.ptkp_status} / {s.ter_category}
                    {s.ter_rate ? ` ${s.ter_rate}%` : ''}
                  </TD>
                  <TD className="text-right">{s.site_days}</TD>
                  <TD className="text-right">{s.overtime_hours}</TD>
                  <TD className="text-right tabular-nums">
                    {s.gross ? formatIDR(s.gross) : '•••'}
                  </TD>
                  <TD className="text-right tabular-nums">
                    {s.pph21 ? formatIDR(s.pph21) : '•••'}
                  </TD>
                  <TD className="text-right tabular-nums">{s.net ? formatIDR(s.net) : '•••'}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
          <FormError message={errText(act.error, t('auth.unexpected'))} />
          <div className="flex flex-wrap gap-2">
            {editable && (
              <>
                <Button
                  onClick={() =>
                    act.mutate({ path: `${base}/recalculate`, body: { reload: false } })
                  }
                >
                  <Icon name="refresh" /> {t('payroll.recalculate')}
                </Button>
                <Button
                  onClick={() =>
                    act.mutate({ path: `${base}/recalculate`, body: { reload: true } })
                  }
                >
                  <Icon name="sync" /> {t('payroll.reload')}
                </Button>
              </>
            )}
            {r.status === 'calculated' && can('payroll', 'submit') && (
              <Button variant="primary" onClick={() => act.mutate({ path: `${base}/submit` })}>
                {t('payroll.submit')}
              </Button>
            )}
            <Button
              onClick={() =>
                void downloadFile(
                  `${base}/export`,
                  `gaji-${r.year}-${String(r.month).padStart(2, '0')}.xlsx`,
                )
              }
            >
              <Icon name="download" /> Excel
            </Button>
          </div>
          <p className="text-small text-fg-secondary">{t('payroll.sod')}</p>
        </CardContent>
      </Card>
      {slip && <SlipCard id={slip} editable={editable} />}
    </>
  );
}

function SlipCard({ id, editable }: { id: string; editable: boolean }) {
  const { t } = useTranslation();
  const slip = useQuery({
    queryKey: ['payroll', 'slip', id],
    queryFn: () => api<SlipDetail>(`/payroll/payslips/${id}`),
  });
  const act = usePayrollAction();
  const [reason, setReason] = useState('');
  const [days, setDays] = useState<SlipDetail['days'] | null>(null);
  const [items, setItems] = useState<SlipDetail['items'] | null>(null);
  const s = slip.data;
  if (!s) return <FormError message={errText(slip.error, t('auth.unexpected'))} />;
  const curDays = days ?? s.days;
  const curItems = items ?? s.items;
  const rows: [string, string][] = [
    ['basic', s.basic],
    ['fixedAllowance', s.fixed_allowance],
    ['fieldAllowance', s.field_allowance],
    ['overtimePay', s.overtime_pay],
    ['otherAllowances', s.other_allowances],
    ['bpjsEmployee', String(Number(s.kes_ee) + Number(s.jht_ee) + Number(s.jp_ee))],
    ['pph21', s.pph21 ?? '0'],
    ['deductions', s.deductions],
    ['net', s.net ?? '0'],
  ];
  return (
    <Card className="overflow-x-auto">
      <CardHeader className="flex-row flex-wrap items-center justify-between gap-2">
        <div>
          <CardTitle>
            {s.employee_name} · {s.run.label}
          </CardTitle>
          <CardDescription>
            {s.employee_code} · {s.position} · PTKP {s.ptkp_status}
          </CardDescription>
        </div>
        <Button
          onClick={() =>
            void downloadFile(`/payroll/payslips/${s.id}/pdf`, `slip-${s.employee_code}.pdf`)
          }
        >
          <Icon name="picture_as_pdf" /> {t('payroll.payslipPdf')}
        </Button>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <Table>
          <TBody>
            {rows.map(([k, v]) => (
              <TR key={k}>
                <TD>{t(`payroll.slip.${k}`)}</TD>
                <TD className="text-right tabular-nums">{formatIDR(v)}</TD>
              </TR>
            ))}
          </TBody>
        </Table>
        {s.annual && (
          <p className="text-small text-fg-secondary">
            {t('payroll.annualHint', {
              tax: formatIDR(s.annual.tax ?? 0),
              withheld: formatIDR(s.annual.withheld ?? 0),
            })}
          </p>
        )}
        <div>
          <h3 className="mb-2 font-heading text-body font-semibold">{t('payroll.timesheet')}</h3>
          <Table>
            <THead>
              <TR>
                <TH>{t('payroll.date')}</TH>
                <TH>{t('payroll.project')}</TH>
                <TH className="text-right">{t('payroll.overtime')}</TH>
                <TH>{t('payroll.source')}</TH>
                {editable && <TH />}
              </TR>
            </THead>
            <TBody>
              {curDays.map((d, i) => (
                <TR key={d.work_date}>
                  <TD>{formatDate(d.work_date)}</TD>
                  <TD>{d.project ?? d.project_id}</TD>
                  <TD className="w-28 text-right">
                    {editable ? (
                      <Input
                        aria-label={`${t('payroll.overtime')} ${d.work_date}`}
                        inputMode="decimal"
                        value={d.overtime_hours}
                        onChange={(e) =>
                          setDays(
                            curDays.map((x, j) =>
                              j === i ? { ...x, overtime_hours: e.target.value } : x,
                            ),
                          )
                        }
                      />
                    ) : (
                      d.overtime_hours
                    )}
                  </TD>
                  <TD>
                    {t(`payroll.sources.${d.source}`)}
                    {d.note ? ` · ${d.note}` : ''}
                  </TD>
                  {editable && (
                    <TD>
                      <Button
                        size="sm"
                        variant="ghost"
                        aria-label={t('payroll.removeDay')}
                        onClick={() => setDays(curDays.filter((_, j) => j !== i))}
                      >
                        <Icon name="delete" />
                      </Button>
                    </TD>
                  )}
                </TR>
              ))}
            </TBody>
          </Table>
          {editable && days && (
            <div className="mt-2 flex flex-wrap items-end gap-2">
              <Field label={t('payroll.reason')} className="w-80">
                <Input value={reason} onChange={(e) => setReason(e.target.value)} />
              </Field>
              <Button
                variant="primary"
                disabled={reason.trim().length < 5}
                onClick={() =>
                  act.mutate(
                    {
                      path: `/payroll/payslips/${s.id}/days`,
                      method: 'PUT',
                      body: {
                        reason,
                        days: curDays.map((d) => ({
                          work_date: d.work_date,
                          project_id: d.project_id,
                          overtime_hours: d.overtime_hours || '0',
                        })),
                      },
                    },
                    { onSuccess: () => (setDays(null), setReason('')) },
                  )
                }
              >
                {t('payroll.saveDays')}
              </Button>
            </div>
          )}
        </div>
        <div>
          <h3 className="mb-2 font-heading text-body font-semibold">{t('payroll.items')}</h3>
          {curItems.map((x, i) => (
            <div key={i} className="mb-2 flex flex-wrap items-end gap-2">
              <Field label={t('payroll.itemKind')} className="w-36">
                <Select
                  disabled={!editable}
                  value={x.kind}
                  onChange={(e) =>
                    setItems(
                      curItems.map((y, j) =>
                        j === i ? { ...y, kind: e.target.value as 'allowance' | 'deduction' } : y,
                      ),
                    )
                  }
                >
                  <option value="allowance">{t('payroll.allowance')}</option>
                  <option value="deduction">{t('payroll.deduction')}</option>
                </Select>
              </Field>
              <Field label={t('payroll.itemName')} className="w-56">
                <Input
                  disabled={!editable}
                  value={x.name}
                  onChange={(e) =>
                    setItems(curItems.map((y, j) => (j === i ? { ...y, name: e.target.value } : y)))
                  }
                />
              </Field>
              <Field label={t('payroll.amount')} className="w-40">
                <Input
                  disabled={!editable}
                  inputMode="numeric"
                  value={x.amount}
                  onChange={(e) =>
                    setItems(
                      curItems.map((y, j) => (j === i ? { ...y, amount: e.target.value } : y)),
                    )
                  }
                />
              </Field>
              {editable && (
                <Button
                  variant="ghost"
                  aria-label={t('payroll.removeItem')}
                  onClick={() => setItems(curItems.filter((_, j) => j !== i))}
                >
                  <Icon name="delete" />
                </Button>
              )}
            </div>
          ))}
          {editable && (
            <div className="flex gap-2">
              <Button
                variant="ghost"
                onClick={() =>
                  setItems([
                    ...curItems,
                    { kind: 'allowance', name: '', amount: '', taxable: true },
                  ])
                }
              >
                <Icon name="add" /> {t('payroll.addItem')}
              </Button>
              {items && (
                <Button
                  variant="primary"
                  onClick={() =>
                    act.mutate(
                      {
                        path: `/payroll/payslips/${s.id}/items`,
                        method: 'PUT',
                        body: {
                          items: curItems.map((x) => ({ ...x, amount: moneyToApi(x.amount) })),
                        },
                      },
                      { onSuccess: () => setItems(null) },
                    )
                  }
                >
                  {t('payroll.saveItems')}
                </Button>
              )}
            </div>
          )}
        </div>
        <FormError message={errText(act.error, t('auth.unexpected'))} />
      </CardContent>
    </Card>
  );
}

export function MyPayslipsPage() {
  const { t } = useTranslation();
  const list = useQuery({
    queryKey: ['payroll', 'mine'],
    queryFn: () =>
      api<{ id: string; label: string; year: number; month: number; net: string }[]>(
        '/payroll/my-payslips',
      ),
  });
  const { me } = useAuth();
  const years = [...new Set(list.data?.map((x) => x.year))];
  return (
    <Card className="overflow-x-auto">
      <CardHeader>
        <CardTitle>{t('nav.items.myPayslips')}</CardTitle>
        <CardDescription>{t('payroll.mineHint')}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <FormError message={errText(list.error, t('auth.unexpected'))} />
        <Table>
          <TBody>
            {list.data?.map((x) => (
              <TR key={x.id}>
                <TD>{x.label}</TD>
                <TD className="text-right tabular-nums">{formatIDR(x.net)}</TD>
                <TD>
                  <Button
                    size="sm"
                    onClick={() =>
                      void downloadFile(
                        `/payroll/payslips/${x.id}/pdf`,
                        `slip-${x.year}-${x.month}.pdf`,
                      )
                    }
                  >
                    <Icon name="picture_as_pdf" /> PDF
                  </Button>
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
        {list.data?.length === 0 && (
          <p className="text-small text-fg-secondary">{t('payroll.mineEmpty')}</p>
        )}
        {me && years.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {years.map((y) => (
              <Button
                key={y}
                onClick={() => void downloadFile(`/payroll/a1/${y}/me`, `1721A1-${y}.pdf`)}
              >
                <Icon name="description" /> 1721-A1 {y}
              </Button>
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
