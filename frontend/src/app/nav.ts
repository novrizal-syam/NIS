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
      { key: 'leads', path: '/lead', icon: 'person_search', ready: true, module: 'crm' },
      {
        key: 'opportunities',
        path: '/peluang',
        icon: 'trending_up',
        ready: true,
        module: 'crm',
      },
      {
        key: 'quotations',
        path: '/penawaran',
        icon: 'request_quote',
        ready: true,
        module: 'quotation',
      },
      { key: 'tenders', path: '/tender', icon: 'gavel', ready: true, module: 'tender' },
      { key: 'contracts', path: '/kontrak', icon: 'handshake', ready: true, module: 'contract' },
    ],
  },
  {
    key: 'plan',
    items: [
      { key: 'projects', path: '/proyek', icon: 'account_tree', ready: true, module: 'project' },
      soon('budgets', 'savings', 'budget'),
      soon('bcr', 'published_with_changes', 'budget'),
    ],
  },
  {
    key: 'procureToPay',
    items: [
      {
        key: 'materialRequests',
        path: '/gudang/mr',
        icon: 'inventory',
        ready: true,
        module: 'inventory',
      },
      {
        key: 'purchaseRequisitions',
        path: '/pengadaan/pr',
        icon: 'assignment',
        ready: true,
        module: 'procurement',
      },
      {
        key: 'rfq',
        path: '/pengadaan/rfq',
        icon: 'compare_arrows',
        ready: true,
        module: 'procurement',
      },
      {
        key: 'purchaseOrders',
        path: '/pengadaan/po',
        icon: 'shopping_cart',
        ready: true,
        module: 'procurement',
      },
      {
        key: 'goodsReceipts',
        path: '/gudang/gr',
        icon: 'local_shipping',
        ready: true,
        module: 'inventory',
      },
      {
        key: 'inventoryStock',
        path: '/gudang/stok',
        icon: 'warehouse',
        ready: true,
        module: 'inventory',
      },
      {
        key: 'vendorInvoices',
        path: '/keuangan/tagihan-vendor',
        icon: 'receipt_long',
        ready: true,
        module: 'finance',
      },
    ],
  },
  {
    key: 'execution',
    items: [
      { key: 'dor', path: '/operasi/dor', icon: 'engineering', ready: true, module: 'operations' },
      {
        key: 'maintenance',
        path: '/pemeliharaan',
        icon: 'build',
        ready: true,
        module: 'maintenance',
      },
      { key: 'qhse', path: '/qhse', icon: 'health_and_safety', ready: true, module: 'qhse' },
    ],
  },
  {
    key: 'orderToCash',
    items: [
      {
        key: 'serviceTickets',
        path: '/tagihan',
        icon: 'fact_check',
        ready: true,
        module: 'billing',
      },
      {
        key: 'invoices',
        path: '/tagihan?tab=invoices',
        icon: 'description',
        ready: true,
        module: 'billing',
      },
      {
        key: 'receipts',
        path: '/tagihan?tab=receipts',
        icon: 'payments',
        ready: true,
        module: 'billing',
      },
    ],
  },
  {
    key: 'finance',
    items: [
      {
        key: 'ledger',
        path: '/keuangan/buku-besar',
        icon: 'menu_book',
        ready: true,
        module: 'finance',
      },
      {
        key: 'treasury',
        path: '/keuangan/treasury',
        icon: 'account_balance',
        ready: true,
        module: 'treasury',
      },
      {
        key: 'payroll',
        path: '/keuangan/penggajian',
        icon: 'badge',
        ready: true,
        module: 'payroll',
      },
      { key: 'tax', path: '/keuangan/pajak', icon: 'percent', ready: true, module: 'tax' },
      {
        key: 'periodClose',
        path: '/keuangan/tutup-buku',
        icon: 'lock_clock',
        ready: true,
        module: 'finance',
      },
      {
        key: 'capex',
        path: '/capex',
        icon: 'precision_manufacturing',
        ready: true,
        module: 'capex',
      },
    ],
  },
  {
    key: 'peopleDocs',
    items: [
      { key: 'myPayslips', path: '/slip-gaji', icon: 'receipt_long', ready: true },
      { key: 'letters', path: '/surat', icon: 'mail', ready: true, module: 'letters' },
      { key: 'dms', path: '/dokumen', icon: 'folder_open', ready: true, module: 'dms' },
      { key: 'lms', path: '/pelatihan', icon: 'school', ready: true, module: 'lms' },
    ],
  },
  {
    key: 'settings',
    items: [
      { key: 'settings', path: '/pengaturan', icon: 'settings', ready: true, module: 'settings' },
      { key: 'masterData', path: '/master', icon: 'database', ready: true, module: 'master' },
      { key: 'users', path: '/pengguna', icon: 'manage_accounts', ready: true, module: 'users' },
      {
        key: 'roles',
        path: '/pengaturan/peran',
        icon: 'admin_panel_settings',
        ready: true,
        module: 'users',
      },
      { key: 'sod', path: '/pengaturan/sod', icon: 'gpp_maybe', ready: true, module: 'users' },
      { key: 'doaRules', path: '/pengaturan/doa', icon: 'rule', ready: true, module: 'workflow' },
      {
        key: 'integrations',
        path: '/pengaturan/integrasi',
        icon: 'hub',
        ready: true,
        module: 'settings',
      },
      { key: 'auditTrail', path: '/audit', icon: 'policy', ready: true, module: 'audit' },
      {
        key: 'accessReview',
        path: '/pengaturan/tinjauan-akses',
        icon: 'fact_check',
        ready: true,
        module: 'audit',
      },
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
