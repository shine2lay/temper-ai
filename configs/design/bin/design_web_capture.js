/* Design-owned whole-page evidence. Uses a NEW browser context, never the supplied tab.
 * No model, CSP bypass, stealth, style injection, Accept click, login or robot solving.
 * setup is a fixed-fixture test hook, deliberately not a CLI/workflow input.
 */
const REJECT_LABELS = ['reject all', 'reject', 'decline', 'decline all', 'only necessary',
  'necessary only', 'use necessary cookies only', 'refuse', 'deny'];

function observePage() {
  const round = n => Math.round(n * 100) / 100;
  const pathFor = e => {
    const parts = [];
    for (; e && e !== document.documentElement; e = e.parentElement) {
      const sib = [...e.parentElement.children].filter(s => s.tagName === e.tagName);
      parts.unshift(e.tagName.toLowerCase() + ':nth-of-type(' + (sib.indexOf(e) + 1) + ')');
    }
    return 'html>' + parts.join('>');
  };
  function visibility(e, rects) {
    let opacity = 1;
    for (let p = e; p; p = p.parentElement) {
      const s = getComputedStyle(p); opacity *= Number(s.opacity);
      if (s.display === 'none' || s.visibility !== 'visible' || s.contentVisibility === 'hidden' || opacity <= .01)
        return {visibility: 'hidden', reason: 'css_not_painted'};
    }
    const inview = rects.filter(r => r.right > 0 && r.bottom > 0 && r.left < innerWidth && r.top < innerHeight);
    if (!inview.length) return {visibility: 'outside_viewport', reason: 'not_sampled_at_this_scroll'};
    let checked = 0, covered = 0, clipped = 0;
    for (const r of inview) {
      for (const f of [.15, .5, .85]) {
        const x = Math.max(0, Math.min(innerWidth - 1, r.left + r.width * f));
        const y = Math.max(0, Math.min(innerHeight - 1, r.top + r.height / 2));
        let isClipped = false;
        for (let p = e.parentElement; p; p = p.parentElement) {
          const s = getComputedStyle(p), b = p.getBoundingClientRect();
          if ((/(hidden|clip|scroll|auto)/.test(s.overflowX) && (x < b.left || x > b.right)) ||
              (/(hidden|clip|scroll|auto)/.test(s.overflowY) && (y < b.top || y > b.bottom))) isClipped = true;
        }
        const hit = document.elementsFromPoint(x, y)[0]; checked++;
        if (isClipped) clipped++;
        else if (!hit || !(hit === e || hit.contains(e) || e.contains(hit))) covered++;
      }
    }
    return clipped ? {visibility: 'uncertain', reason: 'ancestor_clipping', checked, clipped} :
      covered ? {visibility: covered === checked ? 'obscured' : 'uncertain', reason: 'sampled_occlusion', checked, covered} :
      {visibility: 'visible', reason: 'sampled_unoccluded', checked, covered};
  }
  const text = [], walk = document.createTreeWalker(document.body || document.documentElement, NodeFilter.SHOW_TEXT);
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    const e = n.parentElement;
    if (!e || e.closest('script,style,noscript,template,head')) continue;
    const value = n.textContent.replace(/\s+/g, ' ').trim();
    if (!value) continue;
    const range = document.createRange(); range.selectNodeContents(n);
    const rects = [...range.getClientRects()].filter(r => r.width > 0 && r.height > 0);
    if (!rects.length) continue;
    const x = Math.min(...rects.map(r => r.left)), y = Math.min(...rects.map(r => r.top));
    const right = Math.max(...rects.map(r => r.right)), bottom = Math.max(...rects.map(r => r.bottom));
    const element = pathFor(e), index = [...e.childNodes].indexOf(n);
    let overlay = false;
    for (let p = e; p; p = p.parentElement) if (['fixed','sticky'].includes(getComputedStyle(p).position)) overlay = true;
    text.push({id: element + '#text-' + index, element, tag: e.tagName.toLowerCase(), text: value, positioned_overlay: overlay,
      bbox: [x + scrollX, y + scrollY, right - x, bottom - y].map(round),
      rects: rects.map(r => [r.x + scrollX, r.y + scrollY, r.width, r.height].map(round)),
      ...visibility(e, rects)});
  }
  const displayed = e => {
    const s = getComputedStyle(e), r = e.getBoundingClientRect();
    return s.display !== 'none' && s.visibility === 'visible' && Number(s.opacity) > .01 && r.width > 0 && r.height > 0;
  };
  const images = [...document.images].filter(displayed).map(e => {
    const r = e.getBoundingClientRect();
    return {url: e.currentSrc || e.src, bbox: [r.x + scrollX, r.y + scrollY, r.width, r.height].map(round),
      complete: e.complete, natural_width: e.naturalWidth, in_view: r.bottom > 0 && r.top < innerHeight};
  });
  const main = document.querySelector('main,[role="main"]');
  const graphics = [...document.querySelectorAll('img,svg,canvas,video')].filter(displayed);
  const graphicArea = graphics.reduce((sum, e) => {
    const r = e.getBoundingClientRect(); return sum + r.width * r.height;
  }, 0);
  const largeHeroes = [...document.querySelectorAll('section,header,main,article')].filter(e => {
    const r = e.getBoundingClientRect();
    return r.height >= innerHeight * .8 && r.height <= innerHeight * 1.25 && e.querySelectorAll('h1,h2,h3').length === 1;
  }).map(e => { const r = e.getBoundingClientRect(); return [r.top + scrollY, r.bottom + scrollY].map(round); });
  return {url: location.href, title: document.title, viewport: {width: innerWidth, height: innerHeight},
    scroll_x: scrollX, scroll_y: scrollY, document_height: Math.max(document.documentElement.scrollHeight, document.body?.scrollHeight || 0, innerHeight),
    scroll_width: Math.max(document.documentElement.scrollWidth, document.body?.scrollWidth || 0, innerWidth),
    fonts_loaded: document.fonts.status === 'loaded', text_nodes: text, images,
    metrics: {h1_count: text.filter(n => n.tag === 'h1' && n.visibility === 'visible').length,
      main_chars: main ? main.innerText.trim().length : null, graphic_area: round(graphicArea),
      body_chars: document.body?.innerText.trim().length || 0, hero_ranges: largeHeroes},
    iframes: [...document.querySelectorAll('iframe')].map(e => ({src: e.src, title: e.title,
      reason: 'frame_text_export_attempted_separately_in_document_coordinates'})),
    environment: {user_agent: navigator.userAgent, locale: navigator.language,
      time_zone: Intl.DateTimeFormat().resolvedOptions().timeZone, html_lang: document.documentElement.lang}};
}

