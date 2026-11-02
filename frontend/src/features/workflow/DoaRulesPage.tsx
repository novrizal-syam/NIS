import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Dialog } from '@/components/ui/dialog';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input, Select, Textarea } from '@/components/ui/input';
import { StatusPill } from '@/components/ui/status-pill';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { FormError } from '@/features/auth/AuthLayout';
import { useAuth } from '@/features/auth/AuthProvider';
import { ApiError } from '@/lib/api';
import { formatDateTime } from '@/lib/format';
import { useProposeRuleChange, useRuleChanges, useRules, type Rule, type RuleStep } from './api';

// Role codes are shown with names from the rules themselves; editing uses a code list.
const ROLE_OPTIONS = [
  'director',
  'shareholders',
  'head_of_sales',
  'head_of_operation',
  'head_of_finance',
  'lead_controller',
  'ofs_superintendent',
  'epcom_superintendent',
  'qhse_coordinator',
  'warehouse_head',
  'cashier',
];

type Leaf = { field: string; op: string; value: unknown };

/** Flat AND conditions can be edited as rows; nested ones are shown read-only. */
function flatLeaves(cond: Record<string, unknown>): Leaf[] | null {
  if (!cond || Object.keys(cond).length === 0) return [];
  if ('field' in cond) return [cond as Leaf];
  if (
    Array.isArray(cond.all) &&
    cond.all.every((c) => c && typeof c === 'object' && 'field' in c)
  ) {
    return cond.all as Leaf[];
  }
  return null;
}

function EditRuleDialog({ rule, onClose }: { rule: Rule; onClose: () => void }) {
  const { t } = useTranslation();
  const propose = useProposeRuleChange();
  const [name, setName] = useState(rule.name);
  const [hours, setHours] = useState(String(rule.escalation_hours));
  const [active, setActive] = useState(rule.is_active);
  const [steps, setSteps] = useState<RuleStep[]>(rule.steps);
  const leaves = useMemo(() => flatLeaves(rule.condition), [rule.condition]);
  const [values, setValues] = useState<string[]>(leaves?.map((l) => String(l.value)) ?? []);
  const [reason, setReason] = useState('');
  const [done, setDone] = useState<string | null>(null);

  const condition = () => {
    if (!leaves) return rule.condition;
    const rows = leaves.map((l, i) => {
      const raw = values[i] ?? '';
      const num = Number(raw.replace(/\./g, ''));
      return { ...l, value: raw !== '' && !Number.isNaN(num) ? num : raw };
    });
    if (rows.length === 0) return {};
    return rows.length === 1 ? rows[0]! : { all: rows };
  };

  const submit = async () => {
    const out = await propose.mutateAsync({
      rule_id: rule.id,
      reason,
      rule: {
        doc_type: rule.doc_type,
        name,
        priority: rule.priority,
        condition: condition() as Record<string, unknown>,
        escalation_hours: Number(hours),
        escalate_to_role: rule.escalate_to_role,
        is_active: active,
        note: rule.note,
        steps,
      },
    });
    setDone(out.doc_number);
  };

  return (
    <Dialog
      open
      onClose={onClose}
      title={t('doa.editTitle', { name: rule.doc_type_label })}
      description={t('doa.editHelp')}
      className="max-w-2xl"
      footer={
        done ? (
          <Button variant="secondary" onClick={onClose}>
            {t('common.close')}
          </Button>
        ) : (
          <>
            <Button variant="ghost" onClick={onClose}>
              {t('common.cancel')}
            </Button>
            <Button
              variant="primary"
              disabled={propose.isPending || reason.trim().length < 5}
              onClick={() => void submit().catch(() => undefined)}
            >
              {t('doa.submitChange')}
            </Button>
          </>
        )
      }
    >
      {done ? (
        <p
          role="status"
          className="rounded-control bg-success-tint px-3 py-2 text-small font-medium text-success"
        >
          {t('doa.submitted', { number: done })}
        </p>
      ) : (
        <div className="flex flex-col gap-4">
          <FormError message={propose.error instanceof ApiError ? propose.error.message : null} />
          <Field label={t('doa.name')} required>
            <Input value={name} onChange={(e) => setName(e.target.value)} />
          </Field>
          {leaves === null ? (
            <p className="text-small text-fg-secondary">
              {t('doa.condition')}:{' '}
              <span className="font-semibold text-fg">{rule.condition_text}</span> (
              {t('doa.nestedReadOnly')})
            </p>
          ) : (
            leaves.map((l, i) => (
              <Field key={i} label={`${t('doa.condition')}: ${l.field} ${l.op}`}>
                <Input
                  value={values[i] ?? ''}
                  inputMode="numeric"
                  onChange={(e) =>
                    setValues((v) => v.map((x, j) => (j === i ? e.target.value : x)))
                  }
                />
              </Field>
            ))
          )}
          <fieldset className="flex flex-col gap-2">
            <legend className="mb-1 text-small font-semibold text-fg">{t('doa.steps')}</legend>
            {steps.map((s, i) => (
              <div key={i} className="grid grid-cols-[4rem_minmax(0,1fr)_auto] items-end gap-2">
                <Field label={t('doa.seq')}>
                  <Input
                    type="number"
                    min={1}
                    value={s.seq}
                    onChange={(e) =>
                      setSteps((all) =>
                        all.map((x, j) => (j === i ? { ...x, seq: Number(e.target.value) } : x)),
                      )
                    }
                  />
                </Field>
                <Field label={t('doa.approver')}>
                  <Select
                    value={s.approver_role}
                    onChange={(e) =>
                      setSteps((all) =>
                        all.map((x, j) => (j === i ? { ...x, approver_role: e.target.value } : x)),
                      )
                    }
                  >
                    {[...new Set([s.approver_role, ...ROLE_OPTIONS])].map((r) => (
                      <option key={r} value={r}>
                        {t(`roles.${r}`, { defaultValue: r })}
                      </option>
                    ))}
                  </Select>
                </Field>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={t('doa.removeStep')}
                  disabled={steps.length === 1}
                  onClick={() => setSteps((all) => all.filter((_, j) => j !== i))}
                >
                  <Icon name="delete" />
                </Button>
              </div>
            ))}
            <Button
              variant="ghost"
              size="sm"
              className="self-start"
              onClick={() =>
                setSteps((all) => [
                  ...all,
                  {
                    seq: Math.max(...all.map((x) => x.seq)) + 1,
                    approver_role: 'director',
                    label: '',
                    approver_scope: 'all',
                  },
                ])
              }
            >
              <Icon name="add" /> {t('doa.addStep')}
            </Button>
          </fieldset>
          <div className="grid gap-3 sm:grid-cols-2">
            <Field label={t('doa.escalationHours')}>
              <Input
                type="number"
                min={1}
                value={hours}
                onChange={(e) => setHours(e.target.value)}
              />
            </Field>
            <label className="flex items-center gap-2 self-end pb-2 text-small font-semibold text-fg">
              <input
                type="checkbox"
                checked={active}
                onChange={(e) => setActive(e.target.checked)}
                className="h-4 w-4 accent-[rgb(var(--brand-ink))]"
              />
              {t('doa.active')}
            </label>
          </div>
          <Field label={t('doa.reason')} hint={t('doa.reasonHint')} required>
            <Textarea value={reason} onChange={(e) => setReason(e.target.value)} rows={2} />
          </Field>
        </div>
      )}
    </Dialog>
  );
}

