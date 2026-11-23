import { test, expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = join(here, '..');

const cases = JSON.parse(
  execFileSync(process.env.PYTHON || 'python3', [join(here, 'gate_cases.py')], { encoding: 'utf8' }),
);

test('no console errors, page errors or third-party requests', async ({ page, baseURL }) => {
  const problems = [];
  const external = [];
  page.on('console', (m) => { if (['error', 'warning'].includes(m.type())) problems.push(`${m.type()}: ${m.text()}`); });
  page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`));
  page.on('requestfailed', (r) => problems.push(`requestfailed: ${r.url()}`));
  page.on('request', (r) => { if (!r.url().startsWith(baseURL) && !r.url().startsWith('data:')) external.push(r.url()); });
  await page.goto('/');
  await page.waitForLoadState('networkidle');
  expect(problems).toEqual([]);
  expect(external).toEqual([]);
});

for (const width of [375, 1440]) {
  test(`no horizontal overflow at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    const m = await page.evaluate(() => ({
      doc: document.documentElement.scrollWidth,
      body: document.body.scrollWidth,
      inner: window.innerWidth,
    }));
    expect(m.doc).toBeLessThanOrEqual(m.inner);
    expect(m.body).toBeLessThanOrEqual(m.inner);
  });
}

test('reduced motion shows every section and animated element', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' });
  await page.goto('/');
  for (const id of ['pipeline', 'gate-demo', 'features', 'quick-start', 'validation']) {
    await expect(page.locator(`#${id}`)).toBeVisible();
  }
  const hidden = await page.evaluate(() =>
    [...document.querySelectorAll('.reveal')].filter((el) => getComputedStyle(el).opacity !== '1').length);
  expect(hidden).toBe(0);
  const anim = await page.evaluate(() => getComputedStyle(document.querySelector('.aurora i')).animationName);
  expect(anim).toBe('none');
});

test('content is visible with JavaScript disabled', async ({ browser, baseURL }) => {
  const ctx = await browser.newContext({ javaScriptEnabled: false, baseURL });
  const page = await ctx.newPage();
  await page.goto('/');
  for (const id of ['pipeline', 'gate-demo', 'features', 'quick-start', 'validation']) {
    await expect(page.locator(`#${id}`)).toBeVisible();
  }
  await expect(page.locator('.card').first()).toHaveCSS('opacity', '1');
  await ctx.close();
});

test('internal links, anchors and assets resolve', async ({ page, request }) => {
  await page.goto('/');
  const found = await page.evaluate(() => ({
    hrefs: [...document.querySelectorAll('a[href]')].map((a) => a.getAttribute('href')),
    ids: [...document.querySelectorAll('[id]')].map((e) => e.id),
    assets: [...document.querySelectorAll('link[href], script[src]')].map((e) => e.getAttribute('href') || e.getAttribute('src')),
  }));
  for (const h of found.hrefs) {
    if (h.startsWith('#')) expect(found.ids, `anchor ${h}`).toContain(h.slice(1));
    else if (!/^https?:/.test(h)) expect((await request.get(h)).status(), h).toBe(200);
  }
  for (const a of [...found.assets, 'og-image.png', 'favicon.svg', 'robots.txt', 'sitemap.xml', '404.html']) {
    if (!/^https?:/.test(a)) expect((await request.get(a)).status(), a).toBe(200);
  }
  const meta = await page.evaluate(() => ({
    canonical: document.querySelector('link[rel=canonical]')?.href,
    desc: document.querySelector('meta[name=description]')?.content,
    og: document.querySelector('meta[property="og:image"]')?.content,
    tw: document.querySelector('meta[name="twitter:card"]')?.content,
    ld: JSON.parse(document.querySelector('script[type="application/ld+json"]').textContent)['@type'],
  }));
  expect(meta.canonical).toBe('https://gerardrecinto.github.io/ai-delivery-observability-kit/');
  expect(meta.desc.length).toBeGreaterThan(50);
  expect(meta.og).toMatch(/og-image\.png$/);
  expect(meta.tw).toBe('summary_large_image');
  expect(meta.ld).toBe('SoftwareSourceCode');
});

test('demo thresholds match config/thresholds.json', async ({ page }) => {
  await page.goto('/');
  const t = await page.evaluate(() => window.aideliveryGate.thresholds);
  expect(t).toEqual(JSON.parse(readFileSync(join(root, 'config', 'thresholds.json'), 'utf8')));
});

test.describe('demo decisions match the Python gate', () => {
  for (const c of cases) {
    test(c.name, async ({ page }) => {
      await page.goto('/');
      await page.locator('#s-err').fill(String(c.values.err));
      await page.locator('#s-p95').fill(String(c.values.p95));
      await page.locator('#s-cost').fill(String(c.values.cost));
      await page.locator('#s-eval').fill(String(c.values.eval));
      const want = c.code === 0 ? 'PROMOTE' : 'ROLLBACK';
      await expect(page.locator('#verdict')).toHaveText(want);
      const failed = await page.locator('#checks li.f span:nth-child(2)').allTextContents();
      expect(failed.map((s) => s.split(':')[0]).sort()).toEqual([...c.failed].sort());
      await expect(page.locator('#live')).toContainText(`Decision: ${want}`);
    });
  }
});

test('sliders are keyboard operable and labelled', async ({ page }) => {
  await page.goto('/');
  const s = page.getByLabel('Error rate');
  await s.focus();
  await page.keyboard.press('End');
  await expect(page.locator('#verdict')).toHaveText('ROLLBACK');
  await page.keyboard.press('Home');
  await expect(page.locator('#verdict')).toHaveText('PROMOTE');
  for (const l of ['Error rate', 'p95 latency', 'Cost per 1k tokens', 'Eval score']) {
    await expect(page.getByLabel(l)).toBeVisible();
  }
  await expect(page.locator('#live')).toHaveAttribute('aria-live', 'polite');
});

test('copy button copies the command', async ({ browser, baseURL }) => {
  const ctx = await browser.newContext({ baseURL, permissions: ['clipboard-read', 'clipboard-write'] });
  const page = await ctx.newPage();
  await page.goto('/');
  await page.locator('[data-copy-target="cmd-2"]').click();
  await expect(page.locator('[data-copy-target="cmd-2"]')).toHaveText('Copied');
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('scripts/canary_smoke.sh 0.5');
  await ctx.close();
});
