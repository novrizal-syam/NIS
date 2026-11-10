import { navItemFor } from './pageMeta';

it('finds the menu item a page belongs to for the top-bar title', () => {
  expect(navItemFor('/pengaturan/go-live')?.key).toBe('goLive');
  expect(navItemFor('/pengaturan/pdp')?.key).toBe('pdp');
  expect(navItemFor('/capex/123')?.key).toBe('capex');
  expect(navItemFor('/tagihan/invoice/9')?.key).toBe('serviceTickets');
  expect(navItemFor('/tidak-ada')).toBeUndefined();
  expect(navItemFor('/capexx')).toBeUndefined();
});
