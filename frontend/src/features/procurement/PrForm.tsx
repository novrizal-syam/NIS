import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input, Select, Textarea } from '@/components/ui/input';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { FormError } from '@/features/auth/AuthLayout';
import { moneyToApi } from '@/features/crm/api';
import { ApiError } from '@/lib/api';
import { formatIDR, formatNumber } from '@/lib/format';
import { usePrFormOptions, useSavePr, type PrDetail, type PrLine } from './api';

const toApiQty = (v: string) => v.replace(/\./g, '').replace(',', '.').trim();

/** Create (pr = null) or edit a Draft/Blocked PR. */
export function PrForm({ pr, onSaved }: { pr: PrDetail | null; onSaved?: () => void }) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const options = usePrFormOptions();
  const save = useSavePr(pr?.id ?? null);
  const [v, setV] = useState({
    project: pr?.project_id ?? '',
    wbs: pr?.wbs_code ?? 'EXEC',
    element: pr?.cost_element_code ?? '',
    need: pr?.need_date ?? '',
    location: pr?.delivery_location ?? '',
    purpose: pr?.purpose ?? '',
  });
  const [lines, setLines] = useState<PrLine[]>(
    pr?.lines.map((l) => ({
      ...l,
      qty: l.qty.replace('.', ','),
      est_price: formatNumber(Number(l.est_price)),
    })) ?? [{ item_code: null, description: '', qty: '1', uom: 'lot', est_price: '' }],
  );
  const project = options.data?.projects.find((p) => p.id === v.project);
  const total = lines.reduce(
    (a, l) => a + Number(toApiQty(l.qty) || 0) * Number(moneyToApi(l.est_price) ?? 0),
    0,
  );
  const setLine = (i: number, patch: Partial<PrLine>) =>
    setLines(lines.map((l, j) => (j === i ? { ...l, ...patch } : l)));
  const ready =
    v.project &&
    v.element &&
    v.need &&
    v.location.trim().length >= 2 &&
    lines.every((l) => l.description.trim().length >= 2 && Number(toApiQty(l.qty)) > 0);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{pr ? t('pr.edit') : t('pr.new')}</CardTitle>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <FormError message={save.error instanceof ApiError ? save.error.message : null} />
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          <Field label={t('pr.project')} required>
            <Select
              value={v.project}
              disabled={pr !== null}
              onChange={(e) => setV({ ...v, project: e.target.value, wbs: 'EXEC' })}
            >
              <option value="">–</option>
              {options.data?.projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.number} · {p.name}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="WBS" required>
            <Select value={v.wbs} onChange={(e) => setV({ ...v, wbs: e.target.value })}>
              {(project?.wbs ?? [{ code: v.wbs, name: '' }]).map((w) => (
                <option key={w.code} value={w.code}>
                  {w.code} {w.name && `· ${w.name}`}
                </option>
              ))}
            </Select>
          </Field>
          <Field label={t('project.costElement')} required>
            <Select value={v.element} onChange={(e) => setV({ ...v, element: e.target.value })}>
              <option value="">–</option>
              {options.data?.cost_elements.map((c) => (
                <option key={c.code} value={c.code}>
                  {c.code} · {c.name}
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
          <Field label={t('pr.location')} required className="lg:col-span-2">
            <Input value={v.location} onChange={(e) => setV({ ...v, location: e.target.value })} />
          </Field>
        </div>
        <Field label={t('pr.purpose')}>
          <Textarea
            rows={2}
            value={v.purpose}
            onChange={(e) => setV({ ...v, purpose: e.target.value })}
          />
        </Field>
        <div className="overflow-x-auto">
          <Table>
            <THead>
              <TR>
                <TH>{t('pr.itemCode')}</TH>
                <TH>{t('quotation.description')}</TH>
                <TH className="w-24 text-right">{t('quotation.qty')}</TH>
                <TH className="w-20">{t('quotation.unit')}</TH>
                <TH className="w-40 text-right">{t('pr.estPrice')}</TH>
                <TH className="w-10">{''}</TH>
              </TR>
            </THead>
            <TBody>
              {lines.map((l, i) => (
                <TR key={i}>
                  <TD className="w-32">
                    <Input
                      aria-label={`${t('pr.itemCode')} ${i + 1}`}
                      value={l.item_code ?? ''}
                      onChange={(e) => setLine(i, { item_code: e.target.value || null })}
                    />
                  </TD>
                  <TD className="min-w-48">
                    <Input
                      aria-label={`${t('quotation.description')} ${i + 1}`}
                      value={l.description}
                      onChange={(e) => setLine(i, { description: e.target.value })}
                    />
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
                    <Input
                      aria-label={`${t('quotation.unit')} ${i + 1}`}
                      value={l.uom}
                      onChange={(e) => setLine(i, { uom: e.target.value })}
                    />
                  </TD>
                  <TD>
                    <Input
                      aria-label={`${t('pr.estPrice')} ${i + 1}`}
                      inputMode="numeric"
                      className="text-right"
                      value={l.est_price}
                      onChange={(e) => setLine(i, { est_price: e.target.value })}
                    />
                  </TD>
                  <TD>
                    <Button
                      size="sm"
                      variant="ghost"
                      aria-label={`${t('quotation.removeLine')} ${i + 1}`}
                      disabled={lines.length === 1}
                      onClick={() => setLines(lines.filter((_, j) => j !== i))}
                    >
                      <Icon name="delete" />
                    </Button>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        </div>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <Button
            variant="secondary"
            onClick={() =>
              setLines([
                ...lines,
                { item_code: null, description: '', qty: '1', uom: 'lot', est_price: '' },
              ])
            }
          >
            <Icon name="add" /> {t('quotation.freeLine')}
          </Button>
          <span className="text-small text-fg-secondary">
            {t('pr.estimatedTotal')}:{' '}
            <span className="font-semibold tabular-nums text-fg">
              {formatIDR(Math.round(total))}
            </span>
          </span>
        </div>
        <Button
          variant="primary"
          className="self-start"
          disabled={!ready || save.isPending}
          onClick={() =>
            save.mutate(
              {
                project_id: v.project,
                wbs_code: v.wbs,
                cost_element_code: v.element,
                need_date: v.need,
                delivery_location: v.location,
                purpose: v.purpose || null,
                lines: lines.map((l) => ({
                  item_code: l.item_code,
                  description: l.description,
                  qty: toApiQty(l.qty),
                  uom: l.uom,
                  est_price: moneyToApi(l.est_price) ?? '0',
                })),
              },
              {
                onSuccess: (r) => {
                  if (pr) onSaved?.();
                  else navigate(`/pengadaan/pr/${r.id}`);
                },
              },
            )
          }
        >
          {pr ? t('master.save') : t('pr.saveDraft')}
        </Button>
      </CardContent>
    </Card>
  );
}
