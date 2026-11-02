// WCAG 2.x contrast helpers, used by tests to keep token pairs at >= 4.5:1.

export type RGB = [number, number, number];

function channel(c: number): number {
  const s = c / 255;
  return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
}

export function luminance([r, g, b]: RGB): number {
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

export function contrastRatio(a: RGB, b: RGB): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

/** Parse "--name: R G B;" declarations of one CSS block. */
export function parseTokens(block: string): Record<string, RGB> {
  const out: Record<string, RGB> = {};
  for (const m of block.matchAll(/--([\w-]+):\s*(\d+)\s+(\d+)\s+(\d+)\s*;/g)) {
    out[m[1]!] = [Number(m[2]), Number(m[3]), Number(m[4])];
  }
  return out;
}
