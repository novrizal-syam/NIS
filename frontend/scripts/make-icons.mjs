// Renders PWA PNG icons from the gold monogram on brand-ink.
// Run: node scripts/make-icons.mjs  (uses Playwright's Chromium)
import { readFileSync } from 'node:fs';
import { chromium } from '@playwright/test';

const svg = readFileSync(
  new URL('../public/brand/nustrad-monogram-gold.svg', import.meta.url),
  'utf8',
);
const dataUrl = `data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`;

const targets = [
  { file: 'icon-192.png', size: 192, pad: 0.16 },
  { file: 'icon-512.png', size: 512, pad: 0.16 },
  // Maskable icons need the logo inside the central 80% safe zone.
  { file: 'icon-maskable-512.png', size: 512, pad: 0.24 },
];

const browser = await chromium.launch();
const page = await browser.newPage();
for (const { file, size, pad } of targets) {
  await page.setViewportSize({ width: size, height: size });
  await page.setContent(
    `<body style="margin:0;background:#1A1A1A;display:grid;place-items:center;width:${size}px;height:${size}px">
       <img src="${dataUrl}" style="width:${size * (1 - 2 * pad)}px;height:auto" />
     </body>`,
  );
  await page.screenshot({ path: new URL(`../public/icons/${file}`, import.meta.url).pathname });
}
await browser.close();
