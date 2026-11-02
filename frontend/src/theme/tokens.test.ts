import { readFileSync } from 'node:fs';
import path from 'node:path';
import { contrastRatio, parseTokens, type RGB } from './contrast';

const css = readFileSync(path.resolve(__dirname, 'tokens.css'), 'utf8');

function block(selectorStart: string): string {
  const start = css.indexOf(selectorStart);
  if (start < 0) throw new Error(`block ${selectorStart} not found`);
  const open = css.indexOf('{', start);
  return css.slice(open, css.indexOf('}', open));
}

const light = parseTokens(block(':root,'));
const dark = { ...light, ...parseTokens(block("[data-theme='dark']")) };
const system = { ...light, ...parseTokens(block(':root:not([data-theme])')) };

// [foreground, background] pairs that carry text in the UI.
const TEXT_PAIRS: [string, string][] = [
  ...['text', 'text-body', 'text-secondary', 'text-muted', 'text-accent'].flatMap(
    (fg) =>
      ['surface', 'surface-muted', 'surface-raised'].map((bg) => [fg, bg]) as [string, string][],
  ),
  ['text-on-inverse', 'surface-inverse'],
  ['on-gold', 'brand-gold'],
  ['on-gold-muted', 'brand-gold'],
  ['success', 'success-tint'],
  ['warning', 'warning-tint'],
  ['danger', 'danger-tint'],
  ['info', 'info-tint'],
  ['danger', 'surface'],
  ['sidebar-fg', 'brand-ink'],
  ['sidebar-muted', 'brand-ink'],
  ['sidebar-fg', 'sidebar-hover'],
  ['sidebar-muted', 'sidebar-hover'],
];

describe.each([
  ['light', light],
  ['dark', dark],
])('%s theme tokens', (_name, tokens: Record<string, RGB>) => {
  it.each(TEXT_PAIRS)('%s on %s has contrast >= 4.5:1', (fg, bg) => {
    expect(tokens[fg], fg).toBeDefined();
    expect(tokens[bg], bg).toBeDefined();
    expect(contrastRatio(tokens[fg]!, tokens[bg]!)).toBeGreaterThanOrEqual(4.5);
  });

  it('focus ring is visible (>= 3:1) on the page surface', () => {
    expect(contrastRatio(tokens['focus-ring']!, tokens.surface!)).toBeGreaterThanOrEqual(3);
  });
});

it('system-dark block matches the explicit dark theme', () => {
  expect(system).toEqual(dark);
});

it('gold is never used as text on light surfaces', () => {
  // Guard for BRAND.md: brand gold fails contrast on white, so it must stay a fill.
  expect(contrastRatio(light['brand-gold']!, light.surface!)).toBeLessThan(4.5);
});
