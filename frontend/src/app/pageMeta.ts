import { useTranslation } from 'react-i18next';
import { matchPath, useLocation } from 'react-router-dom';
import { findNavItem } from './nav';

export interface PageMeta {
  title: string;
  description: string;
}

/** Title and one-line description shown in the top bar for the current route. */
export function usePageMeta(): PageMeta {
  const { t } = useTranslation();
  const { pathname } = useLocation();

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
  if (pathname === '/pengaturan/doa') {
    return { title: t('pages.doaRules.title'), description: t('pages.doaRules.description') };
  }
  if (pathname === '/dev/komponen') {
    return { title: t('pages.components.title'), description: t('pages.components.description') };
  }
  return { title: t('pages.notFound.title'), description: t('pages.notFound.description') };
}
