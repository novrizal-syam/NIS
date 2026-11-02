import { useTranslation } from 'react-i18next';
import { Link, useParams } from 'react-router-dom';
import { findNavItem } from '@/app/nav';
import { buttonVariants } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Icon } from '@/components/ui/icon';
import { NotFoundPage } from './NotFoundPage';

export function ComingSoonPage() {
  const { t } = useTranslation();
  const { key = '' } = useParams();
  const item = findNavItem(key);
  if (!item) return <NotFoundPage />;

  return (
    <Card className="mx-auto max-w-xl">
      <CardContent className="flex flex-col items-center gap-3 p-8 text-center">
        <span className="grid h-12 w-12 place-items-center rounded-control bg-surface-muted text-fg-accent">
          <Icon name={item.icon} className="text-[28px]" />
        </span>
        <p className="eyebrow">{t('nav.soon')}</p>
        <p className="text-body text-fg-body">
          {t('pages.soon.body', { name: t(`nav.items.${key}`) })}
        </p>
        <Link to="/" className={buttonVariants({ variant: 'secondary' })}>
          {t('pages.soon.back')}
        </Link>
      </CardContent>
    </Card>
  );
}
