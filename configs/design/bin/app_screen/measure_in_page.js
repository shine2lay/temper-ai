// Look-only measurement of one screen, evaluated inside the page by existing_capture.mjs (design_app_screen_v1
// stage 2). Moved in from Design #170's RollCall read (results/rollcall-mobile-redesign-20261104/current/tools,
// left as it was) and made product-agnostic: the page's main element, its areas (tabbar, topbar, pinned...),
// the key regions to locate and the loading words come from the product's app file as `cfg`.
// Returns chrome heights, first-view content, text-size histogram, small targets, overflow, truncation, blocks,
// key-region tops, error messages and the visible text runs. bin/app_screen/existing_measures.py turns it into
// the audit's measures.
(cfg) => {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const areas = cfg.areas || {};
  const visible = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) return false;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.opacity) === 0) return false;
    if (el.closest('.sr-only, .skip')) return false;
    return true;
  };
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const label = (el) => clean(el.getAttribute('aria-label') || el.innerText || el.value || el.title || '').slice(0, 50);
  const where = (el) => {
    for (const [name, sel] of Object.entries(areas)) if (el.closest(sel)) return name;
    return el.closest(cfg.main) ? 'main' : 'other';
  };
  const rectOf = (sel) => {
    const el = sel ? document.querySelector(sel) : null;
    if (!visible(el)) return 0;
    return Math.round(el.getBoundingClientRect().height);
  };
  const main = document.querySelector(cfg.main);
  const tabbar = areas.tabbar ? document.querySelector(areas.tabbar) : null;
  const tabbarH = visible(tabbar) ? Math.round(tabbar.getBoundingClientRect().height) : 0;
  const mainTop = main ? Math.round(main.getBoundingClientRect().top + window.scrollY) : 0;
  const foldBottom = vh - tabbarH;
  const chrome = {
    areas: Object.fromEntries(Object.entries(areas).map(([name, sel]) => [name, rectOf(sel)])),
    tabbar: tabbarH,
    tabbarRows: (() => {
      if (!tabbarH) return 0;
      const tops = new Set([...tabbar.querySelectorAll('a')].filter(visible).map((a) => Math.round(a.getBoundingClientRect().top)));
      return tops.size;
    })(),
    tabbarItems: tabbarH ? [...tabbar.querySelectorAll('a')].filter(visible).length : 0,
    mainTop,
    contentLeftInFirstView: Math.max(0, foldBottom - mainTop),
    contentShareOfFirstView: +(Math.max(0, foldBottom - mainTop) / vh).toFixed(2),
  };

  // Text runs
  const runs = [];
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode;
    const text = clean(node.textContent);
    if (!text) continue;
    const el = node.parentElement;
    if (!el || !visible(el)) continue;
    if (el.closest('script, style, noscript')) continue;
    const range = document.createRange();
    range.selectNodeContents(node);
    const r = range.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;
    const cs = getComputedStyle(el);
    runs.push({
      size: parseFloat(cs.fontSize),
      weight: cs.fontWeight,
      family: cs.fontFamily.split(',')[0].replace(/["']/g, '').trim(),
      top: Math.round(r.top + window.scrollY),
      bottom: Math.round(r.bottom + window.scrollY),
      area: where(el),
      cls: (el.id ? '#' + el.id : el.classList.length ? '.' + [...el.classList].join('.') : el.tagName.toLowerCase()),
      text: text.slice(0, 60),
      full: text.slice(0, 240),
      len: text.length,
    });
  }
  const hist = (rows) => {
    const h = {};
    for (const r of rows) h[r.size] = (h[r.size] || 0) + 1;
    return Object.fromEntries(Object.entries(h).sort((a, b) => +a[0] - +b[0]));
  };
  const typeSummary = (rows) => ({
    total: rows.length,
    histogram: hist(rows),
    under12: rows.filter((r) => r.size < 12).length,
    under14: rows.filter((r) => r.size < 14).length,
    under16: rows.filter((r) => r.size < 16).length,
    // body-like: a sentence-length run (40+ characters) in the page body
    bodyLikeRuns: rows.filter((r) => r.len >= 40 && r.area === 'main').length,
    bodyLikeUnder16: rows.filter((r) => r.len >= 40 && r.area === 'main' && r.size < 16).length,
    distinctSizes: [...new Set(rows.map((r) => r.size))].length,
    smallestPx: rows.length ? Math.min(...rows.map((r) => r.size)) : null,
    smallest: rows.filter((r) => r.size < 12).sort((a, b) => a.size - b.size).slice(0, 8).map((r) => ({ size: r.size, area: r.area, cls: r.cls, text: r.text })),
    families: Object.entries(rows.reduce((m, r) => ((m[r.family] = (m[r.family] || 0) + 1), m), {})).sort((a, b) => b[1] - a[1]).slice(0, 4),
  });
  const firstViewRuns = runs.filter((r) => r.top < foldBottom && r.bottom > 0);
  const firstViewMainRuns = firstViewRuns.filter((r) => r.area === 'main');

  // Interactive targets
  const interactiveSel = 'a[href], button, input:not([type=hidden]), select, textarea, summary, [role=button], [role=tab], [role=link], [role=switch], [tabindex]:not([tabindex="-1"])';
  const targets = [...document.querySelectorAll(interactiveSel)].filter(visible);
  const small = [];
  for (const el of targets) {
    const r = el.getBoundingClientRect();
    if (r.width >= 24 && r.height >= 24) continue;
    const cs = getComputedStyle(el);
    const parentText = (el.parentElement?.innerText || '').trim().length;
    const ownText = (el.innerText || '').trim().length;
    const inline = cs.display === 'inline' && parentText > ownText + 10;
    small.push({ w: Math.round(r.width), h: Math.round(r.height), inline, area: where(el), tag: el.tagName.toLowerCase(), label: label(el), top: Math.round(r.top + window.scrollY) });
  }
  const firstViewTargets = targets.filter((el) => {
    const r = el.getBoundingClientRect();
    return r.top < foldBottom && r.bottom > 0 && where(el) === 'main';
  });

  // Horizontal overflow: elements sticking out past the viewport, not clipped by a scrolling ancestor
  const clippedByScroller = (el) => {
    for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
      const ox = getComputedStyle(p).overflowX;
      if (ox === 'auto' || ox === 'scroll' || ox === 'hidden' || ox === 'clip') return p;
    }
    return null;
  };
  const overflowing = [];
  const scrollers = new Map();
  const overflowSel = [cfg.main, ...Object.entries(areas).filter(([name]) => name !== 'tabbar').map(([, sel]) => sel)].map((s) => `${s} *`).join(', ');
  for (const el of document.querySelectorAll(overflowSel)) {
    if (!visible(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.right <= vw + 1 && r.left >= -1) continue;
    const sc = clippedByScroller(el);
    if (sc) {
      const key = sc.className || sc.tagName;
      if (!scrollers.has(sc)) scrollers.set(sc, { cls: String(key).slice(0, 60), area: where(sc), scrollW: sc.scrollWidth, clientW: sc.clientWidth });
      continue;
    }
    const parent = el.parentElement;
    const pr = parent?.getBoundingClientRect();
    if (pr && pr.right > vw + 1) continue; // report the outermost offender only
    overflowing.push({ cls: (el.className && String(el.className).slice(0, 60)) || el.tagName.toLowerCase(), right: Math.round(r.right), text: clean(el.innerText).slice(0, 50) });
  }
  const sideScrollers = [...scrollers.values()].filter((s) => s.scrollW > s.clientW + 1);

  // Truncated text
  const truncated = [];
  for (const el of document.querySelectorAll('body *')) {
    if (!visible(el) || el.children.length > 3) continue;
    const text = clean(el.innerText);
    if (!text) continue;
    const cs = getComputedStyle(el);
    const clamp = cs.webkitLineClamp && cs.webkitLineClamp !== 'none';
    const ellipsis = cs.textOverflow === 'ellipsis';
    const cutW = el.scrollWidth > el.clientWidth + 1 && (ellipsis || cs.overflowX === 'hidden' || cs.overflow === 'hidden');
    const cutH = clamp && el.scrollHeight > el.clientHeight + 1;
    if (cutW || cutH) truncated.push({ area: where(el), cls: (el.className && String(el.className).slice(0, 50)) || el.tagName.toLowerCase(), how: cutH ? 'line-clamp' : ellipsis ? 'ellipsis' : 'clipped', axis: cutH ? 'height' : 'width', shown: cutH ? el.clientHeight : el.clientWidth, needs: cutH ? el.scrollHeight : el.scrollWidth, text: text.slice(0, 70) });
  }

  // Blocks: the page's top-level pieces, from main down through single-child wrappers
  let root = main;
  while (root && root.children.length === 1) root = root.children[0];
  const blocks = root
    ? [...root.children].filter(visible).map((el) => {
        const r = el.getBoundingClientRect();
        const isDetails = el.tagName === 'DETAILS';
        const collapsedToggle = el.querySelector(':scope > button[aria-expanded="false"], :scope > header button[aria-expanded="false"], :scope > summary');
        return {
          tag: el.tagName.toLowerCase(),
          cls: String(el.className || '').slice(0, 50),
          top: Math.round(r.top + window.scrollY),
          h: Math.round(r.height),
          collapsed: isDetails ? !el.open : false,
          hasToggle: !!collapsedToggle,
          heading: clean(el.querySelector('h1,h2,h3,h4,.card-title,.section-title')?.innerText).slice(0, 60),
          text: clean(el.innerText).slice(0, 80),
        };
      })
    : [];
  const alwaysOpen = blocks.filter((b) => !b.collapsed && b.h > 40).length;
  const detailsInMain = main ? [...main.querySelectorAll('details')].filter(visible) : [];

  // Key regions (what the product says matters first, e.g. RollCall's attention list): top from the page top
  const keyRegions = {};
  for (const [name, sel] of Object.entries(cfg.key_regions || {})) {
    const el = [...document.querySelectorAll(sel)].find(visible);
    keyRegions[name] = el ? { top: Math.round(el.getBoundingClientRect().top + window.scrollY), cls: String(el.className || el.tagName).slice(0, 60) } : null;
  }

  // Error messages, and whether each offers a way out (a button or link in it or in its parent)
  const errorSel = cfg.error_selector || '[role="alert"]';
  const errors = [...document.querySelectorAll(errorSel)].filter(visible).filter((el) => clean(el.innerText)).map((el) => {
    const scope = el.parentElement || el;
    const actions = [...scope.querySelectorAll('a[href], button, [role=button]')].filter(visible).length;
    return { text: clean(el.innerText).slice(0, 120), actions };
  });

  const docH = document.scrollingElement.scrollHeight;
  const h1 = document.querySelector(`${cfg.main} h1`);
  const loadingRe = cfg.loading_text ? new RegExp(cfg.loading_text) : null;
  return {
    url: location.pathname + location.search,
    viewport: { w: vw, h: vh },
    pageHeight: docH,
    screensTall: +(docH / vh).toFixed(1),
    horizontalScroll: document.scrollingElement.scrollWidth > vw + 1 ? document.scrollingElement.scrollWidth : 0,
    chrome,
    firstView: {
      h1: h1 ? clean(h1.innerText).slice(0, 80) : '',
      headings: [...document.querySelectorAll(`${cfg.main} h1, ${cfg.main} h2, ${cfg.main} h3`)].filter(visible).filter((h) => h.getBoundingClientRect().top < foldBottom).map((h) => clean(h.innerText).slice(0, 60)),
      mainText: firstViewMainRuns.map((r) => r.text).join(' · ').slice(0, 600),
      mainTargets: firstViewTargets.map(label).filter(Boolean).slice(0, 20),
      type: typeSummary(firstViewRuns),
    },
    type: typeSummary(runs),
    targets: {
      total: targets.length,
      under24: small.length,
      under24NotInline: small.filter((s) => !s.inline).length,
      byArea: small.reduce((m, s) => ((m[s.area] = (m[s.area] || 0) + 1), m), {}),
      examples: small.filter((s) => !s.inline).slice(0, 12),
    },
    overflow: { outside: overflowing.slice(0, 10), outsideCount: overflowing.length, sideScrollers: sideScrollers.slice(0, 8) },
    truncated: { count: truncated.length, items: truncated.slice(0, 12) },
    blocks: { count: blocks.length, alwaysOpen, details: detailsInMain.length, detailsOpen: detailsInMain.filter((d) => d.open).length, list: blocks.slice(0, 20) },
    keyRegions,
    errors,
    loadingWords: loadingRe ? loadingRe.test(document.body.innerText) : false,
    fontsLoaded: [...new Set([...document.fonts].filter((f) => f.status === 'loaded').map((f) => f.family.replace(/["']/g, '')))],
    runs: runs.slice(0, 800).map((r) => ({ text: r.full, size: r.size, top: r.top, area: r.area, first: r.top < foldBottom && r.bottom > 0 })),
  };
}
