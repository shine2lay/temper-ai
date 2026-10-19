() => {
  // In-page helpers for design_homepage_bar_interact.py (Design, queue #79). They install
  // window.__bi and return raw measurements only: no limit and no pass or fail lives here.
  // Definitions: docs/design-homepage-bar-interaction.md.
  if (window.__bi) return true;
  const ids = new Map();
  const byId = [];
  const idOf = (el) => {
    if (!ids.has(el)) { ids.set(el, byId.length); byId.push(el); }
    return ids.get(el);
  };
  const cs = (el, pseudo) => getComputedStyle(el, pseudo || null);

  const selector = (el) => {
    if (!el || el.nodeType !== 1) return '';
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && node !== document.body && node !== document.documentElement) {
      if (node.id && node !== el) { parts.unshift('#' + CSS.escape(node.id)); return parts.join(' > '); }
      const parent = node.parentElement;
      const n = parent ? Array.prototype.indexOf.call(parent.children, node) + 1 : 1;
      parts.unshift(node.tagName.toLowerCase() + ':nth-child(' + n + ')');
      node = parent;
    }
    parts.unshift(node === document.documentElement ? 'html' : 'body');
    return parts.join(' > ');
  };
  const text = (el) => {
    const t = ((el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('alt') ||
      el.getAttribute('title') || el.getAttribute('placeholder') || '') + '').replace(/\s+/g, ' ').trim();
    return t.length > 80 ? t.slice(0, 79) + '\u2026' : t;
  };
  const r2 = (v) => Math.round(v * 100) / 100;
  const pageBox = (el) => {
    const r = el.getBoundingClientRect();
    return [r2(r.left + scrollX), r2(r.top + scrollY), r2(r.width), r2(r.height)];
  };
  const viewBox = (el) => {
    const r = el.getBoundingClientRect();
    return [r2(r.left), r2(r.top), r2(r.width), r2(r.height)];
  };
  // Layout box without transforms (offset box), for elements that move: stays the same run to run.
  const layoutBox = (el) => {
    if (!(el instanceof HTMLElement)) return pageBox(el);
    let x = 0, y = 0;
    for (let n = el; n; n = n.offsetParent) { x += n.offsetLeft; y += n.offsetTop; }
    return [r2(x), r2(y), r2(el.offsetWidth), r2(el.offsetHeight)];
  };
  const fixedContainer = (el) => {
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const p = cs(n).position;
      if (p === 'fixed' || p === 'sticky') return n;
    }
    return null;
  };

  const visible = (el) => {
    const r = el.getBoundingClientRect();
    if (!(r.width > 0 && r.height > 0)) return false;
    let box = {l: r.left, t: r.top, r: r.right, b: r.bottom};
    for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
      const s = cs(n);
      if (s.display === 'none' || s.visibility === 'hidden' || s.visibility === 'collapse' || parseFloat(s.opacity) === 0) return false;
      if (n !== el) {
        const clips = (s.overflowX !== 'visible' || s.overflowY !== 'visible') ||
          (s.clip && s.clip !== 'auto') || (s.clipPath && s.clipPath !== 'none');
        if (clips) {
          const pr = n.getBoundingClientRect();
          if (s.clipPath && s.clipPath !== 'none' && /inset\(\s*(50%|100%)/.test(s.clipPath)) return false;
          if (s.clip && s.clip !== 'auto' && /rect\(\s*0(px)?,?\s*0(px)?,?\s*0(px)?,?\s*0(px)?\s*\)/.test(s.clip)) return false;
          if (s.overflowX !== 'visible') { box.l = Math.max(box.l, pr.left); box.r = Math.min(box.r, pr.right); }
          if (s.overflowY !== 'visible') { box.t = Math.max(box.t, pr.top); box.b = Math.min(box.b, pr.bottom); }
          if (!(box.r > box.l && box.b > box.t)) return false;
        }
      }
      if (cs(n).position === 'fixed') break;
    }
    return true;
  };
  const SEL = 'a[href], button, input, select, textarea, summary, [tabindex]';
  const isInteractive = (el) => {
    if (!el.matches(SEL)) return false;
    if (el.matches('input[type=hidden]')) return false;
    if (el.hasAttribute('tabindex') && !el.matches('a[href], button, input, select, textarea, summary')) {
      const t = parseInt(el.getAttribute('tabindex'), 10);
      if (!(t >= 0)) return false;
    }
    if (el.disabled) return false;
    if (el.closest('[inert]')) return false;
    return visible(el);
  };
  const groupKey = (el) => {
    if (el.matches('input[type=radio]') && el.name) {
      const f = el.form ? idOf(el.form) : 'doc';
      return 'radio:' + f + ':' + el.name;
    }
    return 'el:' + idOf(el);
  };
  const info = (el) => ({id: idOf(el), sel: selector(el), text: text(el), box: pageBox(el)});
  const interactive = () => Array.from(document.querySelectorAll(SEL)).filter(isInteractive)
    .map((el) => Object.assign(info(el), {key: groupKey(el)}));

  const settle = () => {
    for (const a of document.getAnimations()) {
      try {
        const t = a.effect ? a.effect.getComputedTiming() : null;
        if (t && !isFinite(t.endTime)) { a.pause(); a.currentTime = 0; } else { a.finish(); }
      } catch (e) {
        try { a.pause(); a.currentTime = 0; } catch (e2) { /* leave it */ }
      }
    }
    for (const v of document.querySelectorAll('video')) { try { v.pause(); } catch (e) { /* ignore */ } }
    return true;
  };
  const waitScroll = () => new Promise((resolve) => {
    const start = performance.now();
    let last = [scrollX, scrollY], same = 0;
    const tick = () => {
      const now = [scrollX, scrollY];
      same = (now[0] === last[0] && now[1] === last[1]) ? same + 1 : 0;
      last = now;
      if (same >= 3 || performance.now() - start > 1500) resolve(true); else requestAnimationFrame(tick);
    };
    requestAnimationFrame(tick);
  });

  // Five points of the focused element's viewport box; hidden per WCAG 2.4.11 reading.
  const hiddenPoints = (el) => {
    const r = el.getBoundingClientRect();
    const ix = Math.min(4, r.width / 4), iy = Math.min(4, r.height / 4);
    const pts = [[r.left + r.width / 2, r.top + r.height / 2], [r.left + ix, r.top + iy], [r.right - ix, r.top + iy],
      [r.left + ix, r.bottom - iy], [r.right - ix, r.bottom - iy]];
    return pts.map(([x, y]) => {
      if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) return {hidden: true, by: 'outside the viewport'};
      const hit = document.elementFromPoint(x, y);
      if (!hit) return {hidden: true, by: 'nothing'};
      if (hit === el || el.contains(hit)) return {hidden: false};
      const fc = fixedContainer(hit);
      if (fc && !fc.contains(el)) return {hidden: true, by: selector(fc)};
      return {hidden: false};
    });
  };
  const active = () => {
    const el = document.activeElement;
    if (!el || el === document.body || el === document.documentElement) return null;
    const fc = fixedContainer(el);
    const vb = viewBox(el);
    return Object.assign(info(el), {
      vbox: vb, fixed: fc ? selector(fc) : null, key: groupKey(el), points: hiddenPoints(el),
      vw: innerWidth, vh: innerHeight,
    });
  };

  // Hover and focus state reading.
  const PROPS = ['color', 'background-color', 'background-image',
    'border-top-color', 'border-top-style', 'border-top-width', 'border-right-color', 'border-right-style', 'border-right-width',
    'border-bottom-color', 'border-bottom-style', 'border-bottom-width', 'border-left-color', 'border-left-style', 'border-left-width',
    'box-shadow', 'outline-color', 'outline-style', 'outline-width', 'outline-offset',
    'text-decoration-line', 'text-decoration-color', 'text-decoration-style', 'text-decoration-thickness',
    'transform', 'translate', 'scale', 'rotate'];
  const nodesOf = (el) => {
    const out = [[el, null, 'self']];
    const desc = Array.from(el.querySelectorAll('*')).slice(0, 60);
    for (const [i, d] of [el].concat(desc).entries()) {
      if (i > 0) out.push([d, null, 'd' + i]);
      for (const p of ['::before', '::after']) {
        const c = cs(d, p).content;
        if (c && c !== 'none' && c !== 'normal') out.push([d, p, (i > 0 ? 'd' + i : 'self') + p]);
      }
    }
    return out;
  };
  const readState = (el) => {
    const st = {};
    for (const [n, pseudo, key] of nodesOf(el)) {
      const s = cs(n, pseudo);
      const m = {};
      for (const p of PROPS) m[p] = s.getPropertyValue(p);
      st[key] = m;
    }
    return st;
  };
  // Keep only nodes where any property differs (both full maps, so the scorer can apply the
  // "draws nothing" rules); nodes that exist in only one state are kept with null on the other side.
  const stateDiff = (a, b) => {
    const out = {};
    for (const k of new Set(Object.keys(a).concat(Object.keys(b)))) {
      const x = a[k] || null, y = b[k] || null;
      if (!x || !y || PROPS.some((p) => x[p] !== y[p])) out[k] = {rest: x, state: y};
    }
    return out;
  };
  const centreTo = (el) => {
    const r = el.getBoundingClientRect();
    window.scrollTo({left: 0, top: Math.max(0, r.top + scrollY + r.height / 2 - innerHeight / 2), behavior: 'instant'});
  };
  const hoverPoint = (el) => {
    const r = el.getBoundingClientRect();
    const ix = Math.min(4, r.width / 4), iy = Math.min(4, r.height / 4);
    const pts = [[r.left + r.width / 2, r.top + r.height / 2], [r.left + ix, r.top + iy], [r.right - ix, r.top + iy],
      [r.left + ix, r.bottom - iy], [r.right - ix, r.bottom - iy]];
    for (const [x, y] of pts) {
      if (x < 0 || y < 0 || x >= innerWidth || y >= innerHeight) continue;
      const hit = document.elementFromPoint(x, y);
      if (hit && (hit === el || el.contains(hit))) return [x, y];
    }
    return null;
  };

  // UI parts.
  const TEXTLIKE = ['', 'text', 'email', 'search', 'tel', 'url', 'password', 'number', 'date', 'time',
    'datetime-local', 'month', 'week'];
  const uiKind = (el) => {
    const tag = el.tagName.toLowerCase();
    if (tag === 'select' || tag === 'textarea') return 'field';
    if (tag === 'input') {
      const t = (el.getAttribute('type') || '').toLowerCase();
      if (TEXTLIKE.includes(t)) return 'field';
      if (['submit', 'button', 'reset'].includes(t)) return 'button';
      return null;
    }
    if (tag === 'button' || el.getAttribute('role') === 'button') return 'button';
    if (tag === 'a' && el.hasAttribute('href') && el.getBoundingClientRect().height <= 80) return 'button';
    return null;
  };
  // Any CSS colour (rgb, oklch, color(), lab ...) to sRGB [r, g, b, a] by painting it on a canvas.
  const cvs = document.createElement('canvas');
  cvs.width = 1; cvs.height = 1;
  const ctx = cvs.getContext('2d', {willReadFrequently: true});
  const rgba = (c) => {
    if (!c || c === 'transparent') return [0, 0, 0, 0];
    ctx.clearRect(0, 0, 1, 1);
    ctx.fillStyle = '#000';
    ctx.fillStyle = c;
    ctx.fillRect(0, 0, 1, 1);
    const d = ctx.getImageData(0, 0, 1, 1).data;
    return [d[0], d[1], d[2], r2(d[3] / 255)];
  };
  const uiStyle = (el) => {
    const s = cs(el);
    const sides = ['top', 'right', 'bottom', 'left'];
    const full = sides.every((d) => {
      const st = s.getPropertyValue('border-' + d + '-style');
      const w = parseFloat(s.getPropertyValue('border-' + d + '-width')) || 0;
      const c = s.getPropertyValue('border-' + d + '-color');
      return st !== 'none' && st !== 'hidden' && w >= 1 && rgba(c)[3] > 0;
    });
    const bw = sides.map((d) => parseFloat(s.getPropertyValue('border-' + d + '-width')) || 0);
    return {
      background_color: s.backgroundColor, background_rgba: rgba(s.backgroundColor),
      background_image: s.backgroundImage,
      border_color: s.borderTopColor, border_rgba: rgba(s.borderTopColor), full_border: full, border_widths: bw,
    };
  };
  const uiCandidates = () => Array.from(document.querySelectorAll(SEL)).filter(isInteractive)
    .map((el) => ({el, kind: uiKind(el)})).filter((c) => c.kind)
    .map((c) => Object.assign(info(c.el), {kind: c.kind}));

  // Motion.
  const animKey = (a) => {
    const t = a.effect && a.effect.target;
    const pe = a.effect && a.effect.pseudoElement ? a.effect.pseudoElement : '';
    const name = a.animationName || a.transitionProperty || a.id || 'animation';
    return (t ? selector(t) : '?') + pe + '|' + name;
  };
  const running = () => document.getAnimations().filter((a) => a.playState === 'running').map((a) => {
    const t = a.effect ? a.effect.getComputedTiming() : {};
    const tgt = a.effect && a.effect.target;
    return {
      key: animKey(a), target: tgt ? selector(tgt) : null, text: tgt ? text(tgt) : '',
      box: tgt && tgt.getBoundingClientRect ? layoutBox(tgt) : null,
      infinite: !isFinite(t.activeDuration), active_ms: isFinite(t.activeDuration) ? Math.round(t.activeDuration) : null,
      kind: a.constructor.name,
    };
  });
  const TPROPS = ['transform', 'translate', 'scale', 'rotate'];
  const transforms = () => {
    const out = {};
    for (const el of document.querySelectorAll('body *')) {
      const s = cs(el);
      const v = TPROPS.map((p) => s.getPropertyValue(p));
      if (v.some((x) => x && x !== 'none')) out[selector(el)] = {v: v.join(' | '), text: text(el), box: layoutBox(el)};
    }
    return out;
  };
  const boxOf = (sel) => {
    try { const el = document.querySelector(sel); return el ? {text: text(el), box: pageBox(el)} : null; } catch (e) { return null; }
  };
  const videos = () => Array.from(document.querySelectorAll('video')).map((v) => {
    const r = v.getBoundingClientRect();
    return {sel: selector(v), text: text(v), box: pageBox(v), sized: r.width > 0 && r.height > 0,
      paused: v.paused, ended: v.ended, autoplay: v.autoplay, current: r2(v.currentTime)};
  });
  const scrollOne = () => { window.scrollTo({left: 0, top: scrollY + innerHeight, behavior: 'instant'}); return scrollY; };
  const sleep = (ms) => new Promise((res) => setTimeout(res, ms));

  window.__bi = {
    idOf, byId, selector, text, pageBox, layoutBox, viewBox, visible, isInteractive, interactive, settle, waitScroll,
    hiddenPoints, active, readState, stateDiff, centreTo, hoverPoint, uiCandidates, uiStyle, running,
    transforms, boxOf, videos, scrollOne, sleep, fixedContainer,
    el: (id) => byId[id],
  };
  return true;
}
