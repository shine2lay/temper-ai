// design_homepage_bar's in-page measurements (Design, queue #78). One function expression; the
// driver calls it as (expr)(opts) in the page after load, document.fonts.ready and settled
// animations, at scroll 0. It returns raw measurements only: no limits are applied here, every
// limit is applied by design_homepage_bar.py's scorer. Definitions: docs/design-homepage-bar.md.
// opts: {min_words: body text needs this many words, chars: count characters per line (1440 only)}.
// Coordinates are page coordinates in CSS px (x, y from the page's top left), rounded to 0.01.
(async (OPTS) => {
  const W = innerWidth;
  const H = innerHeight;
  const SKIP = "svg, script, style, noscript, template";
  const r2 = (v) => Math.round(v * 100) / 100;

  // Colours: rgb()/rgba() parsed directly; any other syntax resolved through a 1x1 canvas.
  const cv = document.createElement("canvas");
  cv.width = 1; cv.height = 1;
  const cx = cv.getContext("2d", { willReadFrequently: true });
  const colours = new Map();
  const parse = (c) => {
    if (!c) return null;
    if (colours.has(c)) return colours.get(c);
    let v;
    const m = c.match(/^rgba?\(([^)]+)\)$/);
    if (m) {
      const p = m[1].split(/[\s,\/]+/).filter(Boolean).map((x) => (x.endsWith("%") ? parseFloat(x) / 100 : parseFloat(x)));
      v = [p[0], p[1], p[2], p.length > 3 ? p[3] : 1];
    } else if (c === "transparent") {
      v = [0, 0, 0, 0];
    } else {
      cx.clearRect(0, 0, 1, 1);
      cx.fillStyle = "#000";
      cx.fillStyle = c;
      cx.fillRect(0, 0, 1, 1);
      const d = cx.getImageData(0, 0, 1, 1).data;
      v = [d[0], d[1], d[2], d[3] / 255];
    }
    colours.set(c, v);
    return v;
  };
  const lum = ([r, g, b]) => {
    const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
    return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
  };
  const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
  const blend = (fg, bg) => { const a = fg[3]; return [0, 1, 2].map((i) => fg[i] * a + bg[i] * (1 - a)).concat([1]); };
  // The background colours behind an element, composited over white (as design_measure.js does).
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
  const rgb = (c) => c.slice(0, 3).map(Math.round);

  const sel = (el) => {
    if (el.id) return "#" + el.id;
    const parts = [];
    for (let e = el; e && e !== document.body && e !== document.documentElement && parts.length < 4; e = e.parentElement) {
      let s = e.localName;
      if (e.classList && e.classList.length) s += "." + [...e.classList].slice(0, 2).join(".");
      const sib = e.parentElement ? [...e.parentElement.children].filter((x) => x.localName === e.localName) : [];
      if (sib.length > 1) s += `:nth-of-type(${sib.indexOf(e) + 1})`;
      parts.unshift(s);
      if (e.id) { parts[0] = "#" + e.id; break; }
    }
    return parts.join(" > ") || el.localName;
  };
  const norm = (t) => (t || "").replace(/\s+/g, " ").trim();

  // Rectangles as [x0, y0, x1, y1] in page coordinates.
  const INF = [-1e9, -1e9, 1e9, 1e9];
  const pageRect = (r) => [r.left, r.top + scrollY, r.right, r.bottom + scrollY];
  const inter = (a, b) => [Math.max(a[0], b[0]), Math.max(a[1], b[1]), Math.min(a[2], b[2]), Math.min(a[3], b[3])];
  const wOf = (a) => Math.max(0, a[2] - a[0]);
  const hOf = (a) => Math.max(0, a[3] - a[1]);
  const xywh = (a) => [r2(a[0]), r2(a[1]), r2(wOf(a)), r2(hOf(a))];

  const styles = new Map();
  const cs = (el) => { let s = styles.get(el); if (!s) { s = getComputedStyle(el); styles.set(el, s); } return s; };

  // Clipping. selfClip: what clip / clip-path do to the element and its contents.
  // contentClip: selfClip plus the element's own non-visible overflow (padding box), per axis.
  // ancClip: what the element's ancestors do to it (a fixed element escapes them).
  const selfClip = (el) => {
    const s = cs(el);
    const r = el.getBoundingClientRect();
    let c = INF.slice();
    if ((s.position === "absolute" || s.position === "fixed") && s.clip && s.clip.startsWith("rect(")) {
      const v = (s.clip.match(/-?[\d.]+px|auto/g) || []).map((x) => (x === "auto" ? null : parseFloat(x)));
      const top = v[0] ?? 0, right = v[1] ?? r.width, bottom = v[2] ?? r.height, left = v[3] ?? 0;
      c = inter(c, [r.left + left, r.top + top + scrollY, r.left + right, r.top + bottom + scrollY]);
    }
    if (s.clipPath && /^inset\(\s*50%/.test(s.clipPath)) c = [0, 0, 0, 0];
    return c;
  };
  const contentClips = new Map();
  const contentClip = (el) => {
    if (contentClips.has(el)) return contentClips.get(el);
    const s = cs(el);
    let c = selfClip(el);
    if (el !== document.documentElement && el !== document.body) {
      const r = el.getBoundingClientRect();
      const bl = parseFloat(s.borderLeftWidth) || 0, br = parseFloat(s.borderRightWidth) || 0;
      const bt = parseFloat(s.borderTopWidth) || 0, bb = parseFloat(s.borderBottomWidth) || 0;
      if (s.overflowX !== "visible") c = inter(c, [r.left + bl, -1e9, r.right - br, 1e9]);
      if (s.overflowY !== "visible") c = inter(c, [-1e9, r.top + bt + scrollY, 1e9, r.bottom - bb + scrollY]);
    }
    contentClips.set(el, c);
    return c;
  };
  const ancClips = new Map();
  const ancClip = (el) => {
    if (ancClips.has(el)) return ancClips.get(el);
    const p = el.parentElement;
    let c = INF.slice();
    if (p && cs(el).position !== "fixed") c = inter(ancClip(p), contentClip(p));
    ancClips.set(el, c);
    return c;
  };
  const opacities = new Map();
  const opacity = (el) => {
    if (!el) return 1;
    if (opacities.has(el)) return opacities.get(el);
    const o = (parseFloat(cs(el).opacity) || 0) * opacity(el.parentElement);
    opacities.set(el, o);
    return o;
  };
  // The part of an element that survives clipping, or null when it is not visible.
  const regions = new Map();
  const region = (el) => {
    if (regions.has(el)) return regions.get(el);
    let out = null;
    const r = el.getBoundingClientRect();
    const s = cs(el);
    if (r.width > 0 && r.height > 0 && s.display !== "none" && s.visibility !== "hidden" && s.visibility !== "collapse"
        && opacity(el) > 0) {
      const c = inter(inter(pageRect(r), ancClip(el)), selfClip(el));
      if (wOf(c) > 1 && hOf(c) > 1) out = c;
    }
    regions.set(el, out);
    return out;
  };
  const textClip = (el) => inter(ancClip(el), contentClip(el));
  const rendered = (el) => el.getClientRects().length > 0;

  const out = {
    viewport: [W, H], scroll_width: document.documentElement.scrollWidth, inner_width: W,
    page_height: document.documentElement.scrollHeight, title: document.title,
    lang: document.documentElement.getAttribute("lang"),
  };

  // Sections: the page header, main's element children, the page footer (else body's children).
  const outsideMain = (e) => !e.parentElement || !e.parentElement.closest("main, [role=main], article");
  const mainEl = document.querySelector("main, [role=main]");
  const pageHeader = [...document.querySelectorAll("header, [role=banner]")].find((e) => !e.closest("main, [role=main], article")) || null;
  const pageFooter = [...document.querySelectorAll("footer, [role=contentinfo]")].find((e) => !e.closest("main, [role=main], article")) || null;
  let sections;
  if (mainEl) {
    sections = [...(pageHeader && outsideMain(pageHeader) ? [pageHeader] : []), ...mainEl.children,
      ...(pageFooter ? [pageFooter] : [])];
  } else {
    sections = [...document.body.children];
  }
  sections = sections.filter((e) => !["script", "style", "template", "noscript", "link", "meta"].includes(e.localName));
  const secIndex = new Map(sections.map((e, i) => [e, i]));
  const sectionOf = (el) => { for (let e = el; e; e = e.parentElement) if (secIndex.has(e)) return secIndex.get(e); return -1; };
  out.sections = sections.map((e, i) => ({ i, sel: sel(e), tag: e.localName }));
  out.footer_text = pageFooter ? pageFooter.innerText || "" : "";
  out.page_text = document.body.innerText || "";

  // Headings and the first rendered h1.
  const heads = [...document.querySelectorAll("h1, h2, h3, h4, h5, h6")];
  const headRendered = (h) => rendered(h) && cs(h).visibility !== "hidden" && !h.closest('[aria-hidden="true"]');
  out.headings = heads.filter(headRendered).map((h) => ({ level: +h.localName[1], sel: sel(h), text: norm(h.innerText).slice(0, 80),
    box: xywh(pageRect(h.getBoundingClientRect())) }));
  const firstH1 = heads.find((h) => h.localName === "h1" && headRendered(h)) || null;
  out.h1 = firstH1 ? { sel: sel(firstH1), text: norm(firstH1.innerText), box: xywh(pageRect(firstH1.getBoundingClientRect())) } : null;

  // Controls: a[href], button, [role=button], input submit/button/reset.
  const controlEls = [...document.querySelectorAll('a[href], button, [role=button], input[type=submit], input[type=button], input[type=reset]')]
    .filter((el) => region(el));
  const ctlIndex = new Map(controlEls.map((e, i) => [e, i]));
  out.controls = controlEls.map((el, i) => {
    const bg = parse(cs(el).backgroundColor) || [0, 0, 0, 0];
    const behind = el.parentElement ? bgOf(el.parentElement) : [255, 255, 255, 1];
    const text = el.localName === "input" ? norm(el.value) : norm(el.innerText);
    return { i, sel: sel(el), tag: el.localName, role: el.getAttribute("role") || "", text: text.slice(0, 200),
      box: xywh(pageRect(el.getBoundingClientRect())), bg: [...rgb(bg), r2(bg[3])], behind: rgb(behind),
      bg_ratio: r2(ratio(bg, behind)) };
  });
  const controlOf = (el) => { for (let e = el; e; e = e.parentElement) if (ctlIndex.has(e)) return ctlIndex.get(e); return -1; };

  // Text elements: elements with their own non-blank text, outside svg/script/style/noscript/template.
  const textEls = [];
  const textIndex = new Map();
  {
    const tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const own = new Map();
    while (tw.nextNode()) {
      const n = tw.currentNode;
      if (!n.nodeValue.trim()) continue;
      const el = n.parentElement;
      if (!el || el.closest(SKIP)) continue;
      if (!own.has(el)) own.set(el, []);
      own.get(el).push(n);
    }
    const rg = document.createRange();
    for (const [el, nodes] of own) {
      if (!region(el)) continue;
      const clip = textClip(el);
      const lines = [];
      for (const n of nodes) {
        rg.selectNodeContents(n);
        for (const q of rg.getClientRects()) {
          if (q.width <= 0 || q.height <= 0) continue;
          const c = inter(pageRect(q), clip);
          if (wOf(c) > 0 && hOf(c) > 0) lines.push({ full: pageRect(q), c });
        }
      }
      if (!lines.some((l) => wOf(l.c) > 1 && hOf(l.c) > 1)) continue;
      const s = cs(el);
      const size = parseFloat(s.fontSize);
      const col = blend(parse(s.color) || [0, 0, 0, 1], bgOf(el));
      const bands = [];
      for (const l of lines) {
        const f = l.full;
        const band = Math.min(hOf(f), 0.7 * size);
        const mid = (f[1] + f[3]) / 2;
        const b = inter([f[0], mid - band / 2, f[2], mid + band / 2], textClip(el));
        if (wOf(b) > 0 && hOf(b) > 0) bands.push(xywh(b));
      }
      textIndex.set(el, textEls.length);
      textEls.push({ el, i: textEls.length, sel: sel(el), tag: el.localName,
        text: norm(nodes.map((n) => n.nodeValue).join(" ")).slice(0, 1000), size: r2(size),
        weight: parseInt(s.fontWeight, 10) || 400, color: rgb(col), lines: lines.map((l) => xywh(l.c)), bands,
        sec: sectionOf(el), ctl: controlOf(el), in_h1: !!(firstH1 && firstH1.contains(el)) });
    }
  }
  for (const t of textEls) {
    const anc = [];
    for (let e = t.el.parentElement; e; e = e.parentElement) if (textIndex.has(e)) anc.push(textIndex.get(e));
    t.anc = anc;
  }
  out.texts = textEls.map(({ el, ...rest }) => rest);

  // Pictures: img, outermost svg, video, canvas, elements with a url() background image (not html/body).
  const pictures = [];
  const pictureEls = [];
  for (const el of document.body.querySelectorAll("*")) {
    let kind = null;
    if (["img", "video", "canvas"].includes(el.localName)) kind = el.localName;
    else if (el.localName === "svg") kind = el.parentElement && el.parentElement.closest("svg") ? null : "svg";
    else if (!el.closest("svg") && (cs(el).backgroundImage || "").includes("url(")) kind = "background-image";
    if (!kind) continue;
    const g = region(el);
    if (!g) continue;
    pictureEls.push(el);
    pictures.push({ kind, sel: sel(el), box: xywh(g), sec: sectionOf(el),
      alt: el.localName === "img" ? el.getAttribute("alt") : null });
  }
  out.pictures = pictures;

  // Content boxes per section, for the rhythm check: text (union of its line boxes), pictures and
  // form controls, at least 2x2 px after clipping. Each is [top, bottom, sel].
  const contentBoxes = sections.map(() => []);
  for (const t of out.texts) {
    if (t.sec < 0) continue;
    const top = Math.min(...t.lines.map((q) => q[1]));
    const bottom = Math.max(...t.lines.map((q) => q[1] + q[3]));
    const left = Math.min(...t.lines.map((q) => q[0]));
    const right = Math.max(...t.lines.map((q) => q[0] + q[2]));
    if (right - left >= 2 && bottom - top >= 2) contentBoxes[t.sec].push([r2(top), r2(bottom), t.sel]);
  }
  for (const p of out.pictures) {
    if (p.sec >= 0 && p.box[2] >= 2 && p.box[3] >= 2) contentBoxes[p.sec].push([p.box[1], r2(p.box[1] + p.box[3]), p.sel]);
  }
  for (const el of document.body.querySelectorAll("input, select, textarea, button")) {
    const g = region(el);
    const sec = sectionOf(el);
    if (g && sec >= 0 && wOf(g) >= 2 && hOf(g) >= 2 && !pictureEls.includes(el)) contentBoxes[sec].push([r2(g[1]), r2(g[3]), sel(el)]);
  }
  out.content_boxes = contentBoxes.map((b) => b.sort((p, q) => p[0] - q[0] || p[1] - q[1]));

  // Body text: p, li, dd, blockquote with min_words or more, outside nav and footer; innermost only.
  const lineGroups = (rects) => {
    const rs = rects.filter((q) => q[2] - q[0] > 0 && q[3] - q[1] > 0).sort((a, b) => (a[1] + a[3]) - (b[1] + b[3]));
    const groups = [];
    for (const q of rs) {
      const c = (q[1] + q[3]) / 2;
      const g = groups[groups.length - 1];
      if (g && c >= g.top && c <= g.bottom) { g.top = Math.min(g.top, q[1]); g.bottom = Math.max(g.bottom, q[3]); }
      else groups.push({ top: q[1], bottom: q[3] });
    }
    return groups;
  };
  const wordsOf = (t) => norm(t).split(" ").filter(Boolean).length;
  const bodyCands = [...document.body.querySelectorAll("p, li, dd, blockquote")].filter((el) => region(el)
    && !el.closest("nav, footer, [role=navigation], [role=contentinfo]") && wordsOf(el.innerText) >= OPTS.min_words);
  const bodyEls = bodyCands.filter((el) => !bodyCands.some((o) => o !== el && el.contains(o)));
  {
    const rg = document.createRange();
    out.body = bodyEls.map((el) => {
      const s = cs(el);
      rg.selectNodeContents(el);
      const groups = lineGroups([...rg.getClientRects()].map(pageRect));
      const item = { sel: sel(el), tag: el.localName, words: wordsOf(el.innerText), size: r2(parseFloat(s.fontSize)),
        line_height: s.lineHeight, line_height_px: s.lineHeight.endsWith("px") ? r2(parseFloat(s.lineHeight)) : null,
        content_height: r2(el.clientHeight - (parseFloat(s.paddingTop) || 0) - (parseFloat(s.paddingBottom) || 0)),
        lines: groups.length, text: norm(el.innerText).slice(0, 5000), box: xywh(pageRect(el.getBoundingClientRect())) };
      if (OPTS.chars) {
        const counts = groups.map(() => 0);
        const tw = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
        while (tw.nextNode()) {
          const n = tw.currentNode;
          if (n.parentElement && n.parentElement.closest(SKIP)) continue;
          const v = n.nodeValue;
          for (let i = 0; i < v.length;) {
            const len = v.codePointAt(i) > 0xffff ? 2 : 1;
            rg.setStart(n, i);
            rg.setEnd(n, i + len);
            const q = [...rg.getClientRects()].find((x) => x.width > 0 && x.height > 0);
            if (q) {
              const c = q.top + scrollY + q.height / 2;
              const g = groups.findIndex((gr) => c >= gr.top && c <= gr.bottom);
              if (g >= 0) counts[g] += 1;
            }
            i += len;
          }
        }
        item.line_chars = counts;
      }
      return item;
    });
  }

  // Spacing values: margins and paddings of visible elements (not inside svg, larger than 1x1),
  // and row/column gaps of flex and grid boxes. Keyword values (auto, normal) are skipped and so
  // is 0. Counted by value in px.
  {
    const SIDES = ["margin-top", "margin-right", "margin-bottom", "margin-left",
      "padding-top", "padding-right", "padding-bottom", "padding-left"];
    const counts = {};
    let keywordSkipped = 0;
    const add = (px) => { const k = String(r2(Math.abs(px))); counts[k] = (counts[k] || 0) + 1; };
    for (const el of [document.body, ...document.body.querySelectorAll("*")]) {
      if (el.closest("svg") || ["script", "style", "template", "noscript"].includes(el.localName) || !region(el)) continue;
      const s = cs(el);
      const map = el.computedStyleMap ? el.computedStyleMap() : null;
      const props = [...SIDES];
      if (/(^|-)(flex|grid)$/.test(s.display) || s.display.includes("flex") || s.display.includes("grid")) props.push("row-gap", "column-gap");
      for (const p of props) {
        const tv = map ? map.get(p) : null;
        const raw = s.getPropertyValue(p);
        if ((tv && typeof CSSKeywordValue !== "undefined" && tv instanceof CSSKeywordValue) || raw === "normal" || raw === "auto") { keywordSkipped += 1; continue; }
        const px = parseFloat(raw);
        if (!px) continue;
        add(px);
      }
    }
    out.spacing = { counts, keyword_skipped: keywordSkipped, typed_om: !!document.body.computedStyleMap };
  }

  // Landmarks, lang, images, svgs.
  const anyRendered = (q) => [...document.querySelectorAll(q)].some(rendered);
  out.landmarks = { main: anyRendered("main, [role=main]"), header_or_nav: anyRendered("header, [role=banner], nav, [role=navigation]"),
    footer: anyRendered("footer, [role=contentinfo]") };
  const imgs = [...document.querySelectorAll("img")];
  out.images = { count: imgs.length, no_alt: imgs.filter((i) => !i.hasAttribute("alt"))
    .map((i) => ({ sel: sel(i), text: (i.getAttribute("src") || "").slice(0, 80), box: xywh(pageRect(i.getBoundingClientRect())) })) };
  const nameOfIds = (ids) => ids.split(/\s+/).map((i) => document.getElementById(i)).filter(Boolean).map((e) => e.textContent).join(" ");
  out.svgs = [...document.querySelectorAll("svg")].filter((s) => !(s.parentElement && s.parentElement.closest("svg")) && rendered(s))
    .map((s) => {
      const r = s.getBoundingClientRect();
      const title = [...s.children].find((c) => c.localName === "title");
      const name = norm(s.getAttribute("aria-label") || (s.getAttribute("aria-labelledby") ? nameOfIds(s.getAttribute("aria-labelledby")) : "")
        || (title ? title.textContent : ""));
      return { sel: sel(s), w: r2(r.width), h: r2(r.height), role: s.getAttribute("role") || "", name: name.slice(0, 80),
        hidden: !!s.closest('[aria-hidden="true"]'), box: xywh(pageRect(r)) };
    });

  // Overflowing elements (not html or body) with non-visible overflow, or an ellipsis.
  {
    const rg = document.createRange();
    const list = [];
    for (const el of document.body.querySelectorAll("*")) {
      if (el.closest(SKIP)) continue;
      const s = cs(el);
      const ox = s.overflowX !== "visible", oy = s.overflowY !== "visible";
      const ell = s.textOverflow === "ellipsis";
      if (!ox && !oy && !ell) continue;
      const g = region(el);
      if (!g) continue;
      const dx = el.scrollWidth - el.clientWidth, dy = el.scrollHeight - el.clientHeight;
      if (dx <= 0 && dy <= 0) continue;
      const r = el.getBoundingClientRect();
      const cl = r.left + el.clientLeft, ct = r.top + el.clientTop + scrollY;
      const box = [cl, ct, cl + el.clientWidth, ct + el.clientHeight];
      let pastX = 0, pastY = 0;
      const tw = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
      let ownText = false;
      while (tw.nextNode()) {
        const n = tw.currentNode;
        if (!n.nodeValue.trim() || (n.parentElement && n.parentElement.closest(SKIP))) continue;
        if (n.parentElement === el) ownText = true;
        rg.selectNodeContents(n);
        for (const q of rg.getClientRects()) {
          if (q.width <= 0 || q.height <= 0) continue;
          const p = pageRect(q);
          pastX = Math.max(pastX, box[0] - p[0], p[2] - box[2]);
          pastY = Math.max(pastY, box[1] - p[1], p[3] - box[3]);
        }
      }
      list.push({ sel: sel(el), overflow_x: s.overflowX, overflow_y: s.overflowY, ellipsis: ell,
        scroll_width: el.scrollWidth, client_width: el.clientWidth, scroll_height: el.scrollHeight, client_height: el.clientHeight,
        own_text: ownText, text_past_x: r2(pastX), text_past_y: r2(pastY), text: norm(el.innerText).slice(0, 80), box: xywh(g) });
    }
    out.overflowing = list;
  }
  return out;
})
