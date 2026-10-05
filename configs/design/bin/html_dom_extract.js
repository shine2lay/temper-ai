// html_dom_extract.js (design role): read a rendered page into a "scene" that
// html_to_penpot.py turns into editable Penpot layers. Runs inside the page
// (page.evaluate) after fonts and images have loaded, at scroll position 0.
//
// The scene is a tree of nodes in page pixels: boards (sections, components,
// decorated boxes), groups, rects, text (paragraphs, style runs and the
// browser's own line boxes) and paths (inline SVG, normalised to absolute
// M/L/C/Z in page coordinates). Anything it cannot carry faithfully is listed
// in `issues` so the conversion report shows it instead of hiding it.
(opts) => {
  opts = opts || {};
  const sx = window.scrollX, sy = window.scrollY;
  const doc = document.documentElement;
  const W = doc.clientWidth;
  const H = Math.max(doc.scrollHeight, document.body ? document.body.scrollHeight : 0);
  const issues = [];
  const stats = {elements: 0, boards: 0, groups: 0, rects: 0, texts: 0, paths: 0, images: 0};
  const SKIP = new Set(['script', 'style', 'noscript', 'template', 'head', 'meta', 'link', 'title', 'base']);
  const ISSUE_LIMIT = 200;
  const issue = (kind, el, detail) => {
    if (issues.length < ISSUE_LIMIT) issues.push({kind, where: where(el), detail: detail || ''});
  };
  const where = (el) => {
    if (!el || !el.tagName) return '';
    const parts = [];
    for (let x = el; x && x !== document.body && parts.length < 4; x = x.parentElement) {
      let s = x.tagName.toLowerCase();
      if (x.id) { parts.unshift(s + '#' + x.id); break; }
      if (x.dataset && x.dataset.name) { parts.unshift(s + '[data-name="' + x.dataset.name + '"]'); break; }
      if (x.classList && x.classList.length) s += '.' + [...x.classList].slice(0, 2).join('.');
      parts.unshift(s);
    }
    return parts.join(' > ');
  };
  const r2 = (v) => Math.round(v * 100) / 100;
  const r4 = (v) => Math.round(v * 10000) / 10000;
  const box = (r) => ({x: r2(r.left + sx), y: r2(r.top + sy), w: r2(r.width), h: r2(r.height)});
  const clean = (s) => (s || '').replace(/\s+/g, ' ').trim();
  const short = (s, n) => { s = clean(s); return s.length > n ? s.slice(0, n - 1).trimEnd() + '…' : s; };
  // HTML white space only (CSS collapses these); a no-break space is kept like a letter
  const SPACE = /[ \t\n\r\f]/;
  const trimSpace = (s) => s.replace(/^[ \t\n\r\f]+|[ \t\n\r\f]+$/g, '');

  // ---------- colours ----------
  const parseColor = (v) => {
    if (!v) return null;
    v = v.trim();
    let m = v.match(/^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)(?:\s*[,/]\s*([\d.]+%?))?\s*\)$/);
    if (m) {
      let a = m[4] === undefined ? 1 : (m[4].endsWith('%') ? parseFloat(m[4]) / 100 : parseFloat(m[4]));
      const hex = '#' + [m[1], m[2], m[3]].map((c) => Math.max(0, Math.min(255, Math.round(parseFloat(c)))).toString(16).padStart(2, '0')).join('').toUpperCase();
      return {color: hex, opacity: r2(a)};
    }
    m = v.match(/^#([0-9a-f]{3,8})$/i);
    if (m) {
      let h = m[1];
      if (h.length <= 4) h = h.split('').map((c) => c + c).join('');
      const a = h.length === 8 ? parseInt(h.slice(6, 8), 16) / 255 : 1;
      return {color: '#' + h.slice(0, 6).toUpperCase(), opacity: r2(a)};
    }
    // color(srgb ...), oklch(...), named colours: let the browser normalise.
    const probe = document.createElement('i');
    probe.style.color = v;
    if (!probe.style.color) return null;
    document.body.appendChild(probe);
    const out = getComputedStyle(probe).color;
    probe.remove();
    return out && out !== v ? parseColor(out) : null;
  };
  const visibleColor = (c) => c && c.opacity > 0.001;

  // ---------- CSS custom properties (become shared colours) ----------
  const vars = [];
  const seenVar = new Set();
  const rootStyle = getComputedStyle(doc);
  for (const sheet of document.styleSheets) {
    let rules;
    try { rules = sheet.cssRules; } catch (e) { issue('stylesheet-unreadable', null, String(sheet.href || '')); continue; }
    const walkRules = (list) => {
      for (const rule of list) {
        if (rule.cssRules && !rule.selectorText) { walkRules(rule.cssRules); continue; }
        if (!rule.style || !rule.selectorText) continue;
        if (!/^(:root|html)$/.test(rule.selectorText.trim())) continue;
        for (let i = 0; i < rule.style.length; i++) {
          const name = rule.style[i];
          if (!name.startsWith('--') || seenVar.has(name)) continue;
          seenVar.add(name);
          const value = rootStyle.getPropertyValue(name).trim();
          const c = /gradient|url\(/.test(value) ? null : parseColor(value);
          if (c) vars.push({name, value, color: c.color, opacity: c.opacity});
        }
      }
    };
    walkRules(rules);
  }

  // ---------- fonts (only faces that actually loaded) ----------
  const faceRules = [];
  for (const sheet of document.styleSheets) {
    let rules;
    try { rules = sheet.cssRules; } catch (e) { continue; }
    for (const rule of rules) {
      if (rule.constructor && rule.constructor.name === 'CSSFontFaceRule') {
        const fam = clean(rule.style.getPropertyValue('font-family')).replace(/^["']|["']$/g, '');
        const src = rule.style.getPropertyValue('src');
        const url = (src.match(/url\(\s*["']?([^"')]+)["']?\s*\)/) || [])[1];
        const base = sheet.href || location.href;
        faceRules.push({family: fam, weight: clean(rule.style.getPropertyValue('font-weight')) || '400',
          style: clean(rule.style.getPropertyValue('font-style')) || 'normal', url: url ? new URL(url, base).href : null});
      }
    }
  }
  const loadedFamilies = new Set();
  const fonts = [];
  for (const f of document.fonts) {
    if (f.status !== 'loaded') continue;
    const fam = f.family.replace(/^["']|["']$/g, '');
    loadedFamilies.add(fam.toLowerCase());
    const rule = faceRules.find((r) => r.family.toLowerCase() === fam.toLowerCase() && String(r.weight) === String(f.weight) && r.style === f.style);
    fonts.push({family: fam, weight: String(f.weight), style: f.style, url: rule ? rule.url : null});
  }
  const usedFonts = new Map();
  const familyOf = (cs, el) => {
    const list = cs.fontFamily.split(',').map((s) => s.trim().replace(/^["']|["']$/g, ''));
    for (const fam of list) {
      if (loadedFamilies.has(fam.toLowerCase())) return fam;
    }
    issue('font-not-loaded', el, cs.fontFamily);
    return list[0];
  };

  // ---------- gradients / backgrounds ----------
  const splitTop = (s) => {
    const out = []; let depth = 0, cur = '';
    for (const ch of s) {
      if (ch === '(') depth++;
      if (ch === ')') depth--;
      if (ch === ',' && depth === 0) { out.push(cur.trim()); cur = ''; } else cur += ch;
    }
    if (cur.trim()) out.push(cur.trim());
    return out;
  };
  const len = (v, ref) => {
    v = v.trim();
    if (v.endsWith('%')) return parseFloat(v) / 100 * ref;
    if (v.endsWith('px')) return parseFloat(v);
    if (v === '0') return 0;
    return NaN;
  };
  const stopsOf = (parts, lineLength) => {
    const stops = [];
    for (const p of parts) {
      const m = p.match(/^(rgba?\([^)]*\)|#[0-9a-fA-F]+|[a-z]+(?:\([^)]*\))?)\s*(.*)$/);
      if (!m) return null;
      const c = parseColor(m[1]);
      if (!c) return null;
      const positions = m[2] ? m[2].split(/\s+/).filter(Boolean) : [];
      if (!positions.length) stops.push({color: c.color, opacity: c.opacity, offset: null});
      for (const pos of positions) {
        const px = len(pos, lineLength);
        stops.push({color: c.color, opacity: c.opacity, offset: Number.isFinite(px) && lineLength ? px / lineLength : null});
      }
    }
    if (!stops.length) return null;
    if (stops[0].offset === null) stops[0].offset = 0;
    if (stops[stops.length - 1].offset === null) stops[stops.length - 1].offset = 1;
    for (let i = 1; i < stops.length - 1; i++) {
      if (stops[i].offset !== null) continue;
      let j = i; while (stops[j].offset === null) j++;
      const a = stops[i - 1].offset, b = stops[j].offset;
      for (let k = i; k < j; k++) stops[k].offset = a + (b - a) * (k - i + 1) / (j - i + 1);
    }
    let last = 0;
    for (const s of stops) { s.offset = r2(Math.max(last, Math.min(1, s.offset))); last = s.offset; }
    // CSS mixes gradient colours premultiplied, so a fully transparent stop only fades the colours next
    // to it. SVG (Penpot) mixes colour and opacity apart: a transparent stop takes its neighbour's colour
    // (two stops at one offset when the neighbours differ), else the fade passes through grey.
    const seen = (from, step) => { for (let j = from; j >= 0 && j < stops.length; j += step) if (stops[j].opacity > 0.001) return stops[j]; return null; };
    const out = [];
    stops.forEach((s, i) => {
      if (s.opacity > 0.001) { out.push(s); return; }
      const prev = seen(i - 1, -1), next = seen(i + 1, 1);
      if (prev && next && prev.color !== next.color) {
        out.push({color: prev.color, opacity: 0, offset: s.offset}, {color: next.color, opacity: 0, offset: s.offset});
      } else {
        out.push({color: (prev || next || s).color, opacity: 0, offset: s.offset});
      }
    });
    return out;
  };
  const linear = (args, w, h) => {
    let parts = splitTop(args);
    let angle = 180;
    const first = parts[0];
    const dirs = {'to top': 0, 'to right': 90, 'to bottom': 180, 'to left': 270,
      'to top right': null, 'to right top': null, 'to bottom right': null, 'to right bottom': null,
      'to bottom left': null, 'to left bottom': null, 'to top left': null, 'to left top': null};
    if (/^-?[\d.]+(deg|turn|rad|grad)$/.test(first)) {
      const n = parseFloat(first);
      angle = first.endsWith('turn') ? n * 360 : first.endsWith('rad') ? n * 180 / Math.PI : first.endsWith('grad') ? n * 0.9 : n;
      parts = parts.slice(1);
    } else if (first in dirs) {
      if (dirs[first] !== null) angle = dirs[first];
      else {
        const v = first.includes('top') ? -1 : 1, hz = first.includes('left') ? -1 : 1;
        // Corner directions: the gradient line is perpendicular to the diagonal
        // through the other two corners, so its direction is (hz*h, v*w).
        angle = (Math.atan2(hz * h, -v * w) * 180 / Math.PI + 360) % 360;
      }
      parts = parts.slice(1);
    }
    const t = angle * Math.PI / 180;
    const L = Math.abs(w * Math.sin(t)) + Math.abs(h * Math.cos(t));
    const dx = Math.sin(t), dy = -Math.cos(t);
    const stops = stopsOf(parts, L);
    if (!stops || !L) return null;
    // Penpot draws gradients in the shape's unit box (SVG objectBoundingBox), where colour
    // lines stay perpendicular to the vector in unit space. CSS keeps them perpendicular in
    // pixels. Position t = A(u - .5) + B(v - .5) + .5 is linear in unit space, so the unit
    // vector (A, B) / (A^2 + B^2) through the centre reproduces CSS exactly, corners included.
    const A = w * dx / L, B = h * dy / L, n = A * A + B * B;
    const vx = A / n, vy = B / n;
    return {type: 'linear', start: [r4(0.5 - vx / 2), r4(0.5 - vy / 2)],
      end: [r4(0.5 + vx / 2), r4(0.5 + vy / 2)], width: 1, stops};
  };
  const radial = (args, w, h) => {
    let parts = splitTop(args);
    let cx = 0.5, cy = 0.5, shape = 'ellipse', size = [];
    const head = parts[0];
    if (!/^(rgba?\(|#)/.test(head)) {
      parts = parts.slice(1);
      const hm = head.match(/^(.*?)(?:^|\s)at\s+(.*)$/);
      const pre = (hm ? hm[1] : head).trim(), at = hm ? hm[2] : null;
      size = pre ? pre.split(/\s+/) : [];
      if (size.includes('circle')) shape = 'circle';
      if (at) {
        const kw = {left: 0, center: 0.5, right: 1, top: 0, bottom: 1};
        const [ax, ay] = at.trim().split(/\s+/);
        const conv = (v, ref) => v in kw ? kw[v] : (Number.isFinite(len(v, ref)) ? len(v, ref) / ref : 0.5);
        cx = conv(ax || 'center', w); cy = conv(ay || ax || 'center', h);
        if ((ax === 'top' || ax === 'bottom') && !ay) { cy = kw[ax]; cx = 0.5; }
      }
    }
    // Ending shape (CSS Images 3): explicit lengths, or an extent keyword (farthest-corner by default).
    const px = cx * w, py = cy * h;
    const near = [Math.min(Math.abs(px), Math.abs(w - px)), Math.min(Math.abs(py), Math.abs(h - py))];
    const far = [Math.max(Math.abs(px), Math.abs(w - px)), Math.max(Math.abs(py), Math.abs(h - py))];
    const lens = size.filter((t) => !/^(circle|ellipse|(closest|farthest)-(side|corner))$/.test(t));
    const extent = size.find((t) => /^(closest|farthest)-(side|corner)$/.test(t)) || 'farthest-corner';
    if (lens.length === 1 && !size.includes('ellipse')) shape = 'circle';
    let rx, ry;
    if (lens.length) {
      rx = len(lens[0], w);
      ry = shape === 'circle' ? rx : len(lens[1] || lens[0], h);
    } else if (shape === 'circle') {
      rx = ry = extent === 'closest-side' ? Math.min(...near) : extent === 'farthest-side' ? Math.max(...far)
        : extent === 'closest-corner' ? Math.hypot(...near) : Math.hypot(...far);
    } else {
      const k = /corner$/.test(extent) ? Math.SQRT2 : 1;
      [rx, ry] = (/^closest/.test(extent) ? near : far).map((v) => v * k);
    }
    if (!(rx > 0.01) || !(ry > 0.01)) return null;
    // Stop lengths run along the gradient ray, which points right: 100% is the horizontal radius.
    const stops = stopsOf(parts, rx);
    if (!stops) return null;
    return {type: 'radial', start: [r2(cx), r2(cy)], end: [r2(cx), r2(cy + ry / h)], width: r2((rx / w) / (ry / h)), stops};
  };
  // ---------- backgrounds ----------
  // Background layers (CSS lists the top one first). Penpot fills carry a colour, a gradient drawn
  // once over the whole box and an image that covers the box. Layers above the first one they can't
  // carry (tiles, repeating gradients, positioned images, other kinds) keep their order as runs: a
  // picture of those layers (a raster texture, counted as an issue) or native fills on a layer of
  // their own. The page body and form controls keep the old approximations (layered false).
  const textures = [];
  const fnv = (s) => {
    let h = 0x811c9dc5;
    for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 0x01000193) >>> 0; }
    return h.toString(16).padStart(8, '0');
  };
  const FULL_SIZE = /^(auto|auto auto|100%|100% 100%|100% auto|auto 100%|cover|contain)$/;
  const pickOf = (list, i) => (list.length ? list[i % list.length] : '').trim();
  // The box drawn alone in another page (same size, borders, padding, corners, those layers only),
  // saved as <key>.png next to the scene.
  const texture = (el, cs, rect, ids, lists) => {
    const val = (k) => ids.map((i) => pickOf(lists[k], i)).join(', ');
    const w = r2(rect.width), h = r2(rect.height);
    const widths = ['Top', 'Right', 'Bottom', 'Left'].map((s) => (parseFloat(cs['border' + s + 'Width']) || 0) + 'px').join(' ');
    const pad = ['Top', 'Right', 'Bottom', 'Left'].map((s) => cs['padding' + s]).join(' ');
    const css = `position:absolute;left:0;top:0;margin:0;box-sizing:border-box;width:${w}px;height:${h}px;` +
      `border-style:solid;border-color:transparent;border-width:${widths};padding:${pad};border-radius:${cs.borderRadius};` +
      `background-color:transparent;background-image:${val('image')};background-size:${val('size')};` +
      `background-position:${val('position')};background-repeat:${val('repeat')};background-origin:${val('origin')};` +
      `background-clip:${val('clip')}`;
    const key = `tex-${Math.round(w)}x${Math.round(h)}-${fnv(css)}`;
    if (!textures.some((t) => t.key === key)) textures.push({key, w, h, css});
    issue('background-rasterized', el, val('image').slice(0, 100));
    return key + '.png';
  };
  const bgPlan = (cs, el, rect, layered) => {
    const base = [], runs = [];
    const bg = parseColor(cs.backgroundColor);
    if (visibleColor(bg)) base.push({type: 'color', color: bg.color, opacity: bg.opacity});
    if (!cs.backgroundImage || cs.backgroundImage === 'none') return {base, runs};
    // Size, repeat and position are per-layer lists that repeat when shorter (CSS Backgrounds 3).
    const L = {image: splitTop(cs.backgroundImage), size: splitTop(cs.backgroundSize), position: splitTop(cs.backgroundPosition),
      repeat: splitTop(cs.backgroundRepeat), origin: splitTop(cs.backgroundOrigin), clip: splitTop(cs.backgroundClip)};
    if (/fixed/.test(cs.backgroundAttachment || '')) issue('background-fixed-approximated', el, cs.backgroundAttachment);
    const add = (raster, item) => {
      const last = runs[runs.length - 1];
      if (!raster && !runs.length) base.push(item);
      else if (last && last.raster === raster) (raster ? last.ids : last.fills).push(item);
      else runs.push(raster ? {raster, ids: [item]} : {raster, fills: [item]});
    };
    for (let i = L.image.length - 1; i >= 0; i--) {  // fills go bottom to top
      const layer = L.image[i], size = pickOf(L.size, i), repeat = pickOf(L.repeat, i), position = pickOf(L.position, i);
      if (layer === 'none') continue;
      const shifted = /calc|[1-9][\d.]*px/.test(position);
      let m, exact = null, approx = null, why = 'background-unsupported';
      if ((m = layer.match(/^(repeating-)?(linear|radial)-gradient\((.*)\)$/s))) {
        const g = m[2] === 'linear' ? linear(m[3], rect.width, rect.height) : radial(m[3], rect.width, rect.height);
        if (g && !m[1] && FULL_SIZE.test(size) && !shifted) exact = g;
        else if (g && !m[1]) { approx = g; why = 'background-tile-approximated'; }
        else why = 'gradient-approximated';
      } else if ((m = layer.match(/^url\(\s*["']?([^"')]+)["']?\s*\)$/))) {
        const img = {type: 'image', src: new URL(m[1], location.href).href, fit: size === 'contain' ? 'contain' : (size === 'cover' ? 'cover' : 'fill')};
        if (/^(cover|contain|100% 100%)$/.test(size)) {
          exact = img;
          if (/^(cover|contain)$/.test(size) && !/^(50% 50%|center( center)?)$/.test(position)) issue('background-position-approximated', el, position);
        } else { approx = img; why = 'background-repeat-approximated'; }
      }
      if (exact) add(false, exact);
      else if (layered) add(true, i);
      else {
        if (approx) add(false, approx);
        issue(why, el, why === 'background-repeat-approximated' ? size + ' ' + repeat : layer.slice(0, 80));
      }
    }
    for (const run of runs) if (run.raster) run.src = texture(el, cs, rect, run.ids.slice().sort((a, b) => a - b), L);
    return {base, runs};
  };

  // ---------- corners and outlines (paths in page pixels) ----------
  const KAPPA = 0.5522847498;  // a quarter ellipse as one cubic
  const pt = (x, y) => r2(x) + ' ' + r2(y);
  const arc = (C, P0, P1) => 'C' + pt(P0[0] + KAPPA * (C[0] - P0[0]), P0[1] + KAPPA * (C[1] - P0[1])) + ' ' +
    pt(P1[0] + KAPPA * (C[0] - P1[0]), P1[1] + KAPPA * (C[1] - P1[1])) + ' ' + pt(P1[0], P1[1]);
  // Corner k (tl, tr, br, bl) of a rounded box: the corner point, where its curve leaves the side
  // before it (a) and where it reaches the side after it (b), going clockwise.
  const cornerPoints = (x0, y0, x1, y1, c) => [
    {C: [x0, y0], a: [x0, y0 + c[0][1]], b: [x0 + c[0][0], y0]},
    {C: [x1, y0], a: [x1 - c[1][0], y0], b: [x1, y0 + c[1][1]]},
    {C: [x1, y1], a: [x1, y1 - c[2][1]], b: [x1 - c[2][0], y1]},
    {C: [x0, y1], a: [x0 + c[3][0], y1], b: [x0, y1 - c[3][1]]}];
  const roundRect = (x0, y0, x1, y1, c, ccw) => {
    const q = cornerPoints(x0, y0, x1, y1, c);
    let d = 'M' + pt(...(ccw ? q[0].a : q[0].b));
    for (const k of (ccw ? [3, 2, 1, 0] : [1, 2, 3, 0])) {
      d += ccw ? 'L' + pt(...q[k].b) + arc(q[k].C, q[k].b, q[k].a) : 'L' + pt(...q[k].a) + arc(q[k].C, q[k].a, q[k].b);
    }
    return d + 'Z';
  };
  // CSS "corner overlap": all radii scale down together when two corners would meet; a corner with
  // either radius zero is square.
  const fitCorners = (c, w, h) => {
    c = c.map(([x, y]) => (x > 0 && y > 0 ? [x, y] : [0, 0]));
    let f = 1;
    for (const [a, b, side] of [[c[0][0], c[1][0], w], [c[1][1], c[2][1], h], [c[2][0], c[3][0], w], [c[3][1], c[0][1], h]]) {
      if (a + b > side && a + b > 0) f = Math.min(f, Math.max(0, side) / (a + b));
    }
    return c.map(([x, y]) => [x * f, y * f]);
  };
  // A box [x0, y0, x1, y1] inset by [top, right, bottom, left]; its corners shrink by the same widths
  // (the browser's inner border edge).
  const insetBox = (bx, c, t) => {
    const nb = [bx[0] + t[3], bx[1] + t[0], bx[2] - t[1], bx[3] - t[2]];
    const nc = [[c[0][0] - t[3], c[0][1] - t[0]], [c[1][0] - t[1], c[1][1] - t[0]], [c[2][0] - t[1], c[2][1] - t[2]], [c[3][0] - t[3], c[3][1] - t[2]]];
    return [nb, fitCorners(nc, nb[2] - nb[0], nb[3] - nb[1])];
  };
  // A filled band between two outlines (clockwise outside, counter-clockwise inside: non-zero fill).
  const ring = (outer, oc, inner, ic) => roundRect(...outer, oc, false) +
    (inner[2] - inner[0] > 0.01 && inner[3] - inner[1] > 0.01 ? roundRect(...inner, ic, true) : '');
  // The middle line of equal-width border sides (present: top, right, bottom, left), with their
  // rounded corners; open where a side is missing (that corner is square).
  const centreLine = (bx, present, w, c) => {
    const [L, T, R, B] = bx;
    const x0 = present[3] ? L + w / 2 : L, x1 = present[1] ? R - w / 2 : R, y0 = present[0] ? T + w / 2 : T, y1 = present[2] ? B - w / 2 : B;
    const cc = c.map(([h, v]) => (h > 0 && v > 0 ? [Math.max(0, h - w / 2), Math.max(0, v - w / 2)] : [0, 0]));
    if (present.every(Boolean)) return roundRect(x0, y0, x1, y1, cc, false);
    const q = cornerPoints(x0, y0, x1, y1, cc);
    const startOf = [[L, y0], [x1, T], [R, y1], [x0, B]], endOf = [[R, y0], [x1, B], [L, y1], [x0, T]];
    const s = [0, 1, 2, 3].find((k) => present[k] && !present[(k + 3) % 4]);
    let d = 'M' + pt(...startOf[s]);
    for (let k = s, n = 0; n < 4; k = (k + 1) % 4, n++) {
      const next = (k + 1) % 4;
      if (!present[next]) { d += 'L' + pt(...endOf[k]); break; }
      d += 'L' + pt(...q[next].a) + arc(q[next].C, q[next].a, q[next].b);
    }
    return d;
  };
  // Used corner radii [h, v] (tl, tr, br, bl; percentages of the width and the height).
  const cornersOf = (cs, rect) => fitCorners(['borderTopLeftRadius', 'borderTopRightRadius', 'borderBottomRightRadius', 'borderBottomLeftRadius']
    .map((k) => {
      const parts = String(cs[k] || '0').trim().split(/\s+/);
      const v = (s, ref) => Math.max(0, s.endsWith('%') ? parseFloat(s) / 100 * ref : parseFloat(s) || 0);
      return [v(parts[0], rect.width), v(parts[1] || parts[0], rect.height)];
    }), rect.width, rect.height);
  // Penpot corners are circular: an elliptical corner keeps its smaller radius (reported).
  const radiiOf = (cs, rect, el) => {
    const c = cornersOf(cs, rect);
    if (el && c.some(([h, v]) => Math.abs(h - v) > 0.5)) issue('radius-elliptical-approximated', el, cs.borderRadius);
    return c.map(([h, v]) => r2(Math.min(h, v)));
  };
  const shadowsOf = (cs, el) => {
    if (!cs.boxShadow || cs.boxShadow === 'none') return [];
    const out = [];
    for (const part of splitTop(cs.boxShadow)) {
      const cm = part.match(/(rgba?\([^)]*\)|#[0-9a-fA-F]+)/);
      const c = cm ? parseColor(cm[1]) : {color: '#000000', opacity: 1};
      const rest = part.replace(cm ? cm[1] : '', '').trim();
      const inset = /\binset\b/.test(rest);
      const nums = rest.replace('inset', '').trim().split(/\s+/).map(parseFloat).filter((n) => Number.isFinite(n));
      if (nums.length < 2 || !c) { issue('shadow-unsupported', el, part); continue; }
      out.push({style: inset ? 'inner-shadow' : 'drop-shadow', x: nums[0], y: nums[1], blur: nums[2] || 0,
        spread: nums[3] || 0, color: c.color, opacity: c.opacity});
    }
    // CSS paints the first shadow on top.
    return out.reverse();
  };
  // ---------- borders ----------
  const SIDES = ['top', 'right', 'bottom', 'left'];
  const LINE = {solid: 'solid', dashed: 'dashed', dotted: 'dotted'};
  const bordersOf = (cs) => SIDES.map((side) => {
    const S = side[0].toUpperCase() + side.slice(1);
    return {side, width: parseFloat(cs['border' + S + 'Width']) || 0, style: cs['border' + S + 'Style'], color: parseColor(cs['border' + S + 'Color'])};
  }).filter((s) => s.width > 0 && s.style !== 'none' && s.style !== 'hidden' && visibleColor(s.color))
    // A double border under 3 px has no room for its gap: the browser draws it solid.
    .map((s) => (s.style === 'double' && s.width < 3 ? {...s, style: 'solid'} : s));
  const sameBorder = (a, b) => a.width === b.width && a.style === b.style && a.color.color === b.color.color && a.color.opacity === b.color.opacity;
  // A double border's lines (Blink's rounding): the outer line is o wide, the inner one runs from s to the width.
  const doubleStripes = (w) => [Math.floor((w + 1) / 3), Math.floor((2 * w + 1) / 3)];
  // Borders one stroke can't draw. Sides away from rounded corners are drawn one by one: a rectangle,
  // two for double, a dashed or dotted line along the middle. Round a rounded corner, sides of one
  // colour and style become one path: a stroked middle line (equal widths), else a filled outline that
  // follows the browser's inner curve (a border thinning out round a corner, unequal widths, double).
  const borderLayers = (el, dec, bx) => {
    const [L, T, R, B] = bx;
    const sides = dec.border.sides;
    const by = Object.fromEntries(sides.map((s) => [s.side, s]));
    const present = SIDES.map((s) => !!by[s]);
    const w = SIDES.map((s) => (by[s] ? by[s].width : 0));
    const c = fitCorners(dec.corners, R - L, B - T);
    const round = c.map(([h, v]) => h > 0 && v > 0);
    const paint = (s) => [{type: 'color', color: s.color.color, opacity: s.color.opacity}];
    const band = (k, a, t) => (k === 0 ? [L, T + a, R - L, t] : k === 2 ? [L, B - a - t, R - L, t] : k === 3 ? [L + a, T, t, B - T] : [R - a - t, T, t, B - T]);
    const rect = (name, [x, y, bw, bh], s) => ({kind: 'rect', name, box: {x, y, w: bw, h: bh}, fills: paint(s), strokes: [],
      radius: [0, 0, 0, 0], shadows: [], opacity: 1, deco: 'over', z: 0});
    const path = (name, d, fills, strokes, bb) => ({kind: 'path', name, d, box: bb || {x: L, y: T, w: R - L, h: B - T}, fills, strokes,
      opacity: 1, deco: 'over', z: 0});
    const out = [];
    const first = sides[0];
    const nearRound = sides.some((s) => { const k = SIDES.indexOf(s.side); return round[k] || round[(k + 1) % 4]; });
    const uniform = sides.every((s) => s.color.color === first.color.color && s.color.opacity === first.color.opacity && s.style === first.style);
    if (nearRound && !uniform) {
      for (const s of sides) out.push(rect('Border / ' + s.side, band(SIDES.indexOf(s.side), 0, s.width), s));
      issue('border-sides-approximated', el, 'sides of different colours or styles on a rounded box');
      return out;
    }
    if (!nearRound) {
      for (const s of sides) {
        const k = SIDES.indexOf(s.side);
        if (s.style === 'double') {
          const [o, st] = doubleStripes(s.width);
          out.push(rect('Border / ' + s.side + ' (outer line)', band(k, 0, o), s), rect('Border / ' + s.side + ' (inner line)', band(k, st, s.width - st), s));
        } else if (s.style === 'dashed' || s.style === 'dotted') {
          const [x, y, bw, bh] = band(k, 0, s.width);
          const d = k % 2 === 0 ? 'M' + pt(x, y + bh / 2) + 'L' + pt(x + bw, y + bh / 2) : 'M' + pt(x + bw / 2, y) + 'L' + pt(x + bw / 2, y + bh);
          out.push(path('Border / ' + s.side, d, [], [{color: s.color.color, opacity: s.color.opacity, width: s.width, align: 'center', style: s.style}],
            {x, y, w: bw, h: bh}));
        } else {
          out.push(rect('Border / ' + s.side, band(k, 0, s.width), s));
          if (s.style !== 'solid') issue('border-style-approximated', el, s.side + ' ' + s.style + ' drawn solid');
        }
      }
      return out;
    }
    const name = 'Border / ' + sides.map((s) => s.side).join(' ');
    const style = first.style;
    const even = sides.every((s) => s.width === first.width);
    // where a side meets a missing one round a rounded corner, the border thins out to nothing
    const tapers = round.some((r, k) => r && present[k] !== present[(k + 3) % 4]);
    // a joint corner that is square or tighter than the line (its inner edge is square in CSS)
    const sharp = present.some((p, k) => p && present[(k + 3) % 4] && (!round[k] || Math.min(...c[k]) < first.width));
    if (LINE[style] && even && !tapers && (style !== 'solid' || !sharp)) {
      out.push(path(name, centreLine(bx, present, first.width, c), [],
        [{color: first.color.color, opacity: first.color.opacity, width: first.width, align: 'center', style}]));
      return out;
    }
    if (style === 'double') {
      const [b1, c1] = insetBox(bx, c, w.map((x) => doubleStripes(x)[0]));
      const [b2, c2] = insetBox(bx, c, w.map((x) => doubleStripes(x)[1]));
      const [b3, c3] = insetBox(bx, c, w);
      out.push(path(name + ' (double)', ring(bx, c, b1, c1) + ring(b2, c2, b3, c3), paint(first), []));
      return out;
    }
    if (style !== 'solid') issue('border-style-approximated', el, style + ' border round a rounded corner drawn solid');
    const [ib, ic] = insetBox(bx, c, w);
    out.push(path(name, ring(bx, c, ib, ic), paint(first), []));
    return out;
  };
  const decoration = (el, cs, rect, layered) => {
    const plan = bgPlan(cs, el, rect, !!layered);
    const fills = plan.base;
    const borders = bordersOf(cs);
    const shadows = shadowsOf(cs, el);
    const corners = cornersOf(cs, rect);
    const radius = radiiOf(cs, rect, el);
    let strokes = [], border = null;
    if (borders.length === 4 && borders.every((b) => sameBorder(b, borders[0]))) {
      const b = borders[0];
      if (b.style === 'double' && layered) {
        // two native strokes: the box's own (the outer line) and an inset layer's (the inner line)
        const [o, s] = doubleStripes(b.width);
        strokes = [{color: b.color.color, opacity: b.color.opacity, width: o, align: 'inner', style: 'solid'}];
        border = {double: {inset: s, width: b.width - s, color: b.color}};
      } else {
        strokes = [{color: b.color.color, opacity: b.color.opacity, width: b.width, align: 'inner', style: LINE[b.style] || 'solid'}];
        if (!LINE[b.style]) issue('border-style-approximated', el, b.style + ' border drawn solid');
      }
    } else if (borders.length) {
      border = {sides: borders};
    }
    // An outline (focus rings) is drawn as its own layer outside the box.
    let outline = null;
    const ow = parseFloat(cs.outlineWidth) || 0;
    if (cs.outlineStyle && cs.outlineStyle !== 'none' && ow > 0) {
      const oc = parseColor(cs.outlineColor);
      if (visibleColor(oc)) outline = {width: ow, offset: parseFloat(cs.outlineOffset) || 0, color: oc.color, opacity: oc.opacity,
        style: cs.outlineStyle === 'dashed' ? 'dashed' : cs.outlineStyle === 'dotted' ? 'dotted' : 'solid'};
    }
    const visible = fills.length > 0 || plan.runs.length > 0 || strokes.length > 0 || !!border || shadows.length > 0 || !!outline;
    return {fills, runs: plan.runs, strokes, border, shadows, radius, corners, visible, outline};
  };

  // ---------- naming ----------
  const headingIn = (el) => {
    const hd = el.querySelector('h1, h2, h3');
    return hd ? short(hd.textContent, 36) : '';
  };
  const titleCase = (s) => s.charAt(0).toUpperCase() + s.slice(1);
  const nameOf = (el, kind) => {
    const d = el.dataset && (el.dataset.component || el.dataset.name);
    if (d) return short(d, 60);
    const label = el.getAttribute('aria-label');
    if (label) return short(label, 60);
    const tag = el.tagName.toLowerCase();
    if (kind === 'section') {
      const h = headingIn(el);
      const base = {header: 'Header', footer: 'Footer', nav: 'Navigation', main: 'Main'}[tag] || 'Section';
      if (el.id) return base + ' / ' + el.id;
      return h ? base + ' / ' + h : base;
    }
    if (el.id) return titleCase(tag) + ' / ' + el.id;
    const cls = el.classList && el.classList.length ? el.classList[0] : '';
    return titleCase(tag) + (cls ? ' / ' + cls : '');
  };

  // ---------- SVG -> absolute paths ----------
  const pathSegments = (d) => {
    const toks = d.match(/[MmLlHhVvCcSsQqTtAaZz]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?/g) || [];
    const out = [];
    let i = 0, cmd = null, cx = 0, cy = 0, sx0 = 0, sy0 = 0, lc = null, lq = null;
    const num = () => parseFloat(toks[i++]);
    const isCmd = (t) => /^[A-Za-z]$/.test(t);
    while (i < toks.length) {
      if (isCmd(toks[i])) cmd = toks[i++];
      else if (cmd === null) break;
      const rel = cmd === cmd.toLowerCase();
      const C = cmd.toUpperCase();
      if (C === 'Z') { out.push(['Z']); cx = sx0; cy = sy0; lc = lq = null; if (i < toks.length && !isCmd(toks[i])) cmd = 'L'; continue; }
      if (C === 'M') {
        let x = num(), y = num(); if (rel) { x += cx; y += cy; }
        out.push(['M', x, y]); cx = sx0 = x; cy = sy0 = y; lc = lq = null;
        cmd = rel ? 'l' : 'L';
        continue;
      }
      if (C === 'L') { let x = num(), y = num(); if (rel) { x += cx; y += cy; } out.push(['L', x, y]); cx = x; cy = y; lc = lq = null; continue; }
      if (C === 'H') { let x = num(); if (rel) x += cx; out.push(['L', x, cy]); cx = x; lc = lq = null; continue; }
      if (C === 'V') { let y = num(); if (rel) y += cy; out.push(['L', cx, y]); cy = y; lc = lq = null; continue; }
      if (C === 'C') {
        let a = [num(), num(), num(), num(), num(), num()];
        if (rel) a = a.map((v, k) => v + (k % 2 ? cy : cx));
        out.push(['C', ...a]); lc = [a[2], a[3]]; lq = null; cx = a[4]; cy = a[5]; continue;
      }
      if (C === 'S') {
        let a = [num(), num(), num(), num()];
        if (rel) a = a.map((v, k) => v + (k % 2 ? cy : cx));
        const c1 = lc ? [2 * cx - lc[0], 2 * cy - lc[1]] : [cx, cy];
        out.push(['C', c1[0], c1[1], a[0], a[1], a[2], a[3]]); lc = [a[0], a[1]]; lq = null; cx = a[2]; cy = a[3]; continue;
      }
      if (C === 'Q' || C === 'T') {
        let q, x, y;
        if (C === 'Q') { q = [num(), num()]; x = num(); y = num(); if (rel) { q = [q[0] + cx, q[1] + cy]; x += cx; y += cy; } }
        else { x = num(); y = num(); if (rel) { x += cx; y += cy; } q = lq ? [2 * cx - lq[0], 2 * cy - lq[1]] : [cx, cy]; }
        out.push(['C', cx + 2 / 3 * (q[0] - cx), cy + 2 / 3 * (q[1] - cy), x + 2 / 3 * (q[0] - x), y + 2 / 3 * (q[1] - y), x, y]);
        lq = q; lc = null; cx = x; cy = y; continue;
      }
      if (C === 'A') {
        let rx = Math.abs(num()), ry = Math.abs(num()); const phi = num() * Math.PI / 180; const fa = num(), fs = num();
        let x = num(), y = num(); if (rel) { x += cx; y += cy; }
        out.push(...arcToCubics(cx, cy, rx, ry, phi, fa, fs, x, y)); cx = x; cy = y; lc = lq = null; continue;
      }
      i++; // unknown token
    }
    return out;
  };
  const arcToCubics = (x1, y1, rx, ry, phi, fa, fs, x2, y2) => {
    if (rx === 0 || ry === 0 || (x1 === x2 && y1 === y2)) return [['L', x2, y2]];
    const cos = Math.cos(phi), sin = Math.sin(phi);
    const dx = (x1 - x2) / 2, dy = (y1 - y2) / 2;
    const x1p = cos * dx + sin * dy, y1p = -sin * dx + cos * dy;
    let lam = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry);
    if (lam > 1) { rx *= Math.sqrt(lam); ry *= Math.sqrt(lam); }
    const sign = fa === fs ? -1 : 1;
    const num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p;
    const co = sign * Math.sqrt(Math.max(0, num / (rx * rx * y1p * y1p + ry * ry * x1p * x1p)));
    const cxp = co * rx * y1p / ry, cyp = -co * ry * x1p / rx;
    const ccx = cos * cxp - sin * cyp + (x1 + x2) / 2, ccy = sin * cxp + cos * cyp + (y1 + y2) / 2;
    const ang = (ux, uy, vx, vy) => { const a = Math.atan2(ux * vy - uy * vx, ux * vx + uy * vy); return a; };
    let t1 = ang(1, 0, (x1p - cxp) / rx, (y1p - cyp) / ry);
    let dt = ang((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry);
    if (!fs && dt > 0) dt -= 2 * Math.PI;
    if (fs && dt < 0) dt += 2 * Math.PI;
    const n = Math.ceil(Math.abs(dt) / (Math.PI / 2));
    const out = [];
    const d = dt / n;
    const k = 4 / 3 * Math.tan(d / 4);
    for (let s = 0; s < n; s++) {
      const a1 = t1 + s * d, a2 = a1 + d;
      const p = (a) => [Math.cos(a), Math.sin(a)];
      const [c1, s1] = p(a1), [c2, s2] = p(a2);
      const e1 = [c1 - k * s1, s1 + k * c1], e2 = [c2 + k * s2, s2 - k * c2];
      const map = (u, v) => [ccx + rx * u * cos - ry * v * sin, ccy + rx * u * sin + ry * v * cos];
      const q1 = map(e1[0], e1[1]), q2 = map(e2[0], e2[1]), q3 = map(c2, s2);
      out.push(['C', q1[0], q1[1], q2[0], q2[1], q3[0], q3[1]]);
    }
    return out;
  };
  const shapeD = (el) => {
    const tag = el.tagName.toLowerCase();
    const n = (a) => parseFloat(el.getAttribute(a)) || 0;
    if (tag === 'path') return el.getAttribute('d') || '';
    if (tag === 'rect') {
      const x = n('x'), y = n('y'), w = n('width'), h = n('height');
      let rx = el.hasAttribute('rx') ? n('rx') : (el.hasAttribute('ry') ? n('ry') : 0);
      let ry = el.hasAttribute('ry') ? n('ry') : rx;
      rx = Math.min(rx, w / 2); ry = Math.min(ry, h / 2);
      if (!rx && !ry) return `M${x} ${y}H${x + w}V${y + h}H${x}Z`;
      return `M${x + rx} ${y}H${x + w - rx}A${rx} ${ry} 0 0 1 ${x + w} ${y + ry}V${y + h - ry}A${rx} ${ry} 0 0 1 ${x + w - rx} ${y + h}H${x + rx}A${rx} ${ry} 0 0 1 ${x} ${y + h - ry}V${y + ry}A${rx} ${ry} 0 0 1 ${x + rx} ${y}Z`;
    }
    if (tag === 'circle' || tag === 'ellipse') {
      const cx = n('cx'), cy = n('cy');
      const rx = tag === 'circle' ? n('r') : n('rx'), ry = tag === 'circle' ? n('r') : n('ry');
      return `M${cx - rx} ${cy}A${rx} ${ry} 0 1 0 ${cx + rx} ${cy}A${rx} ${ry} 0 1 0 ${cx - rx} ${cy}Z`;
    }
    if (tag === 'line') return `M${n('x1')} ${n('y1')}L${n('x2')} ${n('y2')}`;
    if (tag === 'polyline' || tag === 'polygon') {
      const pts = (el.getAttribute('points') || '').trim().split(/[\s,]+/).map(parseFloat);
      let d = '';
      for (let i = 0; i + 1 < pts.length; i += 2) d += (i ? 'L' : 'M') + pts[i] + ' ' + pts[i + 1];
      return tag === 'polygon' ? d + 'Z' : d;
    }
    return '';
  };
  const fmt = (v) => { const s = (Math.round(v * 1000) / 1000).toString(); return s === '-0' ? '0' : s; };
  const svgPaint = (paint, opacity, el, svg) => {
    if (!paint || paint === 'none') return null;
    const m = paint.match(/url\(["']?#([^"')]+)["']?\)/);
    if (m) {
      const g = svg.ownerDocument.getElementById(m[1]);
      if (g && /linearGradient|radialGradient/.test(g.tagName)) {
        const stops = [...g.querySelectorAll('stop')].map((s) => {
          const cs = getComputedStyle(s);
          const c = parseColor(cs.stopColor);
          const off = s.getAttribute('offset') || '0';
          return c && {color: c.color, opacity: r2(c.opacity * (parseFloat(cs.stopOpacity) || 1)),
            offset: r2(Math.max(0, Math.min(1, off.endsWith('%') ? parseFloat(off) / 100 : parseFloat(off))))};
        }).filter(Boolean);
        if (!stops.length) return null;
        if (g.tagName === 'linearGradient' && (g.getAttribute('gradientUnits') || 'objectBoundingBox') === 'objectBoundingBox' && !g.getAttribute('gradientTransform')) {
          const a = (k, dflt) => { const v = g.getAttribute(k); return v === null ? dflt : (v.endsWith('%') ? parseFloat(v) / 100 : parseFloat(v)); };
          return {type: 'linear', start: [a('x1', 0), a('y1', 0)], end: [a('x2', 1), a('y2', 0)], width: 1, stops, opacity};
        }
        issue('svg-gradient-approximated', el, g.tagName);
        return {type: 'color', color: stops[0].color, opacity: r2(stops[0].opacity * opacity)};
      }
      issue('svg-paint-unsupported', el, paint);
      return null;
    }
    const c = parseColor(paint);
    return c && visibleColor(c) ? {type: 'color', color: c.color, opacity: r2(c.opacity * opacity)} : null;
  };
  const emitSvg = (svg, out) => {
    const rect = svg.getBoundingClientRect();
    if (rect.width < 0.5 || rect.height < 0.5) return;
    const label = svg.getAttribute('aria-label') || (svg.querySelector('title') && svg.querySelector('title').textContent) || svg.dataset.name || '';
    const group = {kind: 'group', name: 'SVG' + (label ? ' / ' + short(label, 40) : ''), box: box(rect), children: []};
    for (const bad of svg.querySelectorAll('text, use, image, foreignObject')) {
      if (!bad.closest('defs, symbol, clipPath, mask, pattern, marker')) issue('svg-element-unsupported', bad, bad.tagName);
    }
    if (svg.querySelector('[clip-path], [mask], [filter]')) issue('svg-effect-ignored', svg, 'clip-path/mask/filter');
    const els = svg.querySelectorAll('path, rect, circle, ellipse, line, polyline, polygon');
    let idx = 0;
    for (const el of els) {
      if (el.closest('defs, symbol, clipPath, mask, pattern, marker')) continue;
      const cs = getComputedStyle(el);
      if (cs.display === 'none' || cs.visibility === 'hidden') continue;
      const d = shapeD(el);
      if (!d) continue;
      const m = el.getScreenCTM();
      if (!m) continue;
      const segs = pathSegments(d);
      if (!segs.length) continue;
      const tx = (x, y) => [m.a * x + m.c * y + m.e + sx, m.b * x + m.d * y + m.f + sy];
      let str = '';
      for (const s of segs) {
        if (s[0] === 'Z') { str += 'Z'; continue; }
        const pts = [];
        for (let k = 1; k < s.length; k += 2) pts.push(...tx(s[k], s[k + 1]));
        str += s[0] + pts.map(fmt).join(' ');
      }
      const op = parseFloat(cs.opacity);
      const fill = svgPaint(cs.fill, parseFloat(cs.fillOpacity), el, svg);
      const strokeP = svgPaint(cs.stroke, parseFloat(cs.strokeOpacity), el, svg);
      const scale = Math.sqrt(Math.abs(m.a * m.d - m.b * m.c));
      const sw = parseFloat(cs.strokeWidth) * scale;
      const strokes = strokeP && sw > 0 && strokeP.type === 'color' ? [{color: strokeP.color, opacity: strokeP.opacity, width: r2(sw), align: 'center',
        style: cs.strokeDasharray && cs.strokeDasharray !== 'none' ? 'dashed' : 'solid', cap: cs.strokeLinecap, join: cs.strokeLinejoin}] : [];
      if (strokeP && strokeP.type !== 'color') issue('svg-stroke-gradient-approximated', el, '');
      const b = el.getBoundingClientRect();
      const fills = fill ? [fill] : [];
      if (!fills.length && !strokes.length) continue;
      idx += 1;
      group.children.push({kind: 'path', name: (el.dataset && el.dataset.name) || (el.getAttribute('id') || el.tagName.toLowerCase()) + ' ' + idx,
        d: str, box: box(b), fills, strokes, opacity: Number.isFinite(op) ? op : 1, fillRule: cs.fillRule});
      stats.paths += 1;
    }
    if (group.children.length) { out.push(group); stats.groups += 1; }
  };

  // ---------- text runs ----------
  const INLINE = new Set(['inline', 'contents']);
  const isInlineLevel = (node) => {
    if (node.nodeType === Node.TEXT_NODE) return true;
    if (node.nodeType !== Node.ELEMENT_NODE) return false;
    const tag = node.tagName.toLowerCase();
    if (tag === 'br') return true;
    if (tag === 'img' || tag === 'svg' || tag === 'input' || tag === 'textarea' || tag === 'select' || tag === 'video' || tag === 'canvas' || tag === 'iframe') return false;
    // A component is always its own layer, never folded into a text run.
    if (node.dataset && node.dataset.component !== undefined) return false;
    const cs = getComputedStyle(node);
    if (!INLINE.has(cs.display) || cs.position === 'absolute' || cs.position === 'fixed' || cs.cssFloat !== 'none') return false;
    // An inline element that holds block-level content is walked like a block.
    for (const c of node.children) if (!isInlineLevel(c)) return false;
    return true;
  };
  const styleOf = (el) => {
    const cs = getComputedStyle(el);
    const fam = familyOf(cs, el);
    const size = parseFloat(cs.fontSize);
    const color = parseColor(cs.color) || {color: '#000000', opacity: 1};
    const weight = String(cs.fontWeight);
    usedFonts.set(fam.toLowerCase() + '|' + weight + '|' + cs.fontStyle, {family: fam, weight, style: cs.fontStyle});
    if (cs.webkitBackgroundClip === 'text' || cs.backgroundClip === 'text') issue('text-background-clip-approximated', el, 'gradient text drawn as its solid colour');
    if (cs.webkitTextStroke && parseFloat(cs.webkitTextStrokeWidth) > 0) issue('text-stroke-ignored', el, cs.webkitTextStroke);
    if (cs.textShadow && cs.textShadow !== 'none') issue('text-shadow-ignored', el, cs.textShadow.slice(0, 60));
    return {family: fam, weight, style: cs.fontStyle, size, lineHeight: cs.lineHeight === 'normal' ? null : parseFloat(cs.lineHeight),
      letterSpacing: cs.letterSpacing === 'normal' ? 0 : parseFloat(cs.letterSpacing) || 0, transform: cs.textTransform,
      decoration: (cs.textDecorationLine || 'none').includes('underline') ? 'underline' : ((cs.textDecorationLine || '').includes('line-through') ? 'line-through' : 'none'),
      color: color.color, opacity: color.opacity, role: (el.closest('[data-typography]') || {dataset: {}}).dataset.typography || null,
      tag: el.tagName.toLowerCase()};
  };
  const sameStyle = (a, b) => JSON.stringify(a) === JSON.stringify(b);
  const range = document.createRange();
  // The width of one space in an element's font (letter and word spacing included): the browser
  // drops the space at a soft line break, Penpot keeps it at the line's end (see text.wrap).
  const spaceWidths = new Map();
  const spaceWidth = (el) => {
    if (!el) return 0;
    if (!spaceWidths.has(el)) {
      const probe = document.createElement('span');
      probe.style.cssText = 'position:absolute;left:0;top:0;visibility:hidden;white-space:pre;margin:0;padding:0;border:0';
      probe.textContent = ' ';
      el.appendChild(probe);
      spaceWidths.set(el, probe.getBoundingClientRect().width);
      probe.remove();
    }
    return spaceWidths.get(el);
  };

  // Turn one run of inline content into a text node, in DOM order, keeping the browser's line boxes.
  const emitRun = (nodes, block, out) => {
    const paragraphs = [[]];
    const lines = [];           // line boxes: {top, bottom, frags: [...]}
    const decor = [];
    let cur = null;             // current line
    let prevRight = -Infinity, prevTop = -Infinity;
    let lastWasSpace = true;
    let anyText = false;
    let plain = '';
    let brk = null;             // what ended the line so far: 'space', 'end' (paragraph) or none
    let spaceEl = null;         // the element of the last space seen
    const pushChar = (ch, leafRef, rc) => {
      const top = rc.top + sy, bottom = rc.bottom + sy, left = rc.left + sx, right = rc.right + sx;
      const cyy = (top + bottom) / 2;
      const wrapped = cur && (cyy > cur.bottom || (left < prevRight - 1 && top > prevTop + (bottom - top) * 0.3));
      if (!cur || wrapped) {
        if (cur) { cur.k = brk || 'char'; cur.spEl = spaceEl; }
        cur = {top, bottom, frags: []};
        lines.push(cur);
      }
      // where the line's ink ends and its first word, for the width at which Penpot breaks it the same
      if (ch === ' ') {
        if (cur.inkR !== undefined && cur.fsp === undefined) cur.fsp = right - left;
      } else {
        if (cur.inkL === undefined) { cur.inkL = left; cur.inkR = right; cur.fwL = left; }
        cur.inkL = Math.min(cur.inkL, left); cur.inkR = Math.max(cur.inkR, right);
        if (cur.fsp === undefined) cur.fwR = Math.max(cur.fwR === undefined ? right : cur.fwR, right);
        brk = null;
      }
      cur.top = Math.min(cur.top, top); cur.bottom = Math.max(cur.bottom, bottom);
      let f = cur.frags[cur.frags.length - 1];
      if (!f || f.leaf !== leafRef) {
        f = {leaf: leafRef, left, right, top, bottom, text: ''};
        cur.frags.push(f);
      }
      f.left = Math.min(f.left, left); f.right = Math.max(f.right, right);
      f.top = Math.min(f.top, top); f.bottom = Math.max(f.bottom, bottom);
      f.text += ch;
      prevRight = right; prevTop = top;
    };
    const visit = (node) => {
      if (node.nodeType === Node.TEXT_NODE) {
        const parent = node.parentElement;
        plain += node.data;
        const st = styleOf(parent);
        const para = paragraphs[paragraphs.length - 1];
        let leaf = para[para.length - 1];
        if (!leaf || !sameStyle(leaf.style, st)) { leaf = {text: '', style: st}; para.push(leaf); }
        const ws = getComputedStyle(parent).whiteSpace;
        const pre = /^(pre|pre-wrap|break-spaces|pre-line)$/.test(ws);
        const data = node.data;
        for (let i = 0; i < data.length; i++) {
          const ch = data[i];
          range.setStart(node, i); range.setEnd(node, i + 1);
          const rects = range.getClientRects();
          const rc = rects.length ? rects[rects.length - 1] : null;
          const isWs = SPACE.test(ch);  // a no-break space is a character with a width, not white space
          if (isWs) {
            if (pre && ch === '\n') brk = 'end';
            else if (brk !== 'end') { brk = 'space'; spaceEl = parent; }
          }
          if (isWs && !pre) {
            // Collapsed white space still separates words in the live text (soft wraps
            // included); only a space with a visible box joins a line fragment.
            if (lastWasSpace || !anyText) continue;
            if (!leaf) { const p2 = paragraphs[paragraphs.length - 1]; leaf = {text: '', style: st}; p2.push(leaf); }
            leaf.text += ' ';
            lastWasSpace = true;
            if (rc && rc.width > 0.01) pushChar(' ', leaf, rc);
            continue;
          }
          if (isWs && ch === '\n') { paragraphs.push([]); leaf = null; lastWasSpace = true; continue; }
          if (!rc) continue;
          if (!leaf) { const p2 = paragraphs[paragraphs.length - 1]; leaf = {text: '', style: st}; p2.push(leaf); }
          leaf.text += ch;
          lastWasSpace = ch === ' ';
          if (!isWs) anyText = true;
          pushChar(ch, leaf, rc);
        }
        return;
      }
      if (node.nodeType !== Node.ELEMENT_NODE) return;
      const tag = node.tagName.toLowerCase();
      if (tag === 'br') { paragraphs.push([]); lastWasSpace = true; plain += ' '; brk = 'end'; return; }
      const cs = getComputedStyle(node);
      if (cs.display === 'none' || cs.visibility === 'hidden') return;
      const dec = decoration(node, cs, node.getBoundingClientRect());
      if (dec.visible) {
        const rects = [...node.getClientRects()];
        for (const rc of rects) {
          decor.push({kind: 'rect', name: nameOf(node) + ' (inline box)', box: box(rc), fills: dec.fills, strokes: dec.strokes,
            radius: dec.radius, shadows: dec.shadows, opacity: 1, deco: 'under', z: 0});
        }
        // Side borders (a dotted leader, an underline border) under the words; a box split over lines
        // keeps its fill only.
        if (dec.border && dec.border.sides && rects.length === 1) {
          const b = box(rects[0]);
          for (const k of borderLayers(node, dec, [Math.round(b.x), Math.round(b.y), Math.round(b.x + b.w), Math.round(b.y + b.h)])) {
            decor.push({...k, deco: 'under'});
          }
        } else if (dec.border) {
          issue('border-sides-approximated', node, 'borders of an inline box split over lines not carried');
        }
      }
      for (const c of node.childNodes) visit(c);
    };
    for (const n of nodes) visit(n);
    if (!anyText) return;
    // Trim trailing spaces of each paragraph's last leaf; drop empty leaves/paragraphs at the ends.
    for (const para of paragraphs) {
      while (para.length && !trimSpace(para[para.length - 1].text)) para.pop();
      if (para.length) para[para.length - 1].text = para[para.length - 1].text.replace(/[ \t\n\r\f]+$/, '');
      if (para.length) para[0].text = para[0].text.replace(/^[ \t\n\r\f]+/, '');
    }
    while (paragraphs.length && !paragraphs[paragraphs.length - 1].length) paragraphs.pop();
    while (paragraphs.length && !paragraphs[0].length) paragraphs.shift();
    if (!paragraphs.length || !lines.length) return;
    const bcs = getComputedStyle(block);
    const br = block.getBoundingClientRect();
    const pl = parseFloat(bcs.paddingLeft) + parseFloat(bcs.borderLeftWidth);
    const pr = parseFloat(bcs.paddingRight) + parseFloat(bcs.borderRightWidth);
    const contentLeft = br.left + sx + pl, contentRight = br.right + sx - pr;
    const first = paragraphs[0][0].style;
    const firstSize = first.size;
    const lh = first.lineHeight;
    const lineTops = lines.map((l) => l.top);
    let pitch = null;
    if (lines.length > 1) pitch = (lineTops[lineTops.length - 1] - lineTops[0]) / (lines.length - 1);
    const lineBox = lh || pitch || (lines[0].bottom - lines[0].top);
    const half = Math.max(0, (lineBox - (lines[0].bottom - lines[0].top)) / 2);
    const minLeft = Math.min(...lines.flatMap((l) => l.frags.map((f) => f.left)));
    const maxRight = Math.max(...lines.flatMap((l) => l.frags.map((f) => f.right)));
    // Text straight inside a flex/grid box is an anonymous item: its box is the text itself.
    const anon = /flex|grid/.test(bcs.display);
    const x = anon ? minLeft : Math.min(contentLeft, minLeft);
    const right = anon ? maxRight : Math.max(contentRight, maxRight);
    // How the Penpot text should grow when edited: one shrink-wrapped line grows in width, the rest in height.
    const nowrap = /^(nowrap|pre)$/.test(bcs.whiteSpace);
    const fit = lines.length === 1 && (anon || nowrap || Math.abs((contentRight - contentLeft) - (maxRight - minLeft)) < 1.5) ? 'width' : 'height';
    const top = lines[0].top - half;
    const lastHalf = Math.max(0, (lineBox - (lines[lines.length - 1].bottom - lines[lines.length - 1].top)) / 2);
    const bottom = lines[lines.length - 1].bottom + lastHalf;
    let align = bcs.textAlign;
    align = align === 'start' || align === '-webkit-left' ? 'left' : align === 'end' || align === '-webkit-right' ? 'right' : align === '-webkit-center' ? 'center' : align;
    if (!['left', 'center', 'right', 'justify'].includes(align)) align = 'left';
    const leafIndex = new Map();
    paragraphs.forEach((para, pi) => para.forEach((leaf, li) => leafIndex.set(leaf, [pi, li])));
    const frags = [];
    for (const line of lines) {
      for (const f of line.frags) {
        const idx = leafIndex.get(f.leaf);
        if (!idx) continue;
        const text = f.text;
        if (!trimSpace(text)) continue;
        frags.push({p: idx[0], l: idx[1], x: r2(f.left), y: r2(f.bottom), w: r2(f.right - f.left), h: r2(f.bottom - f.top), text});
      }
    }
    // Per line: ink width, what ended it, the space there, and its first word with the space after
    // it; the planner picks a box width at which Penpot's breaks match the browser's.
    const wrap = lines.map((l, i) => {
      const k = i === lines.length - 1 ? 'end' : (l.k || 'char');
      return {w: l.inkR === undefined ? 0 : r2(l.inkR - l.inkL), k, sp: k === 'space' ? r2(spaceWidth(l.spEl)) : 0,
        fw: l.fwR === undefined ? null : r2(l.fwR - l.fwL), fsp: l.fsp === undefined ? null : r2(l.fsp)};
    });
    for (const d of decor) out.push(d);
    const label = short(paragraphs.map((p) => p.map((l) => l.text).join('')).join(' '), 40);
    const tag = block.tagName.toLowerCase();
    const role = /^h[1-6]$/.test(tag) ? tag.toUpperCase() : (tag === 'a' || tag === 'button' ? titleCase(tag) : 'Text');
    out.push({kind: 'text', name: (block.dataset && block.dataset.name && block.childElementCount === 0 ? block.dataset.name : role + ' — ' + label),
      fit, z: 0, item: anon ? {anon: true, pos: 'static', grow: 0, alignSelf: 'auto', justifySelf: 'auto', margin: [0, 0, 0, 0]} : undefined,
      box: {x: r2(x), y: r2(top), w: r2(right - x), h: r2(bottom - top)},
      text: {align, lineHeight: r2(lineBox), paragraphs: paragraphs.map((para) => para.map((leaf) => ({text: leaf.text, style: leaf.style}))), lines: frags,
        wrap, plain: clean(plain), ...(nowrap ? {nowrap: true} : {})}});
    stats.texts += 1;
    void firstSize;
  };

  // ---------- elements ----------
  // Paint order within the nearest stacking context (CSS 2.1 appendix E): negative z-index, the boxes
  // in flow, then positioned boxes and z-index 0 stacking contexts in tree order, then positive
  // z-index. A static box that makes a stacking context (opacity, transform, filter, isolation,
  // blend mode, clip path, mask, containment) paints with the positioned ones; a flex or grid item
  // with a z-index acts as if positioned.
  const stacking = (cs) => parseFloat(cs.opacity) < 1 || (cs.transform || 'none') !== 'none' || (cs.filter || 'none') !== 'none' ||
    cs.isolation === 'isolate' || (cs.mixBlendMode || 'normal') !== 'normal' || (cs.backdropFilter || 'none') !== 'none' ||
    (cs.clipPath || 'none') !== 'none' || (cs.maskImage || cs.webkitMaskImage || 'none') !== 'none' ||
    /\b(paint|layout|strict|content)\b/.test(cs.contain || '');
  const paintKey = (el) => {
    if (el.nodeType !== Node.ELEMENT_NODE) return 0;
    const cs = getComputedStyle(el);
    const z = parseInt(cs.zIndex, 10);
    const pd = el.parentElement ? getComputedStyle(el.parentElement).display : '';
    const positioned = cs.position !== 'static' || (Number.isFinite(z) && /flex|grid/.test(pd));
    if (positioned && Number.isFinite(z) && z < 0) return -1 + z / 1e6;
    if (positioned && Number.isFinite(z) && z > 0) return 2 + z / 1e6;
    if (positioned || stacking(cs)) return 1;
    return 0;
  };
  const isSectionEl = (el) => {
    if (el.dataset && el.dataset.section !== undefined) return true;
    const p = el.parentElement;
    if (!p) return false;
    const tag = el.tagName.toLowerCase();
    const parentTag = p.tagName.toLowerCase();
    const wrapperOnly = parentTag !== 'body' && p.parentElement && p.parentElement.tagName.toLowerCase() === 'body' && p.parentElement.children.length === 1;
    if (parentTag === 'body' || parentTag === 'main' || wrapperOnly) {
      return ['header', 'section', 'footer', 'nav', 'aside', 'div', 'article'].includes(tag) && el.getBoundingClientRect().height >= 24;
    }
    return false;
  };
  const textContentOnlyWhitespace = (nodes) => nodes.every((n) => n.nodeType !== Node.TEXT_NODE || !n.data.trim());

  // ---------- layout facts (for Penpot flex and grid layouts) ----------
  const pxOrNull = (v) => (v && /px$/.test(v)) ? r2(parseFloat(v)) : null;
  const gapPx = (v) => (v && v !== 'normal') ? r2(parseFloat(v) || 0) : 0;
  const tracks = (v) => (v && v !== 'none') ? v.split(/\s+/).filter((t) => /^-?[\d.]+px$/.test(t)).map((t) => r2(parseFloat(t))) : [];
  // The author's own value of a property (crude cascade: inline style, then the most specific, latest matching rule).
  let ruleList = null;
  const allRules = () => {
    if (ruleList) return ruleList;
    ruleList = [];
    const visit = (list) => {
      for (const rule of list) {
        if (rule.media && rule.cssRules) { if (window.matchMedia(rule.media.mediaText).matches) visit(rule.cssRules); continue; }
        if (rule.cssRules && !rule.selectorText) { visit(rule.cssRules); continue; }
        if (rule.selectorText && rule.style) ruleList.push(rule);
      }
    };
    for (const sheet of document.styleSheets) { let rules; try { rules = sheet.cssRules; } catch (e) { continue; } visit(rules); }
    return ruleList;
  };
  const specificity = (sel) => {
    const ids = (sel.match(/#[\w-]+/g) || []).length;
    const cls = (sel.match(/\.[\w-]+|\[[^\]]*\]|:(?!:)[\w-]+/g) || []).length;
    const tags = (sel.replace(/#[\w-]+|\.[\w-]+|\[[^\]]*\]|::?[\w-]+(\([^)]*\))?/g, ' ').match(/[a-zA-Z][\w-]*/g) || []).length;
    return ids * 10000 + cls * 100 + tags;
  };
  const specified = (el, prop) => {
    const inline = el.style && el.style.getPropertyValue(prop);
    if (inline) return inline.trim();
    let best = null, bestSpec = -1;
    for (const rule of allRules()) {
      const v = rule.style.getPropertyValue(prop);
      if (!v) continue;
      for (const sel of splitTop(rule.selectorText)) {
        let ok = false;
        try { ok = el.matches(sel); } catch (e) { ok = false; }
        if (ok) { const s = specificity(sel); if (s >= bestSpec) { best = v.trim(); bestSpec = s; } }
      }
    }
    return best;
  };
  const layoutOf = (el, cs) => {
    const d = cs.display;
    const side = (s) => (parseFloat(cs['padding' + s]) || 0) + (parseFloat(cs['border' + s + 'Width']) || 0);
    const L = {display: d, pad: ['Top', 'Right', 'Bottom', 'Left'].map((s) => r2(side(s))), textAlign: cs.textAlign};
    if (/flex/.test(d)) {
      Object.assign(L, {dir: cs.flexDirection, wrap: cs.flexWrap, gap: [gapPx(cs.rowGap), gapPx(cs.columnGap)],
        justify: cs.justifyContent, alignItems: cs.alignItems, alignContent: cs.alignContent});
    } else if (/grid/.test(d)) {
      Object.assign(L, {gap: [gapPx(cs.rowGap), gapPx(cs.columnGap)], justify: cs.justifyContent, alignItems: cs.alignItems,
        alignContent: cs.alignContent, justifyItems: cs.justifyItems, cols: tracks(cs.gridTemplateColumns), rows: tracks(cs.gridTemplateRows),
        colsSpec: specified(el, 'grid-template-columns'), rowsSpec: specified(el, 'grid-template-rows'),
        autoRows: cs.gridAutoRows, autoCols: cs.gridAutoColumns, flow: cs.gridAutoFlow});
    }
    return L;
  };
  // How this element sits in its parent's layout. Flex and grid items also get their natural size
  // (what they measure when not stretched), so stretched items can become "fill" in Penpot.
  const itemOf = (el, cs, pcs) => {
    const it = {pos: cs.position, grow: parseFloat(cs.flexGrow) || 0, shrink: parseFloat(cs.flexShrink), basis: cs.flexBasis,
      alignSelf: cs.alignSelf, justifySelf: cs.justifySelf,
      margin: [cs.marginTop, cs.marginRight, cs.marginBottom, cs.marginLeft].map((v) => r2(parseFloat(v) || 0)),
      minW: pxOrNull(cs.minWidth), maxW: pxOrNull(cs.maxWidth), minH: pxOrNull(cs.minHeight), maxH: pxOrNull(cs.maxHeight),
      float: cs.cssFloat !== 'none',
      offset: cs.position === 'relative' && ['top', 'right', 'bottom', 'left'].some((k) => cs[k] !== 'auto' && parseFloat(cs[k]) !== 0)};
    // A centred block's own width rule (e.g. min(100% - 48px, 1200px)) tells whether it follows its parent.
    if (!/absolute|fixed/.test(cs.position) && cs.marginLeft === cs.marginRight && parseFloat(cs.marginLeft) > 0.5) {
      it.wspec = specified(el, 'width');
    }
    if (pcs && /flex|grid/.test(pcs.display) && !/absolute|fixed/.test(cs.position)) {
      const saved = el.getAttribute('style');
      el.style.setProperty('align-self', 'start', 'important');
      if (/grid/.test(pcs.display)) el.style.setProperty('justify-self', 'start', 'important');
      const r = el.getBoundingClientRect();
      if (saved === null) el.removeAttribute('style'); else el.setAttribute('style', saved);
      it.nat = {w: r2(r.width), h: r2(r.height)};
    }
    return it;
  };
  const sameBox = (a, b) => Math.abs(a.x - b.x) <= 0.5 && Math.abs(a.y - b.y) <= 0.5 && Math.abs(a.w - b.w) <= 0.5 && Math.abs(a.h - b.h) <= 0.5;
  const compEls = [];
  let registering = true;

  const processChildren = (el, out, cs) => {
    cs = cs || getComputedStyle(el);
    // Children stay in DOM order (the layout order); each node carries its paint order in z.
    const ordered = [...el.childNodes];
    let run = [];
    const flush = () => {
      if (run.length && !textContentOnlyWhitespace(run.filter((n) => n.nodeType === Node.TEXT_NODE)) || run.some((n) => n.nodeType === Node.ELEMENT_NODE && n.tagName.toLowerCase() !== 'br' && clean(n.textContent))) {
        emitRun(run, el, out);
      }
      run = [];
    };
    for (const n of ordered) {
      if (n.nodeType === Node.COMMENT_NODE) continue;
      if (n.nodeType === Node.TEXT_NODE || (n.nodeType === Node.ELEMENT_NODE && isInlineLevel(n))) { run.push(n); continue; }
      if (n.nodeType !== Node.ELEMENT_NODE) continue;
      flush();
      walk(n, out, cs);
    }
    flush();
  };

  const walk = (el, out, pcs) => {
    const tag = el.tagName.toLowerCase();
    if (SKIP.has(tag)) return;
    const cs = getComputedStyle(el);
    if (cs.display === 'none') return;
    if (cs.display === 'contents') { processChildren(el, out, pcs); return; }
    stats.elements += 1;
    if (cs.visibility === 'hidden' || parseFloat(cs.opacity) === 0) {
      if (el.querySelector('*') && cs.visibility === 'hidden') issue('hidden-subtree-skipped', el, 'visibility:hidden');
      return;
    }
    for (const pseudo of ['::before', '::after']) {
      const ps = getComputedStyle(el, pseudo);
      if (ps.content && ps.content !== 'none' && ps.content !== 'normal' && ps.display !== 'none') {
        const pd = (parseColor(ps.backgroundColor) || {}).opacity > 0 || ps.backgroundImage !== 'none' || (ps.content !== '""' && ps.content !== "''");
        if (pd) issue('pseudo-element-ignored', el, pseudo + ' ' + ps.content.slice(0, 30));
      }
    }
    if (cs.transform && cs.transform !== 'none' && !/^matrix\(1, 0, 0, 1, [-\d.]+, [-\d.]+\)$/.test(cs.transform)) issue('transform-approximated', el, cs.transform);
    if (cs.filter && cs.filter !== 'none') issue('filter-ignored', el, cs.filter.slice(0, 60));
    if (cs.mixBlendMode && cs.mixBlendMode !== 'normal') issue('blend-mode-ignored', el, cs.mixBlendMode);
    if (cs.backdropFilter && cs.backdropFilter !== 'none') issue('backdrop-filter-ignored', el, cs.backdropFilter);
    const rect = el.getBoundingClientRect();
    const z = paintKey(el);
    const tagged = (nodes) => {
      const it = itemOf(el, cs, pcs);
      for (const n of nodes) { n.z = z; n.item = it; n.ibox = box(rect); }
      return nodes;
    };
    if (tag === 'svg') { const tmp = []; emitSvg(el, tmp); out.push(...tagged(tmp)); return; }
    if (tag === 'img' || tag === 'picture') {
      const img = tag === 'img' ? el : el.querySelector('img');
      if (!img) return;
      const r = img.getBoundingClientRect();
      if (r.width < 0.5 || r.height < 0.5) return;
      const ics = getComputedStyle(img);
      const fit = ics.objectFit === 'cover' ? 'cover' : ics.objectFit === 'contain' ? 'contain' : 'fill';
      if (fit === 'contain') issue('object-fit-contain-approximated', img, '');
      out.push(...tagged([{kind: 'rect', name: 'Image / ' + short(img.alt || img.getAttribute('src') || 'image', 40), box: box(r),
        fills: [{type: 'image', src: img.currentSrc || img.src, fit, natural: [img.naturalWidth, img.naturalHeight]}],
        strokes: [], radius: radiiOf(ics, r), shadows: shadowsOf(ics, img), opacity: parseFloat(ics.opacity) || 1}]));
      stats.images += 1;
      return;
    }
    if (tag === 'video' || tag === 'canvas' || tag === 'iframe') { issue('media-unsupported', el, tag); return; }
    if (tag === 'input' || tag === 'textarea' || tag === 'select') {
      const dec = decoration(el, cs, rect);
      const fb = box(rect);
      const sides = dec.border && dec.border.sides
        ? borderLayers(el, dec, [Math.round(fb.x), Math.round(fb.y), Math.round(fb.x + fb.w), Math.round(fb.y + fb.h)]) : [];
      out.push(...tagged([{kind: 'board', name: nameOf(el), box: fb, fills: dec.fills, strokes: dec.strokes, radius: dec.radius,
        shadows: dec.shadows, opacity: parseFloat(cs.opacity) || 1, clip: true, children: sides, formControl: tag}]));
      issue('form-control-text-not-carried', el, 'value/placeholder not converted');
      stats.boards += 1;
      return;
    }
    const section = isSectionEl(el);
    const component = el.dataset ? el.dataset.component || null : null;
    const dec = decoration(el, cs, rect, true);
    const named = el.dataset && el.dataset.name;
    const opacity = parseFloat(cs.opacity);
    const kids = [];
    processChildren(el, kids, cs);
    const own = section || component || dec.visible || named || opacity < 1;
    // A static box that paints nothing and holds only positioned content is no layer of its own in
    // CSS: that content paints among the positioned boxes, in tree order, so the box takes their place.
    let zz = z;
    if (z === 0 && !dec.visible && kids.length && kids.every((k) => (k.z || 0) > 0)) zz = Math.min(...kids.map((k) => k.z));
    const b = box(rect);
    if (!own) {
      if (!kids.length) return;  // empty spacers: the layout margins keep their space
      // A plain wrapper around exactly one layer of the same size adds nothing: the layer takes its
      // place (and its place in the parent's layout).
      if (kids.length === 1 && !kids[0].deco && sameBox(kids[0].box, b)) {
        const k = kids[0];
        k.item = itemOf(el, cs, pcs);
        k.ibox = b;
        if (k.z === undefined || z !== 0) k.z = z;
        out.push(k);
        return;
      }
    }
    // Every other element with content is a board, so its layout (flex, grid, block flow) can be carried.
    const node = {kind: 'board', name: nameOf(el, section ? 'section' : 'element'), box: b, fills: dec.fills, strokes: dec.strokes,
      radius: dec.radius, shadows: dec.shadows, opacity: Number.isFinite(opacity) ? opacity : 1,
      clip: cs.overflow !== 'visible' || cs.overflowX !== 'visible' || cs.overflowY !== 'visible' || false,
      section, component, layout: layoutOf(el, cs), item: itemOf(el, cs, pcs), z: zz, tag, children: kids};
    if (!own) node.wrapper = true;
    // The browser paints borders on whole pixels (it snaps the border box's edges to the pixel
    // grid); Penpot draws a layer where it is put, so a hairline at y 247.56 would smear over two rows.
    const L = Math.round(b.x), T = Math.round(b.y), R = Math.round(b.x + b.w), B = Math.round(b.y + b.h);
    if (dec.border && dec.border.sides) kids.push(...borderLayers(el, dec, [L, T, R, B]));
    if (dec.border && dec.border.double) {
      const db = dec.border.double, s = db.inset;
      kids.push({kind: 'rect', name: 'Border / double (inner line)', box: {x: r2(b.x + s), y: r2(b.y + s), w: r2(b.w - 2 * s), h: r2(b.h - 2 * s)},
        fills: [], strokes: [{color: db.color.color, opacity: db.color.opacity, width: db.width, align: 'inner', style: 'solid'}],
        radius: dec.radius.map((r) => r2(Math.max(0, r - s))), shadows: [], opacity: 1, deco: 'over', z: 0});
    }
    // Background layers above the first one the box's own fills can't carry: under everything else.
    dec.runs.forEach((run, k) => kids.push({kind: 'rect', name: run.raster ? 'Background texture (raster)' : 'Background layers',
      box: {...b}, fills: run.raster ? [{type: 'image', src: run.src, texture: true, fit: 'fill'}] : run.fills, strokes: [],
      radius: dec.radius, shadows: [], opacity: 1, deco: 'under', bg: k, z: -100 + k}));
    if (dec.outline) {
      const o = dec.outline, g = o.offset + o.width;
      kids.push({kind: 'rect', name: 'Focus ring', box: {x: r2(b.x - g), y: r2(b.y - g), w: r2(b.w + 2 * g), h: r2(b.h + 2 * g)}, fills: [],
        strokes: [{color: o.color, opacity: o.opacity, width: o.width, align: 'inner', style: o.style}],
        radius: dec.radius.map((r) => (r > 0 ? r2(r + g) : 0)), shadows: [], opacity: 1, deco: 'over', z: 0});
    }
    stats.boards += 1;
    if (component && registering) compEls.push([el, node]);
    out.push(node);
  };

  const body = document.body;
  const bodyCs = getComputedStyle(body);
  let pageBg = parseColor(bodyCs.backgroundColor);
  if (!visibleColor(pageBg)) pageBg = parseColor(getComputedStyle(doc).backgroundColor);
  if (!visibleColor(pageBg)) pageBg = {color: '#FFFFFF', opacity: 1};
  const pageFills = [{type: 'color', color: pageBg.color, opacity: 1}];
  const bodyDec = decoration(body, bodyCs, body.getBoundingClientRect());
  for (const f of bodyDec.fills) if (f.type !== 'color') pageFills.push(f);
  const nodes = [];
  processChildren(body, nodes, bodyCs);

  // ---------- component states (hover, focus) -> Penpot variants ----------
  // State rules are copied with the pseudo-class swapped for a class, so each state can be switched
  // on, read like the default and compared with it. Only states that change something are kept.
  if (opts.states && compEls.length) {
    const rewritten = [];
    const rewrite = (sel) => sel.replace(/:hover\b/g, '.__pp-hover').replace(/:focus-visible\b/g, '.__pp-focus').replace(/:focus\b(?!-)/g, '.__pp-focus');
    const visitRules = (list, wrap) => {
      for (const rule of list) {
        if (rule.media && rule.cssRules) { const m = rule.media.mediaText; visitRules(rule.cssRules, (t) => wrap('@media ' + m + '{' + t + '}')); continue; }
        if (rule.cssRules && !rule.selectorText) { visitRules(rule.cssRules, wrap); continue; }
        if (rule.selectorText && rule.style && /:(hover|focus)/.test(rule.selectorText)) rewritten.push(wrap(rewrite(rule.selectorText) + '{' + rule.style.cssText + '}'));
      }
    };
    for (const sheet of document.styleSheets) { let rules; try { rules = sheet.cssRules; } catch (e) { continue; } visitRules(rules, (t) => t); }
    if (rewritten.length) {
      const still = document.createElement('style');
      still.textContent = '*,*::before,*::after{transition:none!important;animation:none!important}';
      document.head.appendChild(still);
      const st = document.createElement('style');
      document.head.appendChild(st);
      const savedIssues = issues.length, savedStats = Object.assign({}, stats);
      registering = false;
      const FOCUSABLE = 'a[href],button,input,select,textarea,[tabindex]';
      const snap = (el) => { const tmp = []; walk(el, tmp, el.parentElement ? getComputedStyle(el.parentElement) : null); return tmp[0] || null; };
      const key = (n) => JSON.stringify(n, (k, v) => (k === 'item' || k === 'ibox' ? undefined : v));
      for (const [el, node] of compEls) {
        st.textContent = '';
        const base = snap(el);
        st.textContent = rewritten.join('\n');
        const variants = {};
        const chain = [];
        for (let a = el; a && a !== document.documentElement; a = a.parentElement) chain.push(a);
        chain.forEach((a) => a.classList.add('__pp-hover'));
        const hov = snap(el);
        chain.forEach((a) => a.classList.remove('__pp-hover'));
        if (hov && base && key(hov) !== key(base)) variants.Hover = hov;
        const f = el.matches(FOCUSABLE) ? el : el.querySelector(FOCUSABLE);
        if (f) {
          f.classList.add('__pp-focus');
          const foc = snap(el);
          f.classList.remove('__pp-focus');
          if (foc && base && key(foc) !== key(base)) variants.Focus = foc;
        }
        if (Object.keys(variants).length) node.states = variants;
      }
      st.remove();
      still.remove();
      registering = true;
      issues.length = savedIssues;
      Object.assign(stats, savedStats);
    }
  }
  return {version: 2, url: location.href, title: document.title, width: W, height: H,
    viewport: [window.innerWidth, window.innerHeight], background: pageFills, vars,
    body: {box: box(body.getBoundingClientRect()), layout: layoutOf(body, bodyCs)},
    fonts: fonts.filter((f) => usedFonts.has(f.family.toLowerCase() + '|' + f.weight + '|' + f.style)),
    fontsUsed: [...usedFonts.values()], nodes, textures, issues, stats};
}
