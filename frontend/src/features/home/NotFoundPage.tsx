import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { buttonVariants } from '@/components/ui/button';

export function NotFoundPage() {
  const { t } = useTranslation();
  return (
    <div className="flex flex-col items-start gap-3">
      <p className="text-body text-fg-body">{t('pages.notFound.description')}</p>
      <Link to="/" className={buttonVariants({ variant: 'secondary' })}>
        {t('pages.notFound.back')}
      </Link>
    </div>
  );
}
