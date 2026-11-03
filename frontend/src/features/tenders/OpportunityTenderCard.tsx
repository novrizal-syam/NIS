import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { FormError } from '@/features/auth/AuthLayout';
import { useAuth } from '@/features/auth/AuthProvider';
import { ApiError } from '@/lib/api';
import { useCreateTender, useTenders } from './api';
import { ClosingIn } from './TendersPage';
import { PackagePill, ResultPill } from './TenderPills';

/** On a tender opportunity: its tender data, or a button to start it. */
export function OpportunityTenderCard({
  opportunityId,
  open,
}: {
  opportunityId: string;
  open: boolean;
}) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const navigate = useNavigate();
  const visible = can('tender', 'view');
  const list = useTenders({ opportunity_id: opportunityId }, visible);
  const create = useCreateTender();
  if (!visible) return null;
  const tender = list.data?.items[0];
  if (!tender && !open) return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('tender.title')}</CardTitle>
        {!tender && <CardDescription>{t('tender.startHelp')}</CardDescription>}
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <FormError message={create.error instanceof ApiError ? create.error.message : null} />
        {tender ? (
          <div className="flex flex-wrap items-center gap-3 text-small">
            <Link to={`/tender/${tender.id}`} className="font-semibold text-fg-accent underline">
              {tender.tender_number ?? t('tender.openTender')}
            </Link>
            <PackagePill status={tender.package_status} />
            {tender.result && <ResultPill result={tender.result} />}
            <ClosingIn iso={tender.closing_at} />
          </div>
        ) : (
          can('tender', 'create') && (
            <Button
              variant="primary"
              className="self-start"
              disabled={create.isPending}
              onClick={() =>
                create.mutate(opportunityId, { onSuccess: (r) => navigate(`/tender/${r.id}`) })
              }
            >
              {t('tender.create')}
            </Button>
          )
        )}
      </CardContent>
    </Card>
  );
}
