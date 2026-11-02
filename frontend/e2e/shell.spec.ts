import AxeBuilder from '@axe-core/playwright';
import { expect, test, type Page } from '@playwright/test';

const THEMES = ['light', 'dark'] as const;

async function useTheme(page: Page, theme: (typeof THEMES)[number]) {
  await page.addInitScript((t) => localStorage.setItem('nustrad.theme', t), theme);
}

async function contrastViolations(page: Page) {
  const result = await new AxeBuilder({ page }).withRules(['color-contrast']).analyze();
  return result.violations.flatMap((v) =>
    v.nodes.map((n) => `${n.target.join(' ')} — ${n.failureSummary ?? ''}`),
  );
}

for (const theme of THEMES) {
  test.describe(`${theme} theme`, () => {
    test.beforeEach(async ({ page }) => useTheme(page, theme));

    test('Komponen page passes the contrast check', async ({ page }) => {
      await page.goto('/dev/komponen');
      await expect(page.getByTestId('showcase-light')).toBeVisible();
      await expect(page.getByTestId('showcase-dark')).toBeVisible();
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      expect(await contrastViolations(page)).toEqual([]);
    });

    test('shell and login pass the contrast check', async ({ page }) => {
      await page.goto('/');
      await expect(page.getByRole('heading', { level: 1, name: 'Dasbor' })).toBeVisible();
      expect(await contrastViolations(page)).toEqual([]);
      await page.goto('/login');
      await expect(page.getByRole('heading', { name: 'Masuk' })).toBeVisible();
      expect(await contrastViolations(page)).toEqual([]);
    });
  });
}

test('full WCAG A/AA scan of the Komponen page', async ({ page }) => {
  await page.goto('/dev/komponen');
  await expect(page.getByTestId('showcase-dark')).toBeVisible();
  const result = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa']).analyze();
  expect(result.violations.map((v) => `${v.id}: ${v.help}`)).toEqual([]);
});

test('works at 400 px width without horizontal scrolling', async ({ page }) => {
  await page.setViewportSize({ width: 400, height: 800 });
  for (const path of ['/', '/dev/komponen', '/login']) {
    await page.goto(path);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow, path).toBeLessThanOrEqual(0);
  }
  await page.goto('/');
  await page.getByRole('button', { name: 'Buka menu' }).click();
  await expect(page.getByRole('dialog', { name: 'Menu utama' })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog')).toBeHidden();
});

test('keyboard users see a focus ring', async ({ page }) => {
  await page.goto('/');
  await page.keyboard.press('Tab'); // skip link
  await page.keyboard.press('Tab');
  const outline = await page.evaluate(() => {
    const el = document.activeElement as HTMLElement;
    return getComputedStyle(el).outlineStyle;
  });
  expect(outline).toBe('solid');
});
