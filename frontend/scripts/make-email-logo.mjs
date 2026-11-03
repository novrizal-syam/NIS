// Renders the primary logo to PNG for HTML emails (many clients block SVG).
// Run: node scripts/make-email-logo.mjs
import { readFileSync } from 'node:fs';
import { chromium } from '@playwright/test';

const svg = readFileSync(new URL('../public/brand/nustrad-logo-primary.svg', import.meta.url), 'utf8');
const url = `data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}`;
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 600, height: 171 }, deviceScaleFactor: 1 });
await page.setContent(`<body style="margin:0;background:#fff"><img src="${url}" style="width:600px;display:block"></body>`);
await page.screenshot({ path: new URL('../public/brand/nustrad-logo-primary.png', import.meta.url).pathname, omitBackground: false });
await browser.close();
