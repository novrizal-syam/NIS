import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { StatusPill } from '@/components/ui/status-pill';
import { FormError } from '@/features/auth/AuthLayout';
import { useAuth } from '@/features/auth/AuthProvider';
import { ApiError, api, downloadFile } from '@/lib/api';
import { formatDate, formatIDR } from '@/lib/format';

const errText = (e: unknown, fallback: string) =>
  e instanceof ApiError ? e.message : e ? fallback : null;

interface CheckItem {
  key: string;
  label: string;
  ok: boolean | null;
  detail: string;
  link: string | null;
}

interface Checklist {
  ready: boolean;
  done: number;
  total: number;
  items: CheckItem[];
}

interface OpeningResult {
  gl_lines: number;
  ar_items: number;
  ap_items: number;
  stock_rows: number;
  assets: number;
  total: string;
  journal: string | null;
  dry_run: boolean;
}

/** Go-live (10f): readiness checklist and the opening-balance wizard. */
export function GoLivePage() {
  const { t } = useTranslation();
  const { can } = useAuth();
  return (
    <div className="flex flex-col gap-4">
      <ChecklistCard />
      {can('finance', 'approve') ? (
        <OpeningWizard />
      ) : (
        <Card>
          <CardHeader>
            <CardTitle>{t('golive.opening')}</CardTitle>
            <CardDescription>{t('golive.openingByFinance')}</CardDescription>
          </CardHeader>
        </Card>
      )}
    </div>
  );
}

function ChecklistCard() {
  const { t } = useTranslation();
  const q = useQuery({
    queryKey: ['go-live', 'checklist'],
    queryFn: () => api<Checklist>('/go-live/checklist'),
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('golive.checklist')}</CardTitle>
        <CardDescription>{t('golive.checklistHint')}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <FormError message={errText(q.error, t('auth.unexpected'))} />
        {q.data && (
          <>
            <p role="status" className="text-small font-semibold">
              {q.data.ready
                ? t('golive.ready')
                : t('golive.progress', { done: q.data.done, total: q.data.total })}
            </p>
            <ul className="flex flex-col divide-y divide-border">
              {q.data.items.map((i) => (
                <li key={i.key} className="flex flex-wrap items-center gap-2 py-2">
                  <StatusPill tone={i.ok === null ? 'info' : i.ok ? 'success' : 'warning'}>
                    {t(i.ok === null ? 'golive.manual' : i.ok ? 'golive.ok' : 'golive.todo')}
                  </StatusPill>
                  <span className="font-semibold">{i.label}</span>
                  <span className="text-small text-fg-secondary">{i.detail}</span>
                  {i.link && !i.ok && (
                    <Link to={i.link} className="text-small underline">
                      {t('golive.open')}
                    </Link>
                  )}
                </li>
              ))}
            </ul>
          </>
        )}
      </CardContent>
    </Card>
  );
}

export function OpeningWizard() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const status = useQuery({
    queryKey: ['ledger', 'opening'],
    queryFn: () => api<{ opening_date: string | null }>('/ledger/opening'),
  });
  const [asOf, setAsOf] = useState('');
  const [file, setFile] = useState<File | null>(null);
  const send = useMutation({
    mutationFn: (dryRun: boolean) => {
      const form = new FormData();
      form.append('file', file as File);
      form.append('as_of', asOf);
      form.append('dry_run', String(dryRun));
      return api<OpeningResult>('/ledger/opening', { method: 'POST', body: form });
    },
    onSuccess: (r) => {
      if (!r.dry_run) void qc.invalidateQueries({ queryKey: ['ledger'] });
      void qc.invalidateQueries({ queryKey: ['go-live'] });
    },
  });
  const template = useMutation({
    mutationFn: () => downloadFile('/ledger/opening/template', 'saldo-awal.xlsx'),
  });
  const errors =
    send.error instanceof ApiError
      ? (send.error.details as { errors?: string[] } | undefined)?.errors
      : undefined;
  const preview = send.data?.dry_run ? send.data : null;
  const posted = send.data && !send.data.dry_run ? send.data : null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('golive.opening')}</CardTitle>
        <CardDescription>{t('golive.openingHint')}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {status.data?.opening_date && !posted ? (
          <p role="status" className="text-small text-success">
            {t('ledger.openingDone', { date: formatDate(status.data.opening_date) })}
          </p>
        ) : (
          <ol className="flex flex-col gap-4">
            <li className="flex flex-col gap-2">
              <h3 className="font-semibold">{t('golive.step1')}</h3>
              <div className="flex flex-wrap items-end gap-2">
                <Field label={t('ledger.goLive')} className="w-44">
                  <Input
                    type="date"
                    value={asOf}
                    onChange={(e) => {
                      setAsOf(e.target.value);
                      send.reset();
                    }}
                  />
                </Field>
                <Button onClick={() => template.mutate()} disabled={template.isPending}>
                  {t('golive.template')}
                </Button>
              </div>
              <FormError message={errText(template.error, t('auth.unexpected'))} />
            </li>
            <li className="flex flex-col gap-2">
              <h3 className="font-semibold">{t('golive.step2')}</h3>
              <div className="flex flex-wrap items-center gap-2">
                <input
                  type="file"
                  accept=".xlsx"
                  aria-label={t('ledger.openingFile')}
                  onChange={(e) => {
                    setFile(e.target.files?.[0] ?? null);
                    send.reset();
                  }}
                />
                <Button
                  disabled={!file || !asOf || send.isPending}
                  onClick={() => send.mutate(true)}
                >
                  {t('golive.check')}
                </Button>
              </div>
              <FormError message={errText(send.error, t('auth.unexpected'))} />
              {errors && (
                <ul className="list-disc pl-6 text-small text-danger">
                  {errors.slice(0, 50).map((x) => (
                    <li key={x}>{x}</li>
                  ))}
                </ul>
              )}
            </li>
            <li className="flex flex-col gap-2">
              <h3 className="font-semibold">{t('golive.step3')}</h3>
              {preview && (
                <>
                  <p role="status" className="text-small">
                    {t('golive.preview', {
                      total: formatIDR(preview.total),
                      gl: preview.gl_lines,
                      ar: preview.ar_items,
                      ap: preview.ap_items,
                      stock: preview.stock_rows,
                      assets: preview.assets,
                      date: formatDate(asOf),
                    })}
                  </p>
                  <div>
                    <Button
                      variant="primary"
                      disabled={send.isPending}
                      onClick={() => send.mutate(false)}
                    >
                      {t('golive.post')}
                    </Button>
                  </div>
                </>
              )}
              {!preview && !posted && (
                <p className="text-small text-fg-secondary">{t('golive.step3Hint')}</p>
              )}
            </li>
          </ol>
        )}
        {posted && (
          <p role="status" className="text-small text-success">
            {t('ledger.openingPosted', { ...posted })}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
