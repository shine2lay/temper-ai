// Look-only capture + measurement of a product's screens for design_app_screen_v1 stage 2 (existing), on the host.
// Generalized from Design #170's RollCall capture (results/rollcall-mobile-redesign-20261104/current/tools/capture.mjs,
// left as it was): the base address, the login, the page's parts and the capture list come from a plan that
// bin/app_screen/existing.py writes from the product's app file. It only opens pages, follows links and may open a
// ticket; it never clicks anything that sends, places or confirms.
//   node existing_capture.mjs <plan.json>
// Plan: {base_url, login|null, page, captures: [{id, width, height, phone, account, delay_api, steps}], out_dir,
//        state_dir, measure_script}. Writes <out_dir>/<id>.png (first view) and <out_dir>/raw.json
//        ({id: measure result | {failed}}). Exit 0 even when a capture fails: the caller reads raw.json.
import { createRequire } from 'node:module';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

function loadPlaywright() {
  const candidates = [
    process.env.APP_SCREEN_PLAYWRIGHT_FROM,
    new URL('../../../../frontend/package.json', import.meta.url),
    import.meta.url,
    path.join(os.homedir(), 'temper-ai/frontend/package.json'),
  ].filter(Boolean);
  let lastErr;
  for (const c of candidates) {
    try {
      return createRequire(c)('playwright');
    } catch (e) {
      lastErr = e;
    }
  }
  throw lastErr;
}
const { chromium } = loadPlaywright();

const plan = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const BASE = String(plan.base_url || '').replace(/\/$/, '');
if (!/^https?:\/\//.test(BASE) || /^https?:\/\/rollcall\.wai2shine\.com(?:[:/]|$)/i.test(BASE)) {
  throw new Error(`refusing invalid or live address ${BASE}`);
}
const PAGE = plan.page;
const CREDS = JSON.parse(process.env.APP_SCREEN_CREDENTIALS_JSON || '{}');
const SECRETS = Object.values(CREDS).filter((v) => typeof v === 'string' && v.length > 0).sort((a, b) => b.length - a.length);
const states = new Map();
const measureSrc = fs.readFileSync(plan.measure_script, 'utf8');
const NEVER = /send|place|confirm|submit|delete|cancel order/i;

function redact(text) {
  let out = String(text ?? '');
  for (const s of SECRETS) out = out.split(s).join('[REDACTED]');
  return out;
}

async function settle(page) {
  await page.waitForSelector(PAGE.main, { timeout: 20000 }).catch(() => {});
  await page.waitForTimeout(PAGE.settle_ms ?? 1800);
  if (!PAGE.loading_text) return;
  // wait out loading placeholders for up to 8 s
  for (let i = 0; i < 16; i++) {
    const loading = await page.evaluate(([sel, re]) => new RegExp(re).test(document.querySelector(sel)?.innerText || ''), [PAGE.main, PAGE.loading_text]);
    if (!loading) break;
    await page.waitForTimeout(500);
  }
}

async function loginState(browser, account) {
  if (!plan.login || !account || account === 'none') return undefined;
  if (states.has(account)) return states.get(account);
  const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  const page = await ctx.newPage();
  try {
    await page.goto(BASE + plan.login.path, { waitUntil: 'load', timeout: 25000 });
    for (const [sel, value] of Object.entries(plan.login.fields || {})) {
      const strVal = String(value);
      const filled = strVal.includes('{account}@') && account.includes('@') ? account : strVal.replaceAll('{account}', account);
      await page.fill(sel, filled);
    }
    if (plan.login.user_selector && !(plan.login.fields && plan.login.user_selector in plan.login.fields)) {
      const userVal = account.includes('@') || plan.login.fields ? account : `${account}@rollcall.test`;
      await page.fill(plan.login.user_selector, userVal);
    }
    if (plan.login.password_selector) {
      const short = account.split('@')[0];
      const pwd = CREDS[account] ?? CREDS[short] ?? CREDS['*'] ?? CREDS.default ?? CREDS.password ?? '';
      if (!pwd) throw new Error(`missing runtime credentials for account ${account}`);
      await page.fill(plan.login.password_selector, pwd);
    }
    await page.click(plan.login.submit);
    await page.waitForSelector(plan.login.wait_for, { timeout: 20000 });
    await page.waitForTimeout(1000);
    const state = await ctx.storageState();
    states.set(account, state);
    return state;
  } catch (err) {
    const e = new Error(redact(`login failed for account ${account} at ${BASE}${plan.login.path}: ${err.message || err}`));
    e.loginFailed = true;
    throw e;
  } finally {
    await ctx.close();
  }
}

