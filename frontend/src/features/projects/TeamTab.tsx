import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Field } from '@/components/ui/field';
import { Icon } from '@/components/ui/icon';
import { Select } from '@/components/ui/input';
import { FormError } from '@/features/auth/AuthLayout';
import { ApiError } from '@/lib/api';
import { useAddMember, useRemoveMember, useTeam, useTeamCandidates } from './api';

/** Project team: members get the project in their project-scoped rights (MR, DOR). */
export function TeamTab({ projectId }: { projectId: string }) {
  const { t } = useTranslation();
  const team = useTeam(projectId);
  const canEdit = team.data?.can_edit ?? false;
  const candidates = useTeamCandidates(canEdit);
  const add = useAddMember(projectId);
  const remove = useRemoveMember(projectId);
  const [pick, setPick] = useState('');
  const members = team.data?.items ?? [];
  const taken = new Set(members.map((m) => m.user_id));
  const err = add.error ?? remove.error;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('project.team')}</CardTitle>
        <CardDescription>{t('project.teamHelp')}</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <FormError message={err instanceof ApiError ? err.message : null} />
        {members.length === 0 && (
          <p className="text-small text-fg-secondary">{t('project.noTeam')}</p>
        )}
        <ul className="flex flex-col divide-y divide-border">
          {members.map((m) => (
            <li key={m.user_id} className="flex items-center justify-between gap-2 py-2">
              <span className="text-small">
                <span className="font-semibold text-fg">{m.full_name}</span>
                <span className="block text-caption text-fg-muted">{m.email}</span>
              </span>
              {canEdit && (
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={t('project.removeMember', { name: m.full_name })}
                  onClick={() => remove.mutate(m.user_id)}
                >
                  <Icon name="person_remove" />
                </Button>
              )}
            </li>
          ))}
        </ul>
        {canEdit && (
          <div className="flex flex-wrap items-end gap-2">
            <Field label={t('project.addMember')} className="min-w-0 flex-1">
              <Select value={pick} onChange={(e) => setPick(e.target.value)}>
                <option value="">{t('master.choose')}</option>
                {candidates.data
                  ?.filter((c) => !taken.has(c.id))
                  .map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.full_name}
                    </option>
                  ))}
              </Select>
            </Field>
            <Button
              variant="secondary"
              disabled={!pick || add.isPending}
              onClick={() => add.mutate(pick, { onSuccess: () => setPick('') })}
            >
              <Icon name="person_add" /> {t('project.add')}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
