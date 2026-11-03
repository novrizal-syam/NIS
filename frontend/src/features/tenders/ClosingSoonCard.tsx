import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { StatusPill } from '@/components/ui/status-pill';
import { useClosingSoon } from './api';
import { ClosingIn } from './TendersPage';

/** Dashboard: open tenders closing within 7 days, with missing mandatory documents. */
export function ClosingSoonCard() {
  const { t } = useTranslation();
  const q = useClosingSoon(true);
  if (!q.data) return null;
  return (
    <Card>
      <CardHeader>
        <CardTitle>{t('tender.closingSoonTitle')}</CardTitle>
        <CardDescription>{t('tender.closingSoonHelp')}</CardDescription>
      </CardHeader>
      <CardContent>
        {q.data.length === 0 ? (
          <p className="text-small text-fg-secondary">{t('tender.noneClosing')}</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {q.data.map((r) => (
              <li key={r.id} className="flex flex-wrap items-start justify-between gap-2">
                <span className="min-w-0">
                  <Link
                    to={`/tender/${r.id}`}
                    className="text-small font-semibold text-fg-accent underline"
                  >
                    {r.tender_number ?? r.opportunity_number}
                  </Link>
                  <span className="block text-caption text-fg-secondary">
                    {r.opportunity_title} · {r.company_name}
                  </span>
                </span>
                <span className="flex flex-col items-end gap-1 text-small">
                  <ClosingIn iso={r.closing_at} />
                  {r.missing ? (
                    <StatusPill tone="danger">
                      {t('tender.missingDocs', { count: r.missing })}
                    </StatusPill>
                  ) : (
                    <StatusPill tone="success">{t('tender.docsComplete')}</StatusPill>
                  )}
                </span>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
