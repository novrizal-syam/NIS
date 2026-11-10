import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Input, Select, Textarea } from '@/components/ui/input';
import { StatusPill } from '@/components/ui/status-pill';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { FormError } from '@/features/auth/AuthLayout';
import { useAuth } from '@/features/auth/AuthProvider';
import { ApiError, api, postJson } from '@/lib/api';
import { formatDate } from '@/lib/format';

const errText = (e: unknown, fallback: string) =>
  e instanceof ApiError ? e.message : e ? fallback : null;
const CATS = ['nik', 'salary', 'bank_account', 'tax_id', 'contact', 'health', 'other'];

interface Breach {
  id: string;
  number: string;
  detected_at: string;
  notify_by: string;
  overdue: boolean;
  description: string;
  severity: string;
  status: string;
  subjects_notified_at: string | null;
  authority_notified_at: string | null;
}

export function PdpPage() {
  const { t } = useTranslation();
  const { me } = useAuth();
  const officer = me?.roles.some((r) => r.code === 'director' || r.code === 'super_admin');
  const qc = useQueryClient();
  const [f, setF] = useState({
    detected_at: new Date().toISOString().slice(0, 16),
    description: '',
    severity: 'medium',
  });
  const [cats, setCats] = useState<string[]>([]);
  const report = useMutation({
    mutationFn: () =>
      postJson('/pdp/breaches', {
        ...f,
        detected_at: new Date(f.detected_at).toISOString(),
        data_categories: cats,
      }),
    onSuccess: () => {
      setF({ ...f, description: '' });
      setCats([]);
      void qc.invalidateQueries({ queryKey: ['pdp'] });
    },
  });
  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>{t('pdp.report')}</CardTitle>
          <CardDescription>{t('pdp.reportHint')}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-2">
          <div className="flex flex-wrap gap-2">
            <Field label={t('pdp.detectedAt')} className="w-56">
              <Input
                type="datetime-local"
                value={f.detected_at}
                onChange={(e) => setF({ ...f, detected_at: e.target.value })}
              />
            </Field>
            <Field label={t('pdp.severity')} className="w-40">
              <Select value={f.severity} onChange={(e) => setF({ ...f, severity: e.target.value })}>
                {['low', 'medium', 'high'].map((s) => (
                  <option key={s} value={s}>
                    {t(`pdp.severities.${s}`)}
                  </option>
                ))}
              </Select>
            </Field>
          </div>
          <fieldset className="flex flex-wrap gap-3 text-small">
            <legend className="font-semibold">{t('pdp.categories')}</legend>
            {CATS.map((c) => (
              <label key={c} className="inline-flex items-center gap-1">
                <input
                  type="checkbox"
                  checked={cats.includes(c)}
                  onChange={() =>
                    setCats(cats.includes(c) ? cats.filter((x) => x !== c) : [...cats, c])
                  }
                />
                {t(`pdp.cats.${c}`)}
              </label>
            ))}
          </fieldset>
          <Field label={t('pdp.description')}>
            <Textarea
              value={f.description}
              onChange={(e) => setF({ ...f, description: e.target.value })}
            />
          </Field>
          <FormError message={errText(report.error, t('auth.unexpected'))} />
          {report.isSuccess && (
            <p role="status" className="text-small">
              {t('pdp.reported')}
            </p>
          )}
          <div>
            <Button
              variant="primary"
              disabled={f.description.trim().length < 10 || cats.length === 0}
              onClick={() => report.mutate()}
            >
              {t('pdp.send')}
            </Button>
          </div>
        </CardContent>
      </Card>
      {officer && <Breaches />}
    </div>
  );
}

function Breaches() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const list = useQuery({
    queryKey: ['pdp', 'breaches'],
    queryFn: () => api<Breach[]>('/pdp/breaches'),
  });
  const consents = useQuery({
    queryKey: ['pdp', 'consents'],
    queryFn: () =>
      api<{
        current_version: string;
        users: { email: string; name: string; current: boolean; accepted_at: string | null }[];
      }>('/pdp/consents'),
  });
  const upd = useMutation({
    mutationFn: (v: { id: string; body: Record<string, unknown> }) =>
      api(`/pdp/breaches/${v.id}`, { method: 'PUT', body: JSON.stringify(v.body) }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['pdp'] }),
  });
  const pending = consents.data?.users.filter((u) => !u.current).length ?? 0;
  return (
    <>
      <Card className="overflow-x-auto">
        <CardHeader>
          <CardTitle>{t('pdp.log')}</CardTitle>
          <CardDescription>{t('pdp.logHint')}</CardDescription>
        </CardHeader>
        <CardContent>
          <FormError message={errText(list.error ?? upd.error, t('auth.unexpected'))} />
          <Table>
            <THead>
              <TR>
                <TH>{t('pdp.number')}</TH>
                <TH>{t('pdp.notifyBy')}</TH>
                <TH>{t('pdp.status')}</TH>
                <TH />
              </TR>
            </THead>
            <TBody>
              {list.data?.map((b) => (
                <TR key={b.id}>
                  <TD>
                    {b.number}
                    <div className="max-w-96 truncate text-small text-fg-secondary">
                      {b.description}
                    </div>
                  </TD>
                  <TD>
                    {formatDate(b.notify_by.slice(0, 10))}
                    {b.overdue && (
                      <StatusPill tone="danger" className="ml-1">
                        {t('pdp.overdue')}
                      </StatusPill>
                    )}
                  </TD>
                  <TD>{t(`pdp.statuses.${b.status}`)}</TD>
                  <TD className="flex flex-wrap gap-1">
                    {!b.subjects_notified_at && (
                      <Button
                        size="sm"
                        onClick={() => upd.mutate({ id: b.id, body: { subjects_notified: true } })}
                      >
                        {t('pdp.subjectsNotified')}
                      </Button>
                    )}
                    {!b.authority_notified_at && (
                      <Button
                        size="sm"
                        onClick={() => upd.mutate({ id: b.id, body: { authority_notified: true } })}
                      >
                        {t('pdp.authorityNotified')}
                      </Button>
                    )}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
          {list.data?.length === 0 && (
            <p className="text-small text-fg-secondary">{t('pdp.none')}</p>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>{t('pdp.consents')}</CardTitle>
          <CardDescription>
            {t('pdp.consentsHint', { version: consents.data?.current_version ?? '-', pending })}
          </CardDescription>
        </CardHeader>
      </Card>
    </>
  );
}
