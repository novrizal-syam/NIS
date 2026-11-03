import { useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input, Select } from '@/components/ui/input';
import { StatusPill } from '@/components/ui/status-pill';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { FormError } from '@/features/auth/AuthLayout';
import { moneyToApi } from '@/features/crm/api';
import { ApiError } from '@/lib/api';
import { formatIDR, formatNumber } from '@/lib/format';
import { cn } from '@/lib/utils';
import { useAddWbs, useDeleteWbs, useSaveBudget, type ProjectDetail } from './api';

const CONTINGENCY = 'CONTINGENCY';
const key = (wbs: string, el: string) => `${wbs}|${el}`;
const errText = (e: unknown, fallback: string) =>
  e instanceof ApiError ? e.message : e ? fallback : null;

/** Cost element (rows) x WBS (columns). Totals and margin come from the server on save. */
export function BudgetEditor({ p }: { p: ProjectDetail }) {
  const { t } = useTranslation();
  const save = useSaveBudget(p.id);
  const addWbs = useAddWbs(p.id);
  const delWbs = useDeleteWbs(p.id);
  const editable = p.can_edit_budget;
  const initial = useMemo(() => {
    const m: Record<string, string> = {};
    for (const c of p.cells)
      m[key(c.wbs_code, c.cost_element_code)] = formatNumber(Number(c.amount));
    return m;
  }, [p.cells]);
  const [values, setValues] = useState(initial);
  const [rows, setRows] = useState<string[]>([]);
  const [dirty, setDirty] = useState(false);
  const [newRow, setNewRow] = useState('');
  const [wbs, setWbs] = useState({ code: '', name: '' });
  useEffect(() => {
    if (!dirty) {
      setValues(initial);
      setRows([]);
    }
  }, [initial, dirty]);

  const used = new Set(p.cells.map((c) => c.cost_element_code));
  const elements = p.cost_elements.filter((e) => used.has(e.code) || rows.includes(e.code));
  const names = Object.fromEntries(p.cost_elements.map((e) => [e.code, e.name]));
  const num = (v: string | undefined) => Number(moneyToApi(v ?? '') ?? 0);
  const rowTotal = (el: string) => p.wbs.reduce((a, w) => a + num(values[key(w.code, el)]), 0);
  const colTotal = (w: string) => elements.reduce((a, e) => a + num(values[key(w, e.code)]), 0);

  const submit = () =>
    save.mutate(
      Object.entries(values)
        .map(([k, v]) => {
          const [wbs_code, cost_element_code] = k.split('|') as [string, string];
          return { wbs_code, cost_element_code, amount: moneyToApi(v) ?? '0' };
        })
        .filter((c) => c.amount !== '0'),
      { onSuccess: () => setDirty(false) },
    );

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('project.budgetTitle')}</CardTitle>
        <CardDescription>
          {editable ? t('project.editorHelp') : t('project.readOnlyBudget')}
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <FormError
          message={errText(save.error ?? addWbs.error ?? delWbs.error, t('auth.unexpected'))}
        />
        <div className="overflow-x-auto">
          <Table>
            <THead>
              <TR>
                <TH>{t('project.costElement')}</TH>
                {p.wbs.map((w) => (
                  <TH key={w.id} className="min-w-36 text-right">
                    <span className="flex items-center justify-end gap-1">
                      <span title={w.name}>{w.code}</span>
                      {editable && w.code !== 'EXEC' && (
                        <button
                          type="button"
                          aria-label={`${t('project.removeWbs')} ${w.code}`}
                          className="text-fg-muted hover:text-danger"
                          onClick={() => delWbs.mutate(w.id)}
                        >
                          <Icon name="close" />
                        </button>
                      )}
                    </span>
                    <span className="block text-caption font-normal text-fg-muted">{w.name}</span>
                  </TH>
                ))}
                <TH className="text-right">{t('project.total')}</TH>
              </TR>
            </THead>
            <TBody>
              {elements.map((e) => (
                <TR key={e.code} className={cn(e.code === CONTINGENCY && 'bg-surface-muted')}>
                  <TD className="min-w-48">
                    {e.name}
                    <span className="flex items-center gap-2 text-caption text-fg-muted">
                      {e.code}
                      {e.code === CONTINGENCY && (
                        <StatusPill tone="info">{t('project.lockedReserve')}</StatusPill>
                      )}
                    </span>
                  </TD>
                  {p.wbs.map((w) => (
                    <TD key={w.id} className="text-right tabular-nums">
                      {editable ? (
                        <Input
                          aria-label={`${e.code} ${w.code}`}
                          inputMode="numeric"
                          className="text-right"
                          value={values[key(w.code, e.code)] ?? ''}
                          onChange={(ev) => {
                            setValues({ ...values, [key(w.code, e.code)]: ev.target.value });
                            setDirty(true);
                          }}
                        />
                      ) : values[key(w.code, e.code)] ? (
                        `Rp ${values[key(w.code, e.code)]}`
                      ) : (
                        '–'
                      )}
                    </TD>
                  ))}
                  <TD className="whitespace-nowrap text-right font-semibold tabular-nums text-fg">
                    {formatIDR(rowTotal(e.code))}
                  </TD>
                </TR>
              ))}
              <TR>
                <TD className="font-semibold text-fg">{t('project.total')}</TD>
                {p.wbs.map((w) => (
                  <TD key={w.id} className="whitespace-nowrap text-right tabular-nums">
                    {formatIDR(colTotal(w.code))}
                  </TD>
                ))}
                <TD className="whitespace-nowrap text-right font-semibold tabular-nums text-fg">
                  {dirty ? '–' : formatIDR(p.total_cost)}
                </TD>
              </TR>
            </TBody>
          </Table>
        </div>
        {editable && (
          <div className="flex flex-col gap-3">
            <div className="flex flex-wrap items-end gap-2">
              <Field label={t('project.addElement')} className="w-full sm:w-72">
                <Select value={newRow} onChange={(e) => setNewRow(e.target.value)}>
                  <option value="">–</option>
                  {p.cost_elements
                    .filter((e) => !elements.some((x) => x.code === e.code))
                    .map((e) => (
                      <option key={e.code} value={e.code}>
                        {e.code} · {names[e.code]}
                      </option>
                    ))}
                </Select>
              </Field>
              <Button
                variant="secondary"
                disabled={!newRow}
                onClick={() => {
                  setRows([...rows, newRow]);
                  setNewRow('');
                  setDirty(true);
                }}
              >
                <Icon name="add" /> {t('project.addRow')}
              </Button>
              <Field label={t('project.wbsCode')} className="w-32">
                <Input
                  value={wbs.code}
                  onChange={(e) => setWbs({ ...wbs, code: e.target.value })}
                />
              </Field>
              <Field label={t('project.wbsName')} className="min-w-0 flex-1">
                <Input
                  value={wbs.name}
                  placeholder={t('project.wbsHint')}
                  onChange={(e) => setWbs({ ...wbs, name: e.target.value })}
                />
              </Field>
              <Button
                variant="secondary"
                disabled={wbs.code.trim().length < 2 || wbs.name.trim().length < 2 || dirty}
                title={dirty ? t('project.saveFirst') : undefined}
                onClick={() =>
                  addWbs.mutate(
                    { code: wbs.code.trim().toUpperCase(), name: wbs.name.trim() },
                    { onSuccess: () => setWbs({ code: '', name: '' }) },
                  )
                }
              >
                <Icon name="add" /> {t('project.addWbs')}
              </Button>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <Button variant="primary" disabled={!dirty || save.isPending} onClick={submit}>
                {t('quotation.saveRecalc')}
              </Button>
              {dirty && (
                <span role="status" className="text-small text-warning">
                  {t('quotation.unsaved')}
                </span>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
