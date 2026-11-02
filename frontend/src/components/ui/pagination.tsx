import { useTranslation } from 'react-i18next';
import { formatNumber } from '@/lib/format';
import { Button } from './button';
import { Icon } from './icon';

export function Pagination({
  page,
  pageSize,
  total,
  onPage,
}: {
  page: number;
  pageSize: number;
  total: number;
  onPage: (page: number) => void;
}) {
  const { t } = useTranslation();
  const pages = Math.max(1, Math.ceil(total / pageSize));
  const from = total === 0 ? 0 : (page - 1) * pageSize + 1;
  const to = Math.min(total, page * pageSize);
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-border px-3 py-2 text-small text-fg-secondary">
      <span>
        {t('list.showing', {
          from: formatNumber(from),
          to: formatNumber(to),
          total: formatNumber(total),
        })}
      </span>
      <div className="flex items-center gap-1">
        <Button
          variant="ghost"
          size="sm"
          aria-label={t('list.prev')}
          disabled={page <= 1}
          onClick={() => onPage(page - 1)}
        >
          <Icon name="chevron_left" />
        </Button>
        <span className="tabular-nums">
          {page} / {pages}
        </span>
        <Button
          variant="ghost"
          size="sm"
          aria-label={t('list.next')}
          disabled={page >= pages}
          onClick={() => onPage(page + 1)}
        >
          <Icon name="chevron_right" />
        </Button>
      </div>
    </div>
  );
}