function consentControls(labels) {
  const visible = e => {
    const r = e.getBoundingClientRect(), s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0 && r.top < innerHeight && r.left < innerWidth &&
      s.display !== 'none' && s.visibility === 'visible' && Number(s.opacity) > .01;
  };
  const label = e => String(e.innerText || e.value || e.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().toLowerCase();
  const pathFor = e => {
    const parts = [];
    for (; e && e !== document.documentElement; e = e.parentElement) {
      const sib = [...e.parentElement.children].filter(s => s.tagName === e.tagName);
      parts.unshift(e.tagName.toLowerCase() + ':nth-of-type(' + (sib.indexOf(e) + 1) + ')');
    }
    return 'html>' + parts.join('>');
  };
  let present = false;
  const candidates = [];
  for (const e of document.querySelectorAll('button,[role="button"],input[type="button"],input[type="submit"],a')) {
    if (!visible(e)) continue;
    let scope = null;
    for (let p = e.parentElement; p && p !== document.body; p = p.parentElement) {
      const s = getComputedStyle(p), t = (p.innerText || '').toLowerCase();
      if ((p.matches('dialog,[role="dialog"],[aria-modal="true"]') || ['fixed','sticky'].includes(s.position) ||
           /cookie|consent|onetrust/i.test(p.id + ' ' + p.className)) && /cookies?|consent/.test(t)) { scope = p; break; }
    }
    // Known CMP ids still require exact safe text and actual cookie context.
    if (!scope) continue;
    present = true;
    const text = label(e);
    if (labels.includes(text)) candidates.push({selector: pathFor(e), label: text, id: e.id || null,
      scope_text: scope.innerText.replace(/\s+/g, ' ').slice(0, 1200)});
  }
  return {present, candidates};
}

function trackCaptureNetwork(context, quietMs) {
  const active = new Set(); let activity = 0, last = Date.now();
  context.on('request', r => { active.add(r); activity++; last = Date.now(); });
  const finish = r => { active.delete(r); activity++; last = Date.now(); };
  context.on('requestfinished', finish); context.on('requestfailed', finish);
  return () => ({activity, inflight: active.size, quiet_ms: Date.now() - last,
    quiet: active.size === 0 && Date.now() - last >= quietMs,
    pending: [...active].map(r => ({url: r.url(), type: r.resourceType()}))});
}

async function captureWithBrowser(browser, request, viewport, setup = null) {
  const started = Date.now(); let context, target;
  const record = {viewport, requested_url: request.url, csp_bypass: false, device_scale_factor: 1,
    context_closed: false, ok: false, cut_off: false, browser_version: browser.version(), navigation: [],
    scroll_steps: [], page_errors: [], failed_requests: [], cookie: {action: 'not checked', clicks: []}};
  const clean = x => { const v = {...x}; delete v.environment; return JSON.stringify(v); };
  try {
    context = await browser.newContext({viewport: {width: viewport.width, height: viewport.height},
      deviceScaleFactor: 1, bypassCSP: false, ignoreHTTPSErrors: false, locale: 'en-US', timezoneId: 'America/Los_Angeles'});
    const network = trackCaptureNetwork(context, request.network_quiet_ms);
    if (setup) await setup(context);
    target = await context.newPage();
    target.on('pageerror', e => record.page_errors.push(String(e.message)));
    target.on('requestfailed', r => record.failed_requests.push({url: r.url(), error: r.failure()?.errorText}));
    target.on('response', r => { if (r.request().isNavigationRequest() && r.frame() === target.mainFrame())
      record.navigation.push({url: r.url(), status: r.status()}); });
    const response = await target.goto(request.url, {waitUntil: 'domcontentloaded', timeout: request.timeout_ms});
    record.http_status = response?.status() ?? null; record.final_url = target.url();
    record.csp_header_present = !!(response && await response.headerValue('content-security-policy'));
    async function observe() {
      const root = await target.evaluate(observePage);
      root.frame_errors = [];
      for (const [index, frame] of target.frames().entries()) {
        if (frame === target.mainFrame()) continue;
        let owner;
        try {
          owner = await frame.frameElement();
          const box = await owner.boundingBox();
          if (!box || box.width <= 0 || box.height <= 0) continue;
          const local = await frame.evaluate(observePage);
          const prefix = 'frame-' + index + ':' + frame.url() + '>';
          const mapped = local.text_nodes.filter(n => !['outside_viewport','hidden'].includes(n.visibility)).map(n => ({
            ...n, id: prefix + n.id, element: prefix + n.element, frame_url: frame.url(),
            bbox: [n.bbox[0] - local.scroll_x + box.x + root.scroll_x,
              n.bbox[1] - local.scroll_y + box.y + root.scroll_y, n.bbox[2], n.bbox[3]],
            reason: 'frame_sample:' + n.reason
          }));
          const covered = await owner.evaluate((e, nodes) => nodes.map(n => {
            const r = e.getBoundingClientRect(), x = r.left + n.x, y = r.top + n.y;
            const hit = document.elementsFromPoint(x, y)[0];
            return x >= 0 && y >= 0 && x < innerWidth && y < innerHeight && hit !== e;
          }), mapped.map(n => ({x: n.bbox[0] - box.x - root.scroll_x + n.bbox[2] / 2,
                                y: n.bbox[1] - box.y - root.scroll_y + n.bbox[3] / 2})));
          root.text_nodes.push(...mapped.map((n, i) => {
            if (n.bbox[1] + n.bbox[3] <= root.scroll_y || n.bbox[1] >= root.scroll_y + viewport.height)
              return {...n, visibility: 'outside_viewport', reason: 'frame_outside_root_viewport'};
            return covered[i] ? {...n, visibility: 'obscured', reason: 'parent_frame_occlusion'} : n;
          }));
        } catch (error) { root.frame_errors.push({frame_url: frame.url(), error: String(error.message)}); }
        finally { if (owner) await owner.dispose(); }
      }
      return root;
    }
    async function settle() {
      const began = Date.now(); let observed;
      do {
        observed = await observe();
        const pending = observed.images.filter(i => i.in_view && !i.complete);
        if (observed.fonts_loaded && pending.length === 0 && network().quiet) break;
        await target.waitForTimeout(100);
      } while (Date.now() - began < request.timeout_ms);
      await target.waitForTimeout(request.settle_ms);
      observed = await observe();
      return {scroll_y: observed.scroll_y, document_height: observed.document_height, fonts_loaded: observed.fonts_loaded,
        pending_images: observed.images.filter(i => i.in_view && (!i.complete || !i.natural_width)), network: network(),
        observation: observed, elapsed_ms: Date.now() - began};
    }
    async function pair(options) {
      const before = await observe(), at = new Date().toISOString();
      if (typeof options === 'function') options = options(before);
      const png = await target.screenshot({type: 'png', timeout: request.timeout_ms, ...options});
      const after = await observe();
      return {before, after, coherent: clean(before) === clean(after), captured_at: at, png_base64: png.toString('base64')};
    }
    await target.evaluate(() => scrollTo(0, 0));
    await target.locator(request.ready_selector).first().waitFor({state: 'visible', timeout: request.timeout_ms});
    record.initial_settle = await settle();
    record.first_screen = await pair({}); // Deliberately untouched: first-time visitor, animations as-is.
    record.cookie.before = [];
    for (const frame of target.frames()) {
      try { record.cookie.before.push({frame_url: frame.url(), ...await frame.evaluate(consentControls, REJECT_LABELS)}); }
      catch (e) { record.cookie.before.push({frame_url: frame.url(), error: String(e.message)}); }
    }
    const consent = record.cookie.before.find(f => f.candidates?.length);
    if (consent) {
      const frame = target.frames().find(f => f.url() === consent.frame_url), candidate = consent.candidates[0];
      const current = await frame.evaluate(consentControls, REJECT_LABELS);
      if (!current.candidates.some(c => c.selector === candidate.selector && c.label === candidate.label))
        throw new Error('CONSENT_CONTROL_CHANGED');
      const control = frame.locator(candidate.selector);
      // The label is rechecked immediately before clicking; no id-only or fuzzy fallback.
      const actual = await control.evaluate(e => String(e.innerText || e.value || e.getAttribute('aria-label') || '').replace(/\s+/g,' ').trim().toLowerCase());
      if (actual !== candidate.label || !REJECT_LABELS.includes(actual)) throw new Error('UNSAFE_CONSENT_CONTROL');
      await control.click({timeout: request.timeout_ms});
      record.cookie.clicks.push({...candidate, frame_url: consent.frame_url, clicked_at: new Date().toISOString()});
      record.cookie.action = 'rejected optional cookies';
      await target.waitForLoadState('domcontentloaded', {timeout: request.timeout_ms}); await settle();
    } else record.cookie.action = record.cookie.before.some(f => f.present) ? 'cookie window left open' : 'no cookie window found';
    record.cookie.after = [];
    for (const frame of target.frames()) {
      try { record.cookie.after.push({frame_url: frame.url(), ...await frame.evaluate(consentControls, REJECT_LABELS)}); }
      catch (e) { record.cookie.after.push({frame_url: frame.url(), error: String(e.message)}); }
    }
    if (record.cookie.clicks.length && record.cookie.after.some(f => f.present)) record.cookie.action = 'reject clicked; cookie window still open';
    const observations = new Map();
    let previousHeight = -1, stable = 0, desiredY = 0;
    while (true) {
      await target.evaluate(y => scrollTo(0, y), desiredY);
      const step = await settle();
      for (const node of step.observation.text_nodes) if (node.visibility !== 'outside_viewport') observations.set(node.id, node);
      const {observation, ...summary} = step; record.scroll_steps.push(summary);
      if (step.document_height >= viewport.height * 25) { record.cut_off = true; break; }
      const atBottom = step.scroll_y + viewport.height >= step.document_height - 1;
      stable = atBottom && step.document_height === previousHeight ? stable + 1 : 0;
      previousHeight = step.document_height;
      if (stable >= 2) break;
      desiredY = atBottom ? step.document_height : step.scroll_y + viewport.height;
    }
    await target.evaluate(() => scrollTo(0, 0)); await settle();
    // Clip to the viewport's width: a visitor who doesn't scroll sideways sees exactly this column.
    record.full_page = await pair(before => ({fullPage: true, animations: 'disabled', caret: 'hide', scale: 'css',
      clip: {x: 0, y: 0, width: viewport.width, height: before.document_height}}));
    const scrollWidth = record.full_page.before.scroll_width;
    record.horizontal_overflow = {scroll_width: scrollWidth, viewport_width: viewport.width,
      overflow_px: Math.max(0, scrollWidth - viewport.width)};
    // Keep source geometry from the screenshot bracket. Outside-viewport visibility comes only from the actual scroll samples.
    record.full_page.text = record.full_page.before.text_nodes.map(node => {
      const sample = observations.get(node.id);
      const visibility = node.visibility === 'outside_viewport' && sample && sample.text === node.text ?
        {visibility: sample.visibility, reason: 'scroll_sample:' + sample.reason} : {visibility: node.visibility, reason: node.reason};
      return {...node, ...visibility, slice_index: Math.floor(Math.max(0, node.bbox[1]) / viewport.height) + 1,
        slice_indices: Array.from({length: Math.max(1, Math.ceil((node.bbox[1] + node.bbox[3]) / viewport.height) - Math.floor(Math.max(0,node.bbox[1]) / viewport.height))},
          (_, i) => Math.floor(Math.max(0,node.bbox[1]) / viewport.height) + 1 + i)};
    });
    record.final_url = target.url(); record.ok = true;
  } catch (error) {
    record.error = String(error.message || error);
    if (target && !target.isClosed() && !record.first_screen) {
      try {
        record.first_screen = {before: await target.evaluate(observePage), coherent: false, diagnostic: true,
          png_base64: (await target.screenshot({type: 'png', timeout: request.timeout_ms})).toString('base64')};
      } catch (e) { record.diagnostic_error = String(e.message); }
    }
  } finally {
    if (context) {
      try { await context.close(); record.context_closed = true; }
      catch (e) { record.ok = false; record.error = 'CONTEXT_CLEANUP_FAILED: ' + e.message; }
    }
    record.elapsed_ms = Date.now() - started;
  }
  return record;
}
