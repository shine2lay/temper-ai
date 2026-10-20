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
    // Version 2 (H3c): a link at any height; the scorer decides from its fill and border whether it is a control.
    if (tag === 'a' && el.hasAttribute('href')) return 'link';
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
    // Rounded corners (version 2's inside pixels): [horizontal, vertical] radius in CSS px for the top-left,
    // top-right, bottom-right and bottom-left corners, percentages resolved against the border box and
    // overlapping radii scaled down as CSS does.
    const b = el.getBoundingClientRect();
    const len = (v, ref) => (v.endsWith('%') ? parseFloat(v) / 100 * ref : parseFloat(v) || 0);
    const corners = ['top-left', 'top-right', 'bottom-right', 'bottom-left'].map((k) => {
      const v = s.getPropertyValue('border-' + k + '-radius').trim().split(/\s+/);
      return [len(v[0] || '0', b.width), len(v[1] || v[0] || '0', b.height)];
    });
    const f = Math.min(1, ...[[0, 1, b.width, 0], [3, 2, b.width, 0], [0, 3, b.height, 1], [1, 2, b.height, 1]].map(
      ([i, j, side, axis]) => { const sum = corners[i][axis] + corners[j][axis]; return sum > side ? side / sum : 1; }));
    return {
      background_color: s.backgroundColor, background_rgba: rgba(s.backgroundColor),
      background_image: s.backgroundImage,
      border_color: s.borderTopColor, border_rgba: rgba(s.borderTopColor), full_border: full, border_widths: bw,
      radii: corners.map(([x, y]) => [r2(x * f), r2(y * f)]),
    };
  };
  // Visible text (version 2, H3c): the part of a line box that is drawn, after the cuts made by `from` (the
  // text's parent, itself included) and its ancestors, as visible() cuts an element. null when nothing is left.
  const drawnPart = (rect, from) => {
    const box = {l: rect.l, t: rect.t, r: rect.r, b: rect.b};
    for (let n = from; n && n.nodeType === 1; n = n.parentElement) {
      const s = cs(n);
      if (s.display === 'none' || parseFloat(s.opacity) === 0) return null;
      if (n === from && s.visibility !== 'visible') return null;
      const pr = n.getBoundingClientRect();
      if (s.clipPath && s.clipPath !== 'none' && /inset\(\s*(50%|100%)/.test(s.clipPath)) return null;
      if ((s.position === 'absolute' || s.position === 'fixed') && s.clip && s.clip !== 'auto') {
        // clip: rect(top, right, bottom, left), offsets from the border box's top-left corner; auto = that edge.
        const m = /rect\(([^)]*)\)/.exec(s.clip);
        if (m) {
          const v = m[1].split(/[\s,]+/).filter(Boolean);
          const at = (i, edge) => (v[i] === undefined || v[i] === 'auto' ? edge : parseFloat(v[i]));
          box.t = Math.max(box.t, pr.top + at(0, 0)); box.r = Math.min(box.r, pr.left + at(1, pr.width));
          box.b = Math.min(box.b, pr.top + at(2, pr.height)); box.l = Math.max(box.l, pr.left + at(3, 0));
        }
      }
      if (s.overflowX !== 'visible') { box.l = Math.max(box.l, pr.left); box.r = Math.min(box.r, pr.right); }
      if (s.overflowY !== 'visible') { box.t = Math.max(box.t, pr.top); box.b = Math.min(box.b, pr.bottom); }
      if (!(box.r > box.l && box.b > box.t)) return null;
      if (s.position === 'fixed') break;
    }
    return box;
  };
  // A text node with a non-space character whose colour is not transparent and of which more than 1 x 1 px is
  // drawn inside the control's box. An input button draws its value (submit and reset: a default label if empty).
  const hasVisibleText = (el) => {
    if (el.tagName.toLowerCase() === 'input') {
      const t = (el.getAttribute('type') || '').toLowerCase();
      return (el.value.trim() !== '' || t === 'submit' || t === 'reset') && rgba(cs(el).color)[3] > 0;
    }
    const own = el.getBoundingClientRect();
    const walk = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    for (let n = walk.nextNode(); n; n = walk.nextNode()) {
      if (!/\S/.test(n.nodeValue)) continue;
      const p = n.parentElement;
      if (!p || rgba(cs(p).color)[3] === 0) continue;
      const range = document.createRange();
      range.selectNodeContents(n);
      for (const r of range.getClientRects()) {
        const cut = {l: Math.max(r.left, own.left), t: Math.max(r.top, own.top),
          r: Math.min(r.right, own.right), b: Math.min(r.bottom, own.bottom)};
        if (!(cut.r - cut.l > 1 && cut.b - cut.t > 1)) continue;
        const d = drawnPart(cut, p);
        if (d && d.r - d.l > 1 && d.b - d.t > 1) return true;
      }
    }
    return false;
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
  const frames2 = () => new Promise((res) => requestAnimationFrame(() => requestAnimationFrame(res)));

  // A11 (d), version 4: motion with a purpose (doc, "Motion with a purpose"). a11dStart runs with
  // these helpers before the page's own scripts and reads document.getAnimations() on every frame;
  // the driver names the step (load, scroll1 to scroll8, hover-press, end). Raw facts only.
  const A11D_SKIP = new Set(['offset', 'easing', 'composite', 'computedOffset']);
  const kebab = (p) => (p === 'cssFloat' ? 'float' : p === 'cssOffset' ? 'offset'
    : p.startsWith('--') ? p : p.replace(/[A-Z]/g, (c) => '-' + c.toLowerCase()));
  // A timing function's largest distance from the diagonal at 0.1, 0.2, ... 0.9, read by the
  // browser on a detached effect (null when it can't be read).
  const devs = new Map();
  const easingDev = (s) => {
    if (devs.has(s)) return devs.get(s);
    let d = null;
    try {
      const a = new Animation(new KeyframeEffect(null, null, {duration: 1000, easing: s, fill: 'both'}), document.timeline);
      d = 0;
      for (let i = 1; i <= 9; i++) {
        a.currentTime = i * 100;
        d = Math.max(d, Math.abs(a.effect.getComputedTiming().progress - i / 10));
      }
      a.cancel();
      d = Math.round(d * 10000) / 10000;
    } catch (e) { d = null; }
    devs.set(s, d);
    return d;
  };
  // What an animation changes: a transition's property; otherwise each keyframe property, except one
  // with the same value in every keyframe, the first (0) and last (1) included.
  const animProps = (a, kfs) => {
    if (typeof a.transitionProperty === 'string') return [a.transitionProperty];
    const vals = new Map();
    for (const k of kfs) {
      for (const p of Object.keys(k)) {
        if (A11D_SKIP.has(p)) continue;
        if (!vals.has(p)) vals.set(p, []);
        vals.get(p).push(String(k[p]));
      }
    }
    const whole = kfs.length >= 2 && kfs[0].computedOffset === 0 && kfs[kfs.length - 1].computedOffset === 1;
    const out = new Set();
    for (const [p, vs] of vals) {
      if (whole && vs.length === kfs.length && vs.every((v) => v === vs[0])) continue;
      out.add(kebab(p));
    }
    return Array.from(out).sort();
  };
  // One animation is one (kind, target, pseudo-element, name, duration, timing functions).
  const a11dRecord = (st, a, e, t) => {
    const timing = e.getTiming();
    const scrollDriven = !!a.timeline && !(a.timeline instanceof DocumentTimeline);
    let dur = null;
    if (!scrollDriven) {
      const d = e.getComputedTiming().duration;
      dur = typeof d === 'number' && isFinite(d) ? r2(d) : null;
    }
    let kfs = [];
    try { kfs = e.getKeyframes(); } catch (x) { kfs = []; }
    const easings = [timing.easing || 'linear'].concat(kfs.slice(0, -1).map((k) => k.easing || 'linear'))
      .map((s) => [s, easingDev(s)]);
    const kind = a.constructor.name;
    const name = a.animationName || a.transitionProperty || a.id || '';
    const pseudo = e.pseudoElement || '';
    const key = JSON.stringify([kind, pseudo, name, dur, easings.map((x) => x[0])]);
    let m = st.byEl.get(t);
    if (!m) { m = new Map(); st.byEl.set(t, m); }
    let rec = m.get(key);
    if (!rec) {
      const it = timing.iterations;
      rec = {
        el: t, anim: a, kind, name, pseudo, duration: dur, iterations: isFinite(it) ? it : 'infinite',
        delay: r2(timing.delay || 0), easings, props: animProps(a, kfs), seen: st.phase, start: null,
        scroll_driven: scrollDriven, progress: scrollDriven ? new Array(st.steps).fill(null) : null,
        first: {selector: selector(t), text: text(t), box: layoutBox(t)},
      };
      m.set(key, rec);
      st.recs.push(rec);
    }
    return rec;
  };
  // Every animation whose target is an element, first seen once it has started (running or finished).
  const a11dSnap = () => {
    const st = window.__a11d;
    if (!st) return 0;
    let n = 0;
    for (const a of document.getAnimations()) {
      let rec = st.anims.get(a);
      if (!rec) {
        const e = a.effect, t = e && e.target;
        if (!t || t.nodeType !== 1) continue;
        if (a.playState !== 'running' && a.playState !== 'finished') continue;
        rec = a11dRecord(st, a, e, t);
        st.anims.set(a, rec);
        n += 1;
      }
      if (rec.start === null && rec.anim === a && typeof a.startTime === 'number') rec.start = a.startTime + rec.delay;
    }
    return n;
  };
  const a11dStart = (steps) => {
    if (window.__a11d) return true;
    const st = {phase: 'load', block: false, steps, recs: [], byEl: new Map(), anims: new WeakMap()};
    window.__a11d = st;
    // The click after a press is cancelled before any of the page's own listeners.
    const stop = (e) => { if (st.block) { e.preventDefault(); e.stopImmediatePropagation(); } };
    window.addEventListener('click', stop, true);
    window.addEventListener('auxclick', stop, true);
    const loop = () => { a11dSnap(); requestAnimationFrame(loop); };
    requestAnimationFrame(loop);
    return true;
  };
  const a11dPhase = (name, block) => {
    a11dSnap();
    window.__a11d.phase = name;
    if (block !== undefined) window.__a11d.block = block;
    return true;
  };
  const a11dScroll = async (steps, pause) => {
    const st = window.__a11d;
    for (let k = 1; k <= steps; k++) {
      a11dPhase('scroll' + k);
      window.scrollTo({left: 0, top: k * innerHeight / 4, behavior: 'instant'});
      await sleep(pause);
      a11dSnap();
      for (const r of st.recs) {
        if (!r.scroll_driven) continue;
        let p = null;
        try { p = r.anim.effect.getComputedTiming().progress; } catch (e) { p = null; }
        r.progress[k - 1] = typeof p === 'number' ? Math.round(p * 10000) / 10000 : null;
      }
    }
    return true;
  };
  // Feedback: the elements, and their values on the element, its first 60 descendants and their
  // rendered ::before and ::after (nodesOf, as for hover states).
  const FB_SEL = 'a[href], button, [role=button], input, select, textarea, summary';
  const FB_PROPS = ['transform', 'translate', 'scale', 'rotate', 'box-shadow', 'filter', 'opacity',
    'color', 'background-color', 'background-image',
    'border-top-color', 'border-right-color', 'border-bottom-color', 'border-left-color',
    'outline-color', 'text-decoration-color', 'text-decoration-line', 'fill', 'stroke'];
  const FB_READ = FB_PROPS.concat(['border-top-style', 'border-top-width', 'border-right-style',
    'border-right-width', 'border-bottom-style', 'border-bottom-width', 'border-left-style',
    'border-left-width', 'outline-style', 'outline-width']);
  const a11dTargets = () => Array.from(document.querySelectorAll(FB_SEL))
    .filter((el) => !el.matches('input[type=hidden]') && !el.disabled && !el.matches(':disabled') &&
      !el.closest('[inert]') && visible(el))
    .map((el) => ({id: idOf(el), sel: selector(el), text: text(el), box: layoutBox(el), select: el.tagName === 'SELECT'}));
  const readFb = (el) => {
    const st = {};
    for (const [n, pseudo, key] of nodesOf(el)) {
      const s = cs(n, pseudo);
      const m = {};
      for (const p of FB_READ) m[p] = s.getPropertyValue(p);
      st[key] = m;
    }
    return st;
  };
  const borderDraws = (m, side) => {
    const s = m['border-' + side + '-style'];
    return s !== 'none' && s !== 'hidden' && parseFloat(m['border-' + side + '-width']) > 0;
  };
  // A property that draws nothing in both states is not compared (as for hover states).
  const fbCompared = (p, a, b) => {
    const side = /^border-(top|right|bottom|left)-color$/.exec(p);
    if (side) return borderDraws(a, side[1]) || borderDraws(b, side[1]);
    if (p === 'outline-color') {
      return [a, b].some((m) => m['outline-style'] !== 'none' && parseFloat(m['outline-width']) > 0);
    }
    if (p === 'text-decoration-color') return [a, b].some((m) => m['text-decoration-line'] !== 'none');
    return true;
  };
  // [node, property, rest, state] for each compared property that differs; a node in one state only
  // (a pseudo-element that appears) is a change too.
  const fbDiff = (a, b) => {
    const out = [];
    for (const k of new Set(Object.keys(a).concat(Object.keys(b)))) {
      const x = a[k] || null, y = b[k] || null;
      if (!x || !y) { out.push([k, 'content', x ? 'present' : 'none', y ? 'present' : 'none']); continue; }
      for (const p of FB_PROPS) if (x[p] !== y[p] && fbCompared(p, x, y)) out.push([k, p, x[p], y[p]]);
    }
    return out;
  };
  // Each recorded animation, its target read at scroll 0 (a removed target as first seen); "load"
  // becomes "load-late" when its active start is more than windowMs after the end of the load event.
  const a11dEnd = async (windowMs) => {
    const st = window.__a11d;
    a11dPhase('end');
    window.scrollTo({left: 0, top: 0, behavior: 'instant'});
    await frames2();
    a11dSnap();
    settle();
    a11dSnap();
    const nav = performance.getEntriesByType('navigation')[0];
    const loadEnd = nav ? nav.loadEventEnd : 0;
    const anims = st.recs.map((r) => {
      const where = r.el.isConnected ? {selector: selector(r.el), text: text(r.el), box: layoutBox(r.el)} : r.first;
      const late = r.seen === 'load' && r.start !== null && r.start - loadEnd > windowMs;
      return {
        kind: r.kind, name: r.name, selector: where.selector, pseudo: r.pseudo, text: where.text, box: where.box,
        duration: r.duration, iterations: r.iterations, delay: r.delay, easings: r.easings, props: r.props,
        seen: late ? 'load-late' : r.seen, scroll_driven: r.scroll_driven, progress: r.progress,
      };
    });
    const page = (el) => el === document.documentElement || el === document.body;
    const smooth = Array.from(document.querySelectorAll('*')).filter((el) => cs(el).scrollBehavior === 'smooth')
      .map((el) => ({selector: selector(el), text: page(el) ? '' : text(el), box: layoutBox(el)}));
    return {vw: innerWidth, vh: innerHeight, anims, smooth};
  };

  window.__bi = {
    idOf, byId, selector, text, pageBox, layoutBox, viewBox, visible, isInteractive, interactive, settle, waitScroll,
    hiddenPoints, active, readState, stateDiff, centreTo, hoverPoint, uiCandidates, uiStyle, hasVisibleText, running,
    transforms, boxOf, videos, scrollOne, sleep, fixedContainer,
    frames2, a11dStart, a11dSnap, a11dPhase, a11dScroll, a11dTargets, readFb, fbDiff, a11dEnd,
    el: (id) => byId[id],
  };
  return true;
}
