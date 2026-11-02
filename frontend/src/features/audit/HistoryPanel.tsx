import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Pagination } from '@/components/ui/pagination';
import { StatusPill } from '@/components/ui/status-pill';
import { formatDateTime } from '@/lib/format';
import { useHistory } from './api';
import { Changes } from './Changes';

/** "Riwayat": who changed what and when on one record. Reusable on any document. */
export function HistoryPanel({
  entityType,
  entityId,
  labels,
}: {
  entityType: string;
  entityId: string;
  labels?: Record<string, string>;
}) {
  const { t } = useTranslation();
  const [page, setPage] = useState(1);
  const history = useHistory(entityType, entityId, page);
  const items = history.data?.items ?? [];

  if (history.isLoading)
    return <p className="text-small text-fg-secondary">{t('common.loading')}</p>;
  if (items.length === 0)
    return <p className="text-small text-fg-secondary">{t('audit.noHistory')}</p>;
  return (
    <div className="flex flex-col">
      <ol className="flex flex-col gap-3">
        {items.map((e) => (
          <li key={e.id} className="border-b border-border pb-3 last:border-0">
            <div className="flex flex-wrap items-center gap-2 text-small">
              <StatusPill
                tone={e.action === 'delete' || e.action === 'reject' ? 'danger' : 'neutral'}
              >
                {e.action_label}
              </StatusPill>
              <span className="font-semibold text-fg">{e.actor_name ?? t('audit.system')}</span>
              <span className="text-fg-muted">{formatDateTime(e.at)}</span>
            </div>
            <Changes entry={e} labels={labels} />
            {e.note && <p className="mt-1 text-small text-fg-secondary">{e.note}</p>}
          </li>
        ))}
      </ol>
      {(history.data?.total ?? 0) > 10 && (
        <Pagination page={page} pageSize={10} total={history.data?.total ?? 0} onPage={setPage} />
      )}
    </div>
  );
}
