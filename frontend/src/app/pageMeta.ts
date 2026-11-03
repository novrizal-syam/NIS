import { useTranslation } from 'react-i18next';
import { matchPath, useLocation } from 'react-router-dom';
import { useMeta } from '@/features/master/api';
import { findNavItem } from './nav';

export interface PageMeta {
  title: string;
  description: string;
}

/** Title and one-line description shown in the top bar for the current route. */
export function usePageMeta(): PageMeta {
  const { t } = useTranslation();
  const { pathname } = useLocation();
  const masterEntity = matchPath('/master/:entity', pathname)?.params.entity ?? '';
  const entityMeta = useMeta(masterEntity, masterEntity !== '');

  if (pathname === '/') {
    return { title: t('pages.dashboard.title'), description: t('pages.dashboard.description') };
  }
  const soon = matchPath('/segera/:key', pathname);
  if (soon?.params.key && findNavItem(soon.params.key)) {
    return {
      title: t(`nav.items.${soon.params.key}`),
      description: t('pages.soon.description'),
    };
  }
  if (pathname === '/persetujuan') {
    return { title: t('pages.approvals.title'), description: t('pages.approvals.description') };
  }
  if (matchPath('/persetujuan/:id', pathname)) {
    return {
      title: t('pages.approvalDetail.title'),
      description: t('pages.approvalDetail.description'),
    };
  }
  if (pathname === '/pengaturan/peran' || matchPath('/pengaturan/peran/:id', pathname)) {
    return { title: t('pages.roles.title'), description: t('pages.roles.description') };
  }
  if (pathname === '/pengaturan/tinjauan-akses') {
    return {
      title: t('pages.accessReview.title'),
      description: t('pages.accessReview.description'),
    };
  }
  if (pathname === '/pengaturan/sod') {
    return { title: t('pages.sod.title'), description: t('pages.sod.description') };
  }
  if (pathname === '/pengguna') {
    return { title: t('pages.users.title'), description: t('pages.users.description') };
  }
  if (pathname === '/pengaturan') {
    return { title: t('pages.settings.title'), description: t('pages.settings.description') };
  }
  if (pathname === '/pengaturan/doa') {
    return { title: t('pages.doaRules.title'), description: t('pages.doaRules.description') };
  }
  if (pathname === '/audit') {
    return { title: t('pages.audit.title'), description: t('pages.audit.description') };
  }
  if (pathname === '/master') {
    return { title: t('pages.master.title'), description: t('pages.master.description') };
  }
  if (masterEntity) {
    return {
      title: entityMeta.data?.label ?? t('pages.master.title'),
      description: t('pages.master.description'),
    };
  }
  if (pathname === '/dev/komponen') {
    return { title: t('pages.components.title'), description: t('pages.components.description') };
  }
  return { title: t('pages.notFound.title'), description: t('pages.notFound.description') };
}
