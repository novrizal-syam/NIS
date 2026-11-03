import { useTranslation } from 'react-i18next';
import { StatusPill, type StatusTone } from '@/components/ui/status-pill';
import type { PackageStatus, TenderDoc, TenderResult } from './api';

const PKG: Record<PackageStatus, StatusTone> = {
  none: 'neutral',
  pending: 'warning',
  approved: 'success',
  rejected: 'danger',
};
const DOC: Record<TenderDoc['status'], StatusTone> = {
  present: 'success',
  missing: 'danger',
  na: 'neutral',
};
const RES: Record<TenderResult, StatusTone> = {
  won: 'success',
  lost: 'danger',
  disqualified: 'danger',
  cancelled: 'neutral',
};

export function PackagePill({ status }: { status: PackageStatus }) {
  const { t } = useTranslation();
  return <StatusPill tone={PKG[status]}>{t(`tender.package.${status}`)}</StatusPill>;
}

export function DocStatusPill({ doc }: { doc: TenderDoc }) {
  const { t } = useTranslation();
  return (
    <StatusPill tone={DOC[doc.status]}>
      {doc.expired && doc.status === 'missing'
        ? t('tender.docStatus.expired')
        : t(`tender.docStatus.${doc.status}`)}
    </StatusPill>
  );
}

export function ResultPill({ result }: { result: TenderResult }) {
  const { t } = useTranslation();
  return <StatusPill tone={RES[result]}>{t(`tender.results.${result}`)}</StatusPill>;
}
