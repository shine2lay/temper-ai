// design_capture_next's in-page measurements (design role; candidate for design_measure.js).
// One function expression, evaluated in the page after axe-core: what a reviewer would
// otherwise guess at. Every list is capped, and every item names its element by a CSS path.
// Next to design_measure.js: target size follows WCAG 2.5.8 in full (a control's labels count
// as its target; undersized targets pass by the spacing exception) and lists the passes, and
// text of inactive (disabled) controls is exempt from contrast, as WCAG 1.4.3/1.4.11 say.
(async () => {
  const LIMIT = 25;

  // BEGIN target-geometry: pure, no DOM (tests/test_design_review_next.py runs this block in node).
  // WCAG 2.5.8 Target Size (Minimum), AA. Each target: {id, rect: [x, y, w, h], labels: [[x, y, w, h]],
  // skip: [ids nested in it or around it], exempt: "inline" or absent}. A target passes by size when
  // its own box, or the box of one of its labels (clicking a label activates its control), is at
  // least 24x24 CSS px. An undersized target passes by spacing when a 24 px circle centred on its
  // bounding box (own box plus labels) meets no other target's box and no other undersized
  // target's circle (centres at least 24 px apart). Exempt targets are not judged themselves but
  // still count as other targets. Returns one result per target, in order.
  const MIN = 24;
  const distToRect = (p, r) => {
    const dx = Math.max(r[0] - p[0], 0, p[0] - (r[0] + r[2]));
    const dy = Math.max(r[1] - p[1], 0, p[1] - (r[1] + r[3]));
    return Math.hypot(dx, dy);
  };
  const targetGeometry = (targets) => {
    const EPS = 0.01;
    const info = targets.map((t) => {
      const rects = [t.rect, ...(t.labels || [])];
      const big = rects.find((r) => r[2] >= MIN - EPS && r[3] >= MIN - EPS) || null;
      const x0 = Math.min(...rects.map((r) => r[0]));
      const y0 = Math.min(...rects.map((r) => r[1]));
      const x1 = Math.max(...rects.map((r) => r[0] + r[2]));
      const y1 = Math.max(...rects.map((r) => r[1] + r[3]));
      return { t, rects, big, centre: [(x0 + x1) / 2, (y0 + y1) / 2] };
    });
    return info.map((a) => {
      const res = { id: a.t.id, undersized: !a.big, passes: null, by: null, nearest: null };
      if (a.t.exempt) { res.passes = a.t.exempt; return res; }
      if (a.big) { res.passes = a.big === a.t.rect ? "size" : "label"; res.by = a.big; return res; }
      let hit = null;
      let nearest = null;
      for (const b of info) {
        if (b === a || (a.t.skip || []).includes(b.t.id) || (b.t.skip || []).includes(a.t.id)) continue;
        const edge = Math.min(...b.rects.map((r) => distToRect(a.centre, r)));
        const small = !b.big && !b.t.exempt;
        const centre = small ? Math.hypot(a.centre[0] - b.centre[0], a.centre[1] - b.centre[1]) : null;
        const near = { id: b.t.id, edge: +edge.toFixed(1), centre: centre === null ? null : +centre.toFixed(1) };
        const kind = edge < MIN / 2 - EPS ? "target" : (centre !== null && centre < MIN - EPS ? "circle" : null);
        if (kind && (!hit || edge < hit.edge)) hit = { ...near, hit: kind };
        if (!nearest || edge < nearest.edge) nearest = near;
      }
      res.passes = hit ? null : "spacing";
      res.nearest = hit || nearest;
      return res;
    });
  };
  // END target-geometry

  const parse = (c) => {
    const m = (c || "").match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(/[\s,\/]+/).filter(Boolean).map(Number);
    return [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
  };
  const lum = ([r, g, b]) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
  const blend = (fg, bg) => { const a = fg[3]; return [0, 1, 2].map((i) => fg[i] * a + bg[i] * (1 - a)).concat([1]); };
  const bgOf = (el) => {
    const layers = [];
    for (let e = el; e; e = e.parentElement) {
      const c = parse(getComputedStyle(e).backgroundColor);
      if (c && c[3] > 0) { layers.push(c); if (c[3] >= 1) break; }
    }
    let bg = [255, 255, 255, 1];
    for (let i = layers.length - 1; i >= 0; i--) bg = blend(layers[i], bg);
    return bg;
  };
  const rgb = (c) => `rgb(${c.slice(0, 3).map(Math.round).join(",")})`;
  const sel = (el) => {
    if (el.id) return "#" + el.id;
    const parts = [];
    for (let e = el; e && e !== document.body && parts.length < 4; e = e.parentElement) {
      let s = e.tagName.toLowerCase();
      if (e.classList.length) s += "." + [...e.classList].slice(0, 2).join(".");
      const sib = e.parentElement ? [...e.parentElement.children].filter((x) => x.tagName === e.tagName) : [];
      if (sib.length > 1) s += `:nth-of-type(${sib.indexOf(e) + 1})`;
      parts.unshift(s);
      if (e.id) { parts[0] = "#" + e.id; break; }
    }
    return parts.join(" > ");
  };
  const visible = (el) => {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && cs.display !== "none"
      && parseFloat(cs.opacity) > 0 && r.right > 0 && r.bottom + scrollY > 0;
  };
  const snip = (t) => (t || "").replace(/\s+/g, " ").trim().slice(0, 90);
  const textOfIds = (ids) => ids.split(/\s+/).map((i) => document.getElementById(i)).filter(Boolean)
    .map((e) => e.innerText).join(" ");
  const nameOf = (el) => {
    if (el.getAttribute("aria-labelledby")) return ["aria-labelledby", snip(textOfIds(el.getAttribute("aria-labelledby")))];
    if (el.getAttribute("aria-label")) return ["aria-label", snip(el.getAttribute("aria-label"))];
    if (el.labels && el.labels.length) return ["label", snip([...el.labels].map((l) => l.innerText).join(" "))];
    if (el.tagName === "IMG") return el.hasAttribute("alt") ? ["alt", el.getAttribute("alt")] : ["none", ""];
    const own = snip(el.innerText || "");
    if (own && !["INPUT", "SELECT", "TEXTAREA"].includes(el.tagName)) return ["content", own];
    if (el.getAttribute("title")) return ["title", snip(el.getAttribute("title"))];
    if (el.getAttribute("placeholder")) return ["placeholder only", snip(el.getAttribute("placeholder"))];
    return ["none", ""];
  };
  const box = (el) => { const r = el.getBoundingClientRect(); return [Math.round(r.left), Math.round(r.top + scrollY), Math.round(r.width), Math.round(r.height)]; };
  const rectOf = (el) => { const r = el.getBoundingClientRect(); return [r.left, r.top + scrollY, r.width, r.height]; };
  const disabledCtl = (el) => !!el && (el.matches(":disabled") || el.getAttribute("aria-disabled") === "true");
  const inactive = (el) => {
    if (el.closest(':disabled,[aria-disabled="true"]')) return true;
    const label = el.closest("label");
    return !!(label && label.control && disabledCtl(label.control));
  };

  const out = { url: location.pathname, title: document.title, viewport: [innerWidth, innerHeight],
    page_height: document.documentElement.scrollHeight };

  // Text: every element that holds visible text of its own.
  const texts = [];
  const seen = new Set();
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const n = walker.currentNode;
    if (!n.nodeValue.trim()) continue;
    const el = n.parentElement;
    if (!el || seen.has(el) || el.closest("svg,script,style,noscript,template")) continue;
    seen.add(el);
    if (!visible(el)) continue;
    const cs = getComputedStyle(el);
    const bg = bgOf(el);
    const fg = blend(parse(cs.color) || [0, 0, 0, 1], bg);
    const size = parseFloat(cs.fontSize);
    const weight = parseInt(cs.fontWeight, 10);
    const large = size >= 24 || (size >= 18.66 && weight >= 700);
    texts.push({ sel: sel(el), tag: el.tagName.toLowerCase(), text: snip(n.nodeValue), size, weight,
      color: rgb(fg), background: rgb(bg), contrast: +ratio(fg, bg).toFixed(2), needs: large ? 3 : 4.5,
      line_height: cs.lineHeight, transform: cs.textTransform, box: box(el), inactive: inactive(el) });
  }
  // WCAG 1.4.3: text of an inactive user interface component has no contrast requirement.
  out.contrast_failures = texts.filter((t) => t.contrast < t.needs && !t.inactive).slice(0, LIMIT);
  out.contrast_exempt = texts.filter((t) => t.contrast < t.needs && t.inactive).slice(0, LIMIT)
    .map(({ sel, tag, text, size, weight, color, background, contrast, needs }) =>
      ({ sel, tag, text, size, weight, color, background, contrast, needs, why: "inactive (disabled) control" }));
  const styles = {};
  for (const t of texts) { const k = `${t.size}px ${t.weight}`; styles[k] = (styles[k] || 0) + 1; }
  out.type_styles = Object.entries(styles).sort((a, b) => parseFloat(b[0]) - parseFloat(a[0]))
    .map(([style, count]) => ({ style, count }));
  out.largest_text = [...texts].sort((a, b) => b.size - a.size || b.weight - a.weight).slice(0, 8)
    .map(({ sel, tag, text, size, weight, color, transform, box }) => ({ sel, tag, text, size, weight, color, transform, box }));
  out.headings = [...document.querySelectorAll("h1,h2,h3,h4,h5,h6")].filter(visible).map((h) => {
    const cs = getComputedStyle(h);
    return { level: +h.tagName[1], text: snip(h.innerText), size: parseFloat(cs.fontSize), weight: parseInt(cs.fontWeight, 10), box: box(h) };
  });

  // Reading: paragraphs whose lines run long.
  out.long_lines = [...document.querySelectorAll("p,li,dd,blockquote")].filter(visible).map((p) => {
    const cs = getComputedStyle(p);
    const lh = parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.2;
    const r = p.getBoundingClientRect();
    const lines = Math.max(1, Math.round(r.height / lh));
    return { sel: sel(p), text: snip(p.innerText), chars_per_line: Math.round((p.innerText || "").length / lines), lines, width: Math.round(r.width) };
  }).filter((x) => x.lines >= 2 && x.chars_per_line > 90).slice(0, LIMIT);

  // Interactive things: names, sizes, boundaries.
  const interactive = [...document.querySelectorAll(
    'a[href],button,input:not([type=hidden]),select,textarea,[role=button],[role=switch],[role=link],[tabindex]:not([tabindex="-1"])')]
    .filter(visible);
  out.controls = interactive.slice(0, 60).map((el) => {
    const [source, name] = nameOf(el);
    const c = { sel: sel(el), tag: el.tagName.toLowerCase(), role: el.getAttribute("role") || "", name, name_from: source, box: box(el) };
    if (disabledCtl(el)) c.disabled = true;
    return c;
  });
  // Target size (WCAG 2.5.8): judged over every visible target; a link inside a sentence is exempt
  // (the inline exception) but still counts as a neighbour for the others.
  const inlineLink = (el) => el.tagName === "A" && getComputedStyle(el).display === "inline" && el.parentElement
    && snip(el.parentElement.innerText).length > snip(el.innerText).length + 5;
  const geo = targetGeometry(interactive.map((el, i) => ({
    id: i,
    rect: rectOf(el),
    labels: [...(el.labels || [])].filter((l) => visible(l)).map(rectOf).filter((r) => r[2] >= 4 && r[3] >= 4),
    skip: interactive.map((o, j) => (o !== el && (o.contains(el) || el.contains(o)) ? j : -1)).filter((j) => j >= 0),
    exempt: inlineLink(el) ? "inline" : undefined,
  })));
  const nb = (n) => n && { sel: sel(interactive[n.id]), name: nameOf(interactive[n.id])[1], edge: n.edge, centre: n.centre };
  const rb = (r) => r.map(Math.round);
  out.small_targets = geo.filter((g) => g.undersized && g.passes === null).slice(0, LIMIT).map((g) => {
    const el = interactive[g.id];
    return { sel: sel(el), name: nameOf(el)[1], box: box(el), too_close_to: nb(g.nearest), hit: g.nearest ? g.nearest.hit : null };
  });
  out.targets_pass = geo.filter((g) => g.passes === "label" || g.passes === "spacing").slice(0, LIMIT).map((g) => {
    const el = interactive[g.id];
    const t = { sel: sel(el), name: nameOf(el)[1], box: box(el), passes: g.passes };
    if (g.passes === "label") t.label_box = rb(g.by);
    else t.nearest = nb(g.nearest);
    return t;
  });
  out.weak_boundaries = [...document.querySelectorAll(
    "input:not([type=hidden]):not([type=checkbox]):not([type=radio]),select,textarea,[role=switch]")]
    .filter(visible).filter((el) => !disabledCtl(el)).map((el) => {
      const cs = getComputedStyle(el);
      const around = bgOf(el.parentElement || document.body);
      let best = 1;
      const b = parse(cs.borderTopColor);
      if (b && parseFloat(cs.borderTopWidth) > 0) best = ratio(blend(b, around), around);
      const own = parse(cs.backgroundColor);
      if (own && own[3] > 0) best = Math.max(best, ratio(blend(own, around), around));
      return { sel: sel(el), name: nameOf(el)[1], boundary_contrast: +best.toFixed(2) };
    }).filter((x) => x.boundary_contrast < 3).slice(0, LIMIT);
  out.fields = [...document.querySelectorAll("input:not([type=hidden]),select,textarea")].filter(visible)
    .slice(0, 40).map((el) => {
      const [source, name] = nameOf(el);
      return { sel: sel(el), type: el.type || el.tagName.toLowerCase(), name, name_from: source,
        value: el.type === "password" ? (el.value ? "(set)" : "") : snip(el.value),
        aria_invalid: el.getAttribute("aria-invalid") || "", described_by: el.getAttribute("aria-describedby") || "" };
    });

  // Graphics without a text alternative (not hidden, not inside a named control).
  out.unnamed_graphics = [...document.querySelectorAll("img,svg")].filter(visible).filter((el) => {
    if (el.closest('[aria-hidden="true"]')) return false;
    if (el.tagName.toLowerCase() === "img") return !el.hasAttribute("alt");
    if (el.parentElement && el.parentElement.closest("svg")) return false;
    const named = el.getAttribute("aria-label") || el.getAttribute("aria-labelledby") || el.querySelector("title");
    const ctl = el.closest("a,button,[role=button]");
    return !named && !(ctl && nameOf(ctl)[1]);
  }).slice(0, LIMIT).map((el) => ({ sel: sel(el), tag: el.tagName.toLowerCase(), src: el.getAttribute("src") || "", box: box(el) }));

  // Reflow: anything sticking out past the viewport, outside a scrolling box.
  const doc = document.documentElement;
  out.page_width = { scroll: doc.scrollWidth, viewport: innerWidth, overflows: doc.scrollWidth > innerWidth + 1 };
  if (out.page_width.overflows) {
    const scrolls = (el) => { for (let e = el.parentElement; e && e !== document.body; e = e.parentElement) {
      const o = getComputedStyle(e).overflowX; if (o === "auto" || o === "scroll" || o === "hidden") return true; } return false; };
    const wide = [...document.body.querySelectorAll("*")].filter((el) => el.getBoundingClientRect().right > innerWidth + 1 && !scrolls(el));
    out.overflowing = wide.filter((el) => !wide.includes(el.parentElement)).slice(0, 10)
      .map((el) => ({ sel: sel(el), box: box(el) }));
  }
  out.landmarks = [...document.querySelectorAll("header,nav,main,footer,aside,[role=banner],[role=navigation],[role=main],[role=contentinfo]")]
    .filter(visible).map((el) => ({ tag: el.tagName.toLowerCase(), label: el.getAttribute("aria-label") || "" }));
  out.text_count = texts.length;
  return out;
})()
