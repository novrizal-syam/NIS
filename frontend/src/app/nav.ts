// Sidebar menu grouped by value stream (BRAND.md · App shell).
// `ready: false` items render with a "Segera" chip and open the placeholder page.

export interface NavItem {
  key: string; // i18n key under nav.items and URL slug
  path: string;
  icon: string; // Material Symbols Outlined name
  ready: boolean;
  devOnly?: boolean;
}

export interface NavGroup {
  key: string; // i18n key under nav.groups
  items: NavItem[];
}

const soon = (key: string, icon: string): NavItem => ({
  key,
  icon,
  path: `/segera/${key}`,
  ready: false,
});

export const NAV: NavGroup[] = [
  {
    key: 'overview',
    items: [
      { key: 'dashboard', path: '/', icon: 'space_dashboard', ready: true },
      soon('approvals', 'task_alt'),
    ],
  },
  {
    key: 'leadToContract',
    items: [
      soon('leads', 'person_search'),
      soon('opportunities', 'trending_up'),
      soon('quotations', 'request_quote'),
      soon('tenders', 'gavel'),
      soon('contracts', 'handshake'),
    ],
  },
  {
    key: 'plan',
    items: [
      soon('projects', 'account_tree'),
      soon('budgets', 'savings'),
      soon('bcr', 'published_with_changes'),
    ],
  },
  {
    key: 'procureToPay',
    items: [
      soon('materialRequests', 'inventory'),
      soon('purchaseRequisitions', 'assignment'),
      soon('rfq', 'compare_arrows'),
      soon('purchaseOrders', 'shopping_cart'),
      soon('goodsReceipts', 'local_shipping'),
      soon('inventoryStock', 'warehouse'),
      soon('vendorInvoices', 'receipt_long'),
    ],
  },
  {
    key: 'execution',
    items: [
      soon('dor', 'engineering'),
      soon('maintenance', 'build'),
      soon('qhse', 'health_and_safety'),
    ],
  },
  {
    key: 'orderToCash',
    items: [
      soon('serviceTickets', 'fact_check'),
      soon('invoices', 'description'),
      soon('receipts', 'payments'),
    ],
  },
  {
    key: 'finance',
    items: [
      soon('ledger', 'menu_book'),
      soon('treasury', 'account_balance'),
      soon('payroll', 'badge'),
      soon('tax', 'percent'),
      soon('capex', 'precision_manufacturing'),
    ],
  },
  {
    key: 'peopleDocs',
    items: [soon('letters', 'mail'), soon('dms', 'folder_open'), soon('lms', 'school')],
  },
  {
    key: 'settings',
    items: [
      soon('settings', 'settings'),
      soon('users', 'manage_accounts'),
      { key: 'components', path: '/dev/komponen', icon: 'widgets', ready: true, devOnly: true },
    ],
  },
];

export function visibleNav(isDev: boolean): NavGroup[] {
  return NAV.map((g) => ({ ...g, items: g.items.filter((i) => isDev || !i.devOnly) }));
}

export function findNavItem(key: string): NavItem | undefined {
  for (const g of NAV) for (const i of g.items) if (i.key === key) return i;
  return undefined;
}