async function followFirstLink(page, prefix) {
  const href = await page.evaluate(([main, p]) => {
    const a = [...document.querySelectorAll(`${main} a[href^="${p}"]`)].find((x) => x.getAttribute('href') !== p && x.offsetParent);
    return a ? a.getAttribute('href') : null;
  }, [PAGE.main, prefix]);
  if (!href) throw new Error(`no ${prefix} link on ${page.url()}`);
  await page.goto(BASE + href, { waitUntil: 'load' });
  await settle(page);
  return href;
}

async function clickFirst(page, spec) {
  // The first visible button or link in main whose text starts the way the app file says, never one that sends.
  const clicked = await page.evaluate(([main, text, not, never]) => {
    const words = new RegExp(text, 'i');
    const notRe = not ? new RegExp(not, 'i') : null;
    const neverRe = new RegExp(never, 'i');
    const btn = [...document.querySelectorAll(`${main} button, ${main} a`)].find((b) => {
      const t = (b.innerText || '').trim();
      return b.offsetParent && words.test(t) && !(notRe && notRe.test(t)) && !neverRe.test(t);
    });
    if (!btn) return null;
    btn.click();
    return (btn.innerText || '').trim().slice(0, 40);
  }, [PAGE.main, spec.text, spec.not || null, NEVER.source]);
  if (!clicked) throw new Error(`nothing to click matching ${spec.text} on ${page.url()}`);
  await page.waitForTimeout(2000);
  return clicked;
}

async function capture(browser, cap) {
  const storageState = await loginState(browser, cap.account);
  const ctx = await browser.newContext({ viewport: { width: cap.width, height: cap.height }, deviceScaleFactor: 2, isMobile: cap.phone, hasTouch: cap.phone, storageState });
  const delay = cap.delay_api ? PAGE.delay_api : null;
  if (delay) {
    await ctx.route(delay.match, async (route) => {
      const u = route.request().url();
      if (delay.except && u.includes(delay.except)) return route.continue();
      await new Promise((r) => setTimeout(r, delay.delay_ms));
      return route.continue().catch(() => {});
    });
  }
  const page = await ctx.newPage();
  const errors = [];
  page.on('pageerror', (e) => errors.push(String(e.message).slice(0, 160)));
  const did = [];
  try {
    for (const [i, step] of cap.steps.entries()) {
      const last = i === cap.steps.length - 1;
      if (step.goto) {
        await page.goto(BASE + step.goto, { waitUntil: 'load' });
        if (delay && last) await page.waitForTimeout(delay.wait_ms);
        else await settle(page);
        did.push(`goto ${step.goto}`);
      } else if (step.follow_first_link) {
        did.push(`follow ${await followFirstLink(page, step.follow_first_link)}`);
      } else if (step.click_first) {
        did.push(`click "${await clickFirst(page, step.click_first)}"`);
      } else {
        throw new Error(`unknown step ${JSON.stringify(step)}`);
      }
    }
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.waitForTimeout(200);
    const cfg = { main: PAGE.main, areas: PAGE.areas || {}, key_regions: PAGE.key_regions || {}, loading_text: PAGE.loading_text || null, error_selector: PAGE.error_selector || null };
    const m = await page.evaluate(`(${measureSrc})(${JSON.stringify(cfg)})`);
    await page.screenshot({ path: path.join(plan.out_dir, `${cap.id}.png`) });
    return { ...m, steps: did, pageErrors: errors };
  } finally {
    await ctx.close();
  }
}

fs.mkdirSync(plan.out_dir, { recursive: true });
const browser = await chromium.launch();
const results = {};
const rawFile = path.join(plan.out_dir, 'raw.json');
try {
  for (const cap of plan.captures) {
    try {
      results[cap.id] = await capture(browser, cap);
      const m = results[cap.id];
      console.log(cap.id, 'w', m.viewport.w, 'h', m.pageHeight, 'u16', m.type.under16, 'small', m.targets.under24NotInline, 'trunc', m.truncated.count);
    } catch (e) {
      if (e && e.loginFailed) throw e;
      const msg = redact(String(e.message || e)).slice(0, 300);
      console.log(`${cap.id} FAILED ${msg}`);
      results[cap.id] = { failed: msg };
    }
    fs.writeFileSync(rawFile, JSON.stringify(results));
  }
} finally {
  await browser.close();
}
