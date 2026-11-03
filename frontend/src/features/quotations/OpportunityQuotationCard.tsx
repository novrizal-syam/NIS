import { useTranslation } from 'react-i18next';
import { Link, useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { FormError } from '@/features/auth/AuthLayout';
import { useAuth } from '@/features/auth/AuthProvider';
import { ApiError } from '@/lib/api';
import { formatIDR } from '@/lib/format';
import { useCreateQuotation, useQuotations } from './api';
import { MarginPill, QuotationStatusPill } from './QuotationPills';

/** On the opportunity page: the quotation (latest revision) or a button to start one. */
export function OpportunityQuotationCard({
  opportunityId,
  stage,
  canCreate,
}: {
  opportunityId: string;
  stage: string;
  canCreate: boolean;
}) {
  const { t } = useTranslation();
  const { can } = useAuth();
  const navigate = useNavigate();
  const list = useQuotations({ opportunity_id: opportunityId }, can('quotation', 'view'));
  const create = useCreateQuotation();
  if (!can('quotation', 'view')) return null;
  const q = list.data?.items[0];
  if (!q && stage !== 'quotation') return null;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('quotation.title')}</CardTitle>
        {!q && <CardDescription>{t('quotation.startHelp')}</CardDescription>}
      </CardHeader>
      <CardContent className="flex flex-col gap-2">
        <FormError message={create.error instanceof ApiError ? create.error.message : null} />
        {q ? (
          <div className="flex flex-wrap items-center gap-2 text-small">
            <Link to={`/penawaran/${q.id}`} className="font-semibold text-fg-accent underline">
              {q.label}
            </Link>
            <QuotationStatusPill status={q.status} />
            <span className="tabular-nums text-fg">{formatIDR(q.total_price)}</span>
            <MarginPill pct={q.margin_pct} warning={q.margin_warning} />
          </div>
        ) : (
          canCreate &&
          can('quotation', 'create') && (
            <Button
              variant="primary"
              className="self-start"
              disabled={create.isPending}
              onClick={() =>
                create.mutate(opportunityId, { onSuccess: (r) => navigate(`/penawaran/${r.id}`) })
              }
            >
              {t('quotation.create')}
            </Button>
          )
        )}
      </CardContent>
    </Card>
  );
}
