import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Input } from '@/components/ui/input';
import { StatusPill } from '@/components/ui/status-pill';
import { TBody, TD, TH, THead, TR, Table } from '@/components/ui/table';
import { FormError } from '@/features/auth/AuthLayout';
import { ApiError, api, postJson } from '@/lib/api';

const errText = (e: unknown, fallback: string) =>
  e instanceof ApiError ? e.message : e ? fallback : null;

interface Status {
  integrations: {
    key: string;
    label: string;
    mode: 'live' | 'manual' | 'file';
    detail: string;
    config: string;
  }[];
  settings: {
    'psre.provider': string;
    'emeterai.provider': string;
    'whatsapp.notify_kinds': string[];
  };
}
interface Msg {
  id: string;
  to: string;
  body: string;
  kind: string | null;
  status: string;
  error: string | null;
  wa_link: string | null;
}

export function IntegrationsPage() {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const status = useQuery({
    queryKey: ['integrations'],
    queryFn: () => api<Status>('/integrations'),
  });
  const box = useQuery({
    queryKey: ['integrations', 'wa'],
    queryFn: () => api<Msg[]>('/integrations/whatsapp/outbox'),
  });
  const [kinds, setKinds] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () =>
      api('/integrations/settings', {
        method: 'PUT',
        body: JSON.stringify({
          psre_provider: status.data?.settings['psre.provider'] ?? 'internal',
          emeterai_provider: status.data?.settings['emeterai.provider'] ?? 'internal',
          whatsapp_notify_kinds: (kinds ?? '')
            .split(',')
            .map((x) => x.trim())
            .filter(Boolean),
        }),
      }),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['integrations'] }),
  });
  const sent = useMutation({
    mutationFn: (id: string) => postJson(`/integrations/whatsapp/${id}/sent`),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ['integrations'] }),
  });
  const currentKinds = kinds ?? status.data?.settings['whatsapp.notify_kinds'].join(', ') ?? '';
  return (
    <div className="flex flex-col gap-4">
      <Card className="overflow-x-auto">
        <CardHeader>
          <CardTitle>{t('integrations.title')}</CardTitle>
          <CardDescription>{t('integrations.hint')}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-3">
          <FormError message={errText(status.error ?? save.error, t('auth.unexpected'))} />
          <Table>
            <THead>
              <TR>
                <TH>{t('integrations.name')}</TH>
                <TH>{t('integrations.mode')}</TH>
                <TH>{t('integrations.detail')}</TH>
                <TH>{t('integrations.config')}</TH>
              </TR>
            </THead>
            <TBody>
              {status.data?.integrations.map((i) => (
                <TR key={i.key}>
                  <TD className="font-semibold">{i.label}</TD>
                  <TD>
                    <StatusPill tone={i.mode === 'live' ? 'success' : 'neutral'}>
                      {t(`integrations.modes.${i.mode}`)}
                    </StatusPill>
                  </TD>
                  <TD>{i.detail}</TD>
                  <TD className="text-small text-fg-secondary">{i.config}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
          <div className="flex flex-wrap items-end gap-2">
            <Field
              label={t('integrations.waKinds')}
              hint={t('integrations.waKindsHint')}
              className="w-96"
            >
              <Input value={currentKinds} onChange={(e) => setKinds(e.target.value)} />
            </Field>
            <Button variant="primary" onClick={() => save.mutate()}>
              {t('integrations.save')}
            </Button>
          </div>
          <p className="text-small text-fg-secondary">{t('integrations.apiDocs')}</p>
        </CardContent>
      </Card>
      <Card className="overflow-x-auto">
        <CardHeader>
          <CardTitle>{t('integrations.outbox')}</CardTitle>
          <CardDescription>{t('integrations.outboxHint')}</CardDescription>
        </CardHeader>
        <CardContent>
          <Table>
            <TBody>
              {box.data?.map((m) => (
                <TR key={m.id}>
                  <TD>{m.to}</TD>
                  <TD className="max-w-96 truncate">{m.body}</TD>
                  <TD>
                    <StatusPill
                      tone={
                        m.status === 'sent'
                          ? 'success'
                          : m.status === 'failed'
                            ? 'danger'
                            : 'warning'
                      }
                    >
                      {t(`integrations.msg.${m.status}`)}
                    </StatusPill>
                  </TD>
                  <TD className="flex gap-1">
                    {m.wa_link && (
                      <a
                        className="text-fg-accent underline"
                        href={m.wa_link}
                        target="_blank"
                        rel="noreferrer"
                      >
                        {t('integrations.openWa')}
                      </a>
                    )}
                    {['manual', 'failed'].includes(m.status) && (
                      <Button size="sm" onClick={() => sent.mutate(m.id)}>
                        {t('integrations.markSent')}
                      </Button>
                    )}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
          {box.data?.length === 0 && (
            <p className="text-small text-fg-secondary">{t('integrations.empty')}</p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