export function DoaRulesPage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  const rules = useRules();
  const changes = useRuleChanges();
  const [editing, setEditing] = useState<Rule | null>(null);
  const canEdit = can('workflow', 'admin');
  const pendingChanges = (changes.data ?? []).filter((c) => c.status === 'pending');

  return (
    <div className="flex flex-col gap-4">
      <p className="text-body text-fg-secondary">{t('doa.intro')}</p>
      {pendingChanges.length > 0 && (
        <Card className="p-4">
          <p className="eyebrow mb-2">{t('doa.pendingChanges')}</p>
          <ul className="flex flex-col gap-1 text-small">
            {pendingChanges.map((c) => (
              <li key={c.id}>
                <Link
                  to={`/persetujuan/${c.request_id}`}
                  className="font-semibold text-fg-accent underline"
                >
                  {c.name}
                </Link>{' '}
                · {c.reason} · {formatDateTime(c.created_at)}
              </li>
            ))}
          </ul>
        </Card>
      )}
      <Card>
        <Table>
          <caption className="sr-only">{t('doa.tableCaption')}</caption>
          <THead>
            <TR>
              <TH>{t('doa.docType')}</TH>
              <TH>{t('doa.condition')}</TH>
              <TH>{t('doa.steps')}</TH>
              <TH numeric>{t('doa.escalationHours')}</TH>
              <TH>{t('workflow.col.status')}</TH>
              <TH />
            </TR>
          </THead>
          <TBody>
            {rules.data?.map((r) => (
              <TR key={r.id}>
                <TD className="whitespace-nowrap font-semibold text-fg">{r.doc_type_label}</TD>
                <TD className="min-w-48">
                  {r.name}
                  <span className="block text-caption text-fg-muted">{r.condition_text}</span>
                </TD>
                <TD className="min-w-48">
                  {r.steps
                    .map(
                      (s) =>
                        `${s.seq}. ${t(`roles.${s.approver_role}`, { defaultValue: s.approver_role })}${s.label ? ` (${s.label})` : ''}`,
                    )
                    .join(' → ')}
                </TD>
                <TD numeric>{r.escalation_hours}</TD>
                <TD>
                  {r.pending_change ? (
                    <StatusPill tone="warning">{t('doa.changePending')}</StatusPill>
                  ) : (
                    <StatusPill tone={r.is_active ? 'success' : 'neutral'}>
                      {r.is_active ? t('doa.active') : t('doa.inactive')}
                    </StatusPill>
                  )}
                </TD>
                <TD className="text-right">
                  {canEdit && (
                    <Button
                      size="sm"
                      variant="secondary"
                      disabled={r.pending_change}
                      onClick={() => setEditing(r)}
                    >
                      {t('common.edit')}
                    </Button>
                  )}
                </TD>
              </TR>
            ))}
          </TBody>
        </Table>
      </Card>
      {editing && <EditRuleDialog rule={editing} onClose={() => setEditing(null)} />}
    </div>
  );
}
