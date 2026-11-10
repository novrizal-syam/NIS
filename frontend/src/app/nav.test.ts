import en from '@/i18n/locales/en.json';
import id from '@/i18n/locales/id.json';
import { NAV, visibleNav } from './nav';

describe('navigation', () => {
  it('has the nine value-stream groups in order', () => {
    expect(NAV.map((g) => g.key)).toEqual([
      'overview',
      'leadToContract',
      'plan',
      'procureToPay',
      'execution',
      'orderToCash',
      'finance',
      'peopleDocs',
      'settings',
    ]);
  });

  it('translates every group and item in id and en', () => {
    for (const locale of [id, en]) {
      for (const g of NAV) {
        expect(locale.nav.groups[g.key as keyof typeof locale.nav.groups]).toBeTruthy();
        for (const i of g.items) {
          expect(locale.nav.items[i.key as keyof typeof locale.nav.items], i.key).toBeTruthy();
        }
      }
    }
  });

  it('hides dev-only items outside development', () => {
    const keys = visibleNav(false).flatMap((g) => g.items.map((i) => i.key));
    expect(keys).not.toContain('components');
  });
});

describe('permission filtering', () => {
  it('drops items without view permission and empty groups', () => {
    const groups = visibleNav(false, (m) => m === 'procurement');
    // "Slip gaji saya" (07c) and the PDP breach report (10d) are for every signed-in user.
    expect(groups.map((g) => g.key)).toEqual([
      'overview',
      'procureToPay',
      'peopleDocs',
      'settings',
    ]);
    expect(groups[2]!.items.map((i) => i.key)).toEqual(['myPayslips']);
    expect(groups[3]!.items.map((i) => i.key)).toEqual(['pdp']);
    expect(groups[1]!.items.map((i) => i.key)).toEqual([
      'purchaseRequisitions',
      'rfq',
      'purchaseOrders',
    ]);
  });
});
