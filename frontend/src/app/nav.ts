// Sidebar menu grouped by value stream (BRAND.md · App shell).
// `ready: false` items render with a "Segera" chip and open the placeholder page.

export interface NavItem {
  key: string; // i18n key under nav.items and URL slug
  path: string;
  icon: string; // Material Symbols Outlined name
  ready: boolean;
  devOnly?: boolean;
  /** RBAC module whose `view` permission shows this item; none = every signed-in user. */
  module?: string;
}

export interface NavGroup {
  key: string; // i18n key under nav.groups
  items: NavItem[];
}

const soon = (key: string, icon: string, module?: string): NavItem => ({
  key,
  icon,
  module,
  path: `/segera/${key}`,
  ready: false,
});

export const NAV: NavGroup[] = [
  {
    key: 'overview',
    items: [
      { key: 'dashboard', path: '/', icon: 'space_dashboard', ready: true },
      { key: 'approvals', path: '/persetujuan', icon: 'task_alt', ready: true },
    ],
  },
  {
    key: 'leadToContract',
    items: [
      soon('leads', 'person_search', 'crm'),
      soon('opportunities', 'trending_up', 'crm'),
      soon('quotations', 'request_quote', 'quotation'),
      soon('tenders', 'gavel', 'tender'),
      soon('contracts', 'handshake', 'contract'),
    ],
  },
  {
    key: 'plan',
    items: [
      soon('projects', 'account_tree', 'project'),
      soon('budgets', 'savings', 'budget'),
      soon('bcr', 'published_with_changes', 'budget'),
    ],
  },
  {
    key: 'procureToPay',
    items: [
      soon('materialRequests', 'inventory', 'inventory'),
      soon('purchaseRequisitions', 'assignment', 'procurement'),
      soon('rfq', 'compare_arrows', 'procurement'),
      soon('purchaseOrders', 'shopping_cart', 'procurement'),
      soon('goodsReceipts', 'local_shipping', 'inventory'),
      soon('inventoryStock', 'warehouse', 'inventory'),
      soon('vendorInvoices', 'receipt_long', 'finance'),
    ],
  },
  {
    key: 'execution',
    items: [
      soon('dor', 'engineering', 'operations'),
      soon('maintenance', 'build', 'maintenance'),
      soon('qhse', 'health_and_safety', 'qhse'),
    ],
  },
  {
    key: 'orderToCash',
    items: [
      soon('serviceTickets', 'fact_check', 'billing'),
      soon('invoices', 'description', 'billing'),
      soon('receipts', 'payments', 'treasury'),
    ],
  },
  {
    key: 'finance',
    items: [
      soon('ledger', 'menu_book', 'finance'),
      soon('treasury', 'account_balance', 'treasury'),
      soon('payroll', 'badge', 'payroll'),
      soon('tax', 'percent', 'tax'),
      soon('capex', 'precision_manufacturing', 'capex'),
    ],
  },
  {
    key: 'peopleDocs',
    items: [
      soon('letters', 'mail', 'letters'),
      soon('dms', 'folder_open', 'dms'),
      soon('lms', 'school', 'lms'),
    ],
  },
  {
    key: 'settings',
    items: [
      soon('settings', 'settings', 'settings'),
      { key: 'masterData', path: '/master', icon: 'database', ready: true, module: 'master' },
      soon('users', 'manage_accounts', 'users'),
      { key: 'doaRules', path: '/pengaturan/doa', icon: 'rule', ready: true, module: 'workflow' },
      { key: 'auditTrail', path: '/audit', icon: 'policy', ready: true, module: 'audit' },
      { key: 'components', path: '/dev/komponen', icon: 'widgets', ready: true, devOnly: true },
    ],
  },
];

export function visibleNav(
  isDev: boolean,
  canView: (module: string) => boolean = () => true,
): NavGroup[] {
  return NAV.map((g) => ({
    ...g,
    items: g.items.filter((i) => (isDev || !i.devOnly) && (!i.module || canView(i.module))),
  })).filter((g) => g.items.length > 0);
}

export function findNavItem(key: string): NavItem | undefined {
  for (const g of NAV) for (const i of g.items) if (i.key === key) return i;
  return undefined;
}
