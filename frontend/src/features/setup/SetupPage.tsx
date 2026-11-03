import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useState, type FormEvent, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Input, Select, Textarea } from '@/components/ui/input';
import { AuthLayout, FormError } from '@/features/auth/AuthLayout';
import { useAuth } from '@/features/auth/AuthProvider';
import { ApiError, authApi, session, type TotpSetup } from '@/lib/api';
import { cn } from '@/lib/utils';
import { RecoveryCodes } from './RecoveryCodes';
import { setupCall, setupToken, useSetupStatus } from './api';

type Step =
  'token' | 'admin' | 'resume' | 'totp' | 'codes' | 'company' | 'departments' | 'demo' | 'finish';
const ORDER: Step[] = ['admin', 'totp', 'company', 'departments', 'demo', 'finish'];

interface Dept {
  code: string;
  name: string;
}

function useAction() {
  const { t } = useTranslation();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<void>) => {
    setError(null);
    setBusy(true);
    try {
      await fn();
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('auth.unexpected'));
    } finally {
      setBusy(false);
    }
  };
  return { error, busy, run };
}

function Stepper({ current }: { current: Step }) {
  const { t } = useTranslation();
  const idx = ORDER.indexOf(
    current === 'codes' ? 'totp' : current === 'resume' ? 'admin' : current,
  );
  return (
    <ol
      className="mb-6 flex flex-wrap gap-x-3 gap-y-1 text-caption"
      aria-label={t('setup.progress')}
    >
      {ORDER.map((s, i) => (
        <li
          key={s}
          aria-current={i === idx ? 'step' : undefined}
          className={cn(
            'flex items-center gap-1',
            i < idx ? 'text-success' : i === idx ? 'font-bold text-fg' : 'text-fg-muted',
          )}
        >
          {i < idx ? (
            <Icon name="check_circle" className="text-[16px]" />
          ) : (
            <span className="tabular-nums">{i + 1}.</span>
          )}
          {t(`setup.steps.${s}`)}
        </li>
      ))}
    </ol>
  );
}

