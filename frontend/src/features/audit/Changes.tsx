import { useTranslation } from 'react-i18next';
import type { AuditEntry } from './api';

const show = (v: unknown): string => {
  if (v === null || v === undefined || v === '') return '–';
  if (typeof v === 'boolean') return v ? 'Ya' : 'Tidak';
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
};

/** Before → after for the changed fields of one audit entry. */
const HIDDEN = new Set(['is_demo']);

export function Changes({
  entry,
  labels = {},
}: {
  entry: AuditEntry;
  /** field name -> label (e.g. from the form metadata) */
  labels?: Record<string, string>;
}) {
  const { t } = useTranslation();
  const keys = (entry.changed ?? Object.keys(entry.after ?? entry.before ?? {})).filter(
    (k) => !HIDDEN.has(k),
  );
  if (keys.length === 0) return null;
  return (
    <dl className="mt-1 grid gap-x-3 gap-y-0.5 text-small sm:grid-cols-[max-content_minmax(0,1fr)]">
      {keys.map((k) => (
        <div key={k} className="contents">
          <dt className="font-semibold text-fg-secondary">{labels[k] ?? k}</dt>
          <dd className="min-w-0 break-words text-fg-body">
            {entry.before && k in entry.before && (
              <>
                <span className="text-fg-muted line-through">{show(entry.before[k])}</span>
                <span aria-label={t('audit.becomes')}> → </span>
              </>
            )}
            <span>{show(entry.after?.[k])}</span>
          </dd>
        </div>
      ))}
    </dl>
  );
}
