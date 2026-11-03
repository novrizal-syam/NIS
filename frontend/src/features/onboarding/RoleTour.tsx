import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { visibleNav } from '@/app/nav';
import { Button } from '@/components/ui/button';
import { Dialog } from '@/components/ui/dialog';
import { useAuth } from '@/features/auth/AuthProvider';
import { postJson } from '@/lib/api';

/** Short, skippable tour shown once after onboarding, based on what the role can open. */
export function RoleTour() {
  const { t } = useTranslation();
  const { me, can, reload } = useAuth();
  const [step, setStep] = useState(0);
  const [closed, setClosed] = useState(false);
  if (!me || me.tour_done || me.pending.length > 0 || closed) return null;

  const groups = visibleNav(false, (m) => can(m, 'view'))
    .filter((g) => g.key !== 'overview')
    .map((g) => t(`nav.groups.${g.key}`));
  const slides = [
    {
      title: t('tour.welcomeTitle', { name: me.full_name.split(' ')[0] }),
      body: t('tour.welcomeBody', { roles: me.roles.map((r) => r.name).join(', ') }),
    },
    { title: t('tour.menuTitle'), body: t('tour.menuBody', { groups: groups.join(', ') || '–' }) },
    { title: t('tour.approvalsTitle'), body: t('tour.approvalsBody') },
    { title: t('tour.helpTitle'), body: t('tour.helpBody') },
  ];
  const finish = () => {
    setClosed(true);
    void postJson('/auth/tour/done').then(() => reload());
  };
  const last = step === slides.length - 1;

  return (
    <Dialog
      open
      onClose={finish}
      title={slides[step]!.title}
      description={t('tour.progress', { n: step + 1, total: slides.length })}
      footer={
        <>
          <Button variant="ghost" className="mr-auto" onClick={finish}>
            {t('tour.skip')}
          </Button>
          {step > 0 && (
            <Button variant="secondary" onClick={() => setStep(step - 1)}>
              {t('tour.back')}
            </Button>
          )}
          <Button variant="primary" onClick={() => (last ? finish() : setStep(step + 1))}>
            {last ? t('tour.done') : t('tour.next')}
          </Button>
        </>
      }
    >
      <p className="text-body text-fg-body">{slides[step]!.body}</p>
    </Dialog>
  );
}