export function SetupPage() {
  const { t } = useTranslation();
  const status = useSetupStatus();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const { acceptToken } = useAuth();
  const { error, busy, run } = useAction();
  const [step, setStep] = useState<Step>(() => (setupToken.get() ? 'admin' : 'token'));
  const [token, setToken] = useState(setupToken.get());
  const [access, setAccess] = useState<string | null>(null);
  const [admin, setAdmin] = useState({ email: '', full_name: '', password: '', confirm: '' });
  const [resume, setResume] = useState({ email: '', password: '', totp: '' });
  const [totp, setTotp] = useState<TotpSetup | null>(null);
  const [code, setCode] = useState('');
  const [codes, setCodes] = useState<string[]>([]);
  const [company, setCompany] = useState({
    legal_name: 'PT Global Energi KITA',
    npwp: '',
    address: '',
    phone: '',
    email: '',
    fiscal_year_start_month: 1,
  });
  const [depts, setDepts] = useState<Dept[]>([]);

  const steps = status.data?.steps ?? {};
  // Resume after a reload: continue at the first unfinished step.
  useEffect(() => {
    if (step === 'token' || !status.data) return;
    if (step === 'admin' && steps.admin) setStep(access ? 'totp' : 'resume');
  }, [status.data, steps.admin, step, access]);

  const next = (after: Step) => {
    void qc.invalidateQueries({ queryKey: ['setup', 'status'] });
    const done = { ...steps };
    const rest: Step[] = ['totp', 'company', 'departments', 'demo'];
    if (after === 'resume' || after === 'admin') {
      for (const s of rest) if (!done[s as keyof typeof done]) return setStep(s);
      return setStep('finish');
    }
    setStep(after);
  };

  useEffect(() => {
    if (step === 'totp' && !totp) {
      void run(async () => setTotp(await setupCall<TotpSetup>('/totp/setup')));
    }
    if (step === 'company') {
      void setupCall<typeof company & Record<string, unknown>>('/company', 'GET')
        .then((c) => setCompany((cur) => ({ ...cur, ...c })))
        .catch(() => undefined);
    }
    if (step === 'departments' && depts.length === 0) {
      void setupCall<Dept[]>('/departments', 'GET')
        .then(setDepts)
        .catch(() => undefined);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);

  if (status.data?.setup_completed) {
    return (
      <AuthLayout title={t('setup.doneTitle')} subtitle={t('setup.doneHelp')}>
        <Link to="/login" className="text-small font-semibold text-fg-accent underline">
          {t('setup.toLogin')}
        </Link>
      </AuthLayout>
    );
  }

  const form = (onSubmit: () => Promise<void>, children: ReactNode, submit: string) => (
    <form
      noValidate
      className="flex flex-col gap-4"
      onSubmit={(e: FormEvent) => {
        e.preventDefault();
        void run(onSubmit);
      }}
    >
      <FormError message={error} />
      {children}
      <Button type="submit" variant="primary" disabled={busy} className="w-full">
        {submit}
      </Button>
    </form>
  );

  let body: ReactNode;
  switch (step) {
    case 'token':
      body = form(
        async () => {
          setupToken.set(token.trim());
          await setupCall('/verify-token');
          setStep(steps.admin ? 'resume' : 'admin');
        },
        <>
          {status.data && !status.data.token_configured && (
            <FormError message={t('setup.tokenMissing')} />
          )}
          <Field label={t('setup.token')} hint={t('setup.tokenHint')} required>
            <Input value={token} onChange={(e) => setToken(e.target.value)} autoComplete="off" />
          </Field>
        </>,
        t('setup.continue'),
      );
      break;
    case 'admin':
      body = form(
        async () => {
          if (admin.password !== admin.confirm)
            throw new ApiError(422, 'MISMATCH', t('password.mismatch'));
          const out = await setupCall<{ access_token: string }>('/admin', 'POST', {
            email: admin.email,
            full_name: admin.full_name,
            password: admin.password,
          });
          session.setToken(out.access_token);
          setAccess(out.access_token);
          next('totp');
        },
        <>
          <Field label={t('setup.adminName')} required>
            <Input
              value={admin.full_name}
              onChange={(e) => setAdmin({ ...admin, full_name: e.target.value })}
            />
          </Field>
          <Field label={t('login.email')} required>
            <Input
              type="email"
              autoComplete="username"
              value={admin.email}
              onChange={(e) => setAdmin({ ...admin, email: e.target.value })}
            />
          </Field>
          <Field label={t('password.new')} hint={t('setup.strongPolicy')} required>
            <Input
              type="password"
              autoComplete="new-password"
              value={admin.password}
              onChange={(e) => setAdmin({ ...admin, password: e.target.value })}
            />
          </Field>
          <Field label={t('password.confirm')} required>
            <Input
              type="password"
              autoComplete="new-password"
              value={admin.confirm}
              onChange={(e) => setAdmin({ ...admin, confirm: e.target.value })}
            />
          </Field>
        </>,
        t('setup.createAdmin'),
      );
      break;
    case 'resume':
      body = form(
        async () => {
          const out = await authApi.login(resume.email, resume.password, resume.totp || undefined);
          session.setToken(out.access_token);
          setAccess(out.access_token);
          next('resume');
        },
        <>
          <p className="text-small text-fg-secondary">{t('setup.resumeHelp')}</p>
          <Field label={t('login.email')} required>
            <Input
              type="email"
              autoComplete="username"
              value={resume.email}
              onChange={(e) => setResume({ ...resume, email: e.target.value })}
            />
          </Field>
          <Field label={t('login.password')} required>
            <Input
              type="password"
              autoComplete="current-password"
              value={resume.password}
              onChange={(e) => setResume({ ...resume, password: e.target.value })}
            />
          </Field>
          {steps.totp && (
            <Field label={t('login.totp')} required>
              <Input
                inputMode="numeric"
                maxLength={6}
                value={resume.totp}
                onChange={(e) => setResume({ ...resume, totp: e.target.value })}
              />
            </Field>
          )}
        </>,
        t('login.submit'),
      );
      break;
    case 'totp':
      body = form(
        async () => {
          const out = await setupCall<{ recovery_codes: string[] }>('/totp/verify', 'POST', {
            code,
          });
          setCodes(out.recovery_codes);
          setStep('codes');
        },
        <>
          <p className="text-small text-fg-secondary">{t('setup.totpHelp')}</p>
          {totp && (
            <div
              data-theme="light"
              className="flex flex-col items-center gap-2 rounded-card border border-border bg-surface p-4"
            >
              <div
                role="img"
                aria-label={t('totp.qrLabel')}
                dangerouslySetInnerHTML={{ __html: totp.qr_svg }}
              />
              <p className="text-caption text-fg-muted">{t('totp.manual')}</p>
              <code className="break-all text-small font-semibold text-fg">{totp.secret}</code>
            </div>
          )}
          <Field label={t('login.totp')} required>
            <Input
              inputMode="numeric"
              autoComplete="one-time-code"
              maxLength={6}
              value={code}
              onChange={(e) => setCode(e.target.value)}
            />
          </Field>
        </>,
        t('totp.submit'),
      );
      break;
    case 'codes':
      body = <RecoveryCodes codes={codes} onDone={() => next('company')} />;
      break;
    case 'company':
      body = form(
        async () => {
          await setupCall('/company', 'PUT', company);
          next('departments');
        },
        <>
          <Field label={t('setup.legalName')} required>
            <Input
              value={company.legal_name}
              onChange={(e) => setCompany({ ...company, legal_name: e.target.value })}
            />
          </Field>
          <Field label="NPWP">
            <Input
              value={company.npwp}
              onChange={(e) => setCompany({ ...company, npwp: e.target.value })}
            />
          </Field>
          <Field label={t('setup.address')}>
            <Textarea
              rows={2}
              value={company.address}
              onChange={(e) => setCompany({ ...company, address: e.target.value })}
            />
          </Field>
          <div className="grid gap-4 sm:grid-cols-2">
            <Field label={t('setup.phone')}>
              <Input
                value={company.phone}
                onChange={(e) => setCompany({ ...company, phone: e.target.value })}
              />
            </Field>
            <Field label={t('login.email')}>
              <Input
                type="email"
                value={company.email}
                onChange={(e) => setCompany({ ...company, email: e.target.value })}
              />
            </Field>
          </div>
          <Field label={t('setup.fiscalYear')} hint={t('setup.fixedHint')}>
            <Select
              value={company.fiscal_year_start_month}
              onChange={(e) =>
                setCompany({ ...company, fiscal_year_start_month: Number(e.target.value) })
              }
            >
              <option value={1}>{t('setup.janDec')}</option>
            </Select>
          </Field>
          <p className="text-caption text-fg-muted">{t('setup.logoLater')}</p>
        </>,
        t('setup.continue'),
      );
      break;
    case 'departments':
      body = form(
        async () => {
          await setupCall('/departments', 'PUT', {
            departments: depts.filter((d) => d.code && d.name),
          });
          next('demo');
        },
        <>
          <p className="text-small text-fg-secondary">{t('setup.deptHelp')}</p>
          <ul className="flex flex-col gap-2">
            {depts.map((d, i) => (
              <li key={i} className="grid grid-cols-[6rem_minmax(0,1fr)_auto] items-end gap-2">
                <Field label={t('setup.deptCode')}>
                  <Input
                    value={d.code}
                    maxLength={10}
                    onChange={(e) =>
                      setDepts(
                        depts.map((x, j) =>
                          j === i ? { ...x, code: e.target.value.toUpperCase() } : x,
                        ),
                      )
                    }
                  />
                </Field>
                <Field label={t('setup.deptName')}>
                  <Input
                    value={d.name}
                    onChange={(e) =>
                      setDepts(depts.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))
                    }
                  />
                </Field>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={t('setup.removeDept', { code: d.code })}
                  onClick={() => setDepts(depts.filter((_, j) => j !== i))}
                >
                  <Icon name="delete" />
                </Button>
              </li>
            ))}
          </ul>
          <Button
            variant="ghost"
            size="sm"
            className="self-start"
            onClick={() => setDepts([...depts, { code: '', name: '' }])}
          >
            <Icon name="add" /> {t('setup.addDept')}
          </Button>
        </>,
        t('setup.continue'),
      );
      break;
    case 'demo':
      body = (
        <div className="flex flex-col gap-3">
          <FormError message={error} />
          <p className="text-small text-fg-secondary">{t('setup.demoHelp')}</p>
          <Button
            variant="secondary"
            disabled={busy}
            onClick={() =>
              void run(async () => {
                await setupCall('/demo', 'POST', { load_demo: true });
                next('finish');
              })
            }
          >
            <Icon name="dataset" /> {t('setup.loadDemo')}
          </Button>
          <Button
            variant="secondary"
            disabled={busy}
            onClick={() =>
              void run(async () => {
                await setupCall('/demo', 'POST', { load_demo: false });
                next('finish');
              })
            }
          >
            <Icon name="check_box_outline_blank" /> {t('setup.startEmpty')}
          </Button>
        </div>
      );
      break;
    case 'finish':
      body = (
        <div className="flex flex-col gap-3">
          <FormError message={error} />
          <p className="text-body text-fg-body">{t('setup.finishHelp')}</p>
          <Button
            variant="primary"
            disabled={busy}
            onClick={() =>
              void run(async () => {
                await setupCall('/finish');
                setupToken.set('');
                await qc.invalidateQueries({ queryKey: ['setup', 'status'] });
                if (access) await acceptToken(access);
                navigate('/', { replace: true });
              })
            }
          >
            {t('setup.finish')}
          </Button>
        </div>
      );
      break;
  }

  return (
    <AuthLayout title={t(`setup.titles.${step}`)} subtitle={t('setup.subtitle')}>
      {step !== 'token' && <Stepper current={step} />}
      {body}
    </AuthLayout>
  );
}
