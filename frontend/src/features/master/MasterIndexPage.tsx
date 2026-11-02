import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import { Card } from '@/components/ui/card';
import { Icon } from '@/components/ui/icon';
import { GROUPS, useEntities } from './api';

const ICONS: Record<string, string> = {
  departments: 'apartment',
  'cost-centers': 'hub',
  clients: 'business',
  vendors: 'storefront',
  employees: 'badge',
  items: 'inventory_2',
  warehouses: 'warehouse',
  assets: 'precision_manufacturing',
  accounts: 'account_tree',
  'cost-elements': 'category',
  periods: 'calendar_month',
  'price-items': 'sell',
  currencies: 'currency_exchange',
  'fx-rates': 'trending_up',
};

export function MasterIndexPage() {
  const { t } = useTranslation();
  const entities = useEntities();
  return (
    <div className="flex flex-col gap-6">
      {Object.entries(GROUPS).map(([group, labelKey]) => {
        const items = entities.data?.filter((e) => e.group === group) ?? [];
        if (items.length === 0) return null;
        return (
          <section key={group} className="flex flex-col gap-2">
            <h2 className="eyebrow">{t(labelKey)}</h2>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {items.map((e) => (
                <Link key={e.key} to={`/master/${e.key}`} className="rounded-card">
                  <Card className="flex items-center gap-3 p-4 hover:border-border-strong">
                    <span className="grid h-10 w-10 place-items-center rounded-control bg-surface-muted text-fg">
                      <Icon name={ICONS[e.key] ?? 'database'} />
                    </span>
                    <span className="font-heading text-card-title text-fg">{e.label}</span>
                  </Card>
                </Link>
              ))}
            </div>
          </section>
        );
      })}
    </div>
  );
}
