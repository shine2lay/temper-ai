// design_page_checks.js: model-free page checks (design role, queue #39, 2026-10-05).
// One function expression, evaluated in the page by design_capture.py --page-checks once per view,
// after design_measure.js. It collects raw facts only; design_page_checks.py judges them against the
// frozen thresholds in design_page_checks_thresholds.json. Lists are capped; elements are named by a
// CSS path. What it collects:
//   copy        visible prose per section, without links, buttons, navigation and tables (repeated copy)
//   action      where the brief's primary action first appears (first-screen action, judged on the phone)
//   nav         the main navigation's links and how many lines they take (nav fit, judged on the phone)
//   columns     empty columns: a gap in the page's content frame that runs beside content (desktop)
//   cues        interactive elements and whether each has a visible cue (border, fill, shadow,
//               underline or icon); links in a header or footer navigation bar are counted apart
//   overlays    text over an image, a gradient or a translucent layer, with its line boxes, so
//               design_capture.py can measure contrast from the pixels behind it
//   small_dark  running text under the dark-text minimum on a dark background (light text on dark)
//   visuals     non-text pictures (img, svg, canvas, video, CSS background images) per section and
//               in the first screen; icons under the icon size are left out
//   dark        whether the page offers a dark colour scheme (prefers-color-scheme: dark)
// Candidate text for the pixel step is marked data-pc-cand="<n>"; design_capture.py removes the marks.
(async (opts) => {
  const T = opts.thresholds;
  const LIMIT = 30;
  const W = innerWidth;
  const H = innerHeight;

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
  const differs = (a, b) => Math.max(...[0, 1, 2].map((i) => Math.abs(a[i] - b[i]))) >= T.signifier.min_channel_diff;
  const rgb = (c) => `rgb(${c.slice(0, 3).map(Math.round).join(",")})`;
  const sel = (el) => {
    if (el.id) return "#" + el.id;
    const parts = [];
    for (let e = el; e && e !== document.body && parts.length < 4; e = e.parentElement) {
      let s = e.localName;
      if (e.classList && e.classList.length) s += "." + [...e.classList].slice(0, 2).join(".");
      const sib = e.parentElement ? [...e.parentElement.children].filter((x) => x.localName === e.localName) : [];
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
      && parseFloat(cs.opacity) > 0 && r.right > 0 && r.bottom + scrollY > 0 && r.left < W + 1;
  };
  const snip = (t, n = 80) => (t || "").replace(/\s+/g, " ").trim().slice(0, n);
  const box = (r) => [Math.round(r.left), Math.round(r.top + scrollY), Math.round(r.width), Math.round(r.height)];
  const nameOf = (el) => snip(el.getAttribute("aria-label") || el.innerText || el.value || el.getAttribute("title") || el.getAttribute("alt") || "", 60);

  // Sections: [data-section] (outermost), else the page's top-level landmarks.
  let sections = [...document.querySelectorAll("[data-section]")].filter((e) => !e.parentElement.closest("[data-section]"));
  if (!sections.length) {
    sections = [...document.querySelectorAll("body > header, body > nav, body > main > section, body > main > *, body > section, body > footer")];
  }
  sections = sections.filter(visible);
  const sectionName = (s) => snip(s.dataset.section || s.getAttribute("aria-label")
    || (s.querySelector("h1, h2, h3") || {}).innerText || s.localName, 40);
  const isChrome = (s) => s.matches("header, footer, nav, [role=banner], [role=contentinfo], [role=navigation]")
    || /^(site )?(header|footer|nav|navigation|top bar|masthead)$/i.test((s.dataset.section || "").trim());
  const sectionOf = (el) => sections.find((s) => s.contains(el)) || null;

  const out = { viewport: [W, H], page_height: document.documentElement.scrollHeight,
    sections: sections.map((s) => ({ name: sectionName(s), chrome: isChrome(s), box: box(s.getBoundingClientRect()) })) };

  // Dark colour scheme on offer?
  const darkRule = (rules) => {
    for (const r of rules || []) {
      try {
        if (r.conditionText && /prefers-color-scheme\s*:\s*dark/i.test(r.conditionText)) return true;
        if (r.cssRules && darkRule(r.cssRules)) return true;
      } catch (e) { /* unreadable rule */ }
    }
    return false;
  };
  let dark = false;
  for (const sh of document.styleSheets) { try { if (darkRule(sh.cssRules)) { dark = true; break; } } catch (e) { /* cross-origin */ } }
  const meta = document.querySelector('meta[name="color-scheme"]');
  if (meta && /dark/i.test(meta.content || "")) dark = true;
  if (/dark/i.test(getComputedStyle(document.documentElement).colorScheme || "")) dark = true;
  out.dark = dark;

  // Copy per section (prose only: links, buttons, navigation, tables, forms and graphics left out).
  if (opts.copy) {
    const SKIP = "a, button, nav, table, svg, script, style, noscript, template, label, select, option, textarea, input, [aria-hidden='true'], [role='navigation']";
    const BLOCK = "p, li, h1, h2, h3, h4, h5, h6, dd, dt, blockquote, figcaption, caption, td, th";
    out.copy = sections.filter((s) => !isChrome(s)).map((s) => {
      const blocks = new Map();
      const tw = document.createTreeWalker(s, NodeFilter.SHOW_TEXT);
      while (tw.nextNode()) {
        const n = tw.currentNode;
        if (!n.nodeValue.trim()) continue;
        const el = n.parentElement;
        if (!el || !visible(el)) continue;
        const skip = el.closest(SKIP);
        if (skip && s.contains(skip)) continue;
        const owner = el.closest(BLOCK) || el;
        blocks.set(owner, (blocks.get(owner) || "") + " " + n.nodeValue);
      }
      return { name: sectionName(s), blocks: [...blocks.values()].map((t) => snip(t, 2000)).filter(Boolean) };
    });
  }

  // Primary action: the first visible control that carries the brief's whole label; a control whose
  // words are all part of the label ("Demo rooms" for "Explore demo rooms") counts only when no
  // control carries the whole label and it is not a navigation link.
  if (opts.primary) {
    const STOP = new Set(["a", "an", "the", "your", "my", "our", "to", "for", "now", "today", "free"]);
    const words = (t) => (t || "").toLowerCase().replace(/[^a-z0-9]+/g, " ").trim().split(" ").filter((w) => w && !STOP.has(w));
    const want = words(opts.primary);
    const found = [];
    for (const el of document.querySelectorAll("a[href], button, [role='button'], input[type='submit'], input[type='button']")) {
      if (!visible(el)) continue;
      const have = words(el.innerText || el.value || el.getAttribute("aria-label") || "");
      if (!have.length || !want.length) continue;
      const whole = want.every((w) => have.includes(w));
      const part = !whole && have.length >= 2 && have.every((w) => want.includes(w)) && !el.closest("nav, [role='navigation']");
      if (!whole && !part) continue;
      const r = el.getBoundingClientRect();
      found.push({ sel: sel(el), text: snip(el.innerText || el.value, 60), top: Math.round(r.top + scrollY),
        bottom: Math.round(r.bottom + scrollY), whole, section: (sectionOf(el) && sectionName(sectionOf(el))) || "" });
    }
    found.sort((a, b) => (b.whole - a.whole) || (a.top - b.top));
    out.action = { label: opts.primary, found: found.length, first: found[0] || null, screen_height: H };
  }

  // Navigation: the first visible nav in the page header (a footer's link list is not the main nav).
  {
    const navs = [...document.querySelectorAll("nav, [role='navigation']")].filter(visible);
    const inHeader = navs.filter((n) => n.closest("header, [role='banner']") || (sectionOf(n) && sectionOf(n) === sections[0]));
    const nav = inHeader.find((n) => !n.closest("footer, [role='contentinfo']")) || null;
    if (!nav) {
      out.nav = { found: false };
    } else {
      const links = [...nav.querySelectorAll("a[href], button, [role='button'], [role='link']")].filter(visible);
      const rects = links.map((a) => a.getBoundingClientRect());
      const order = rects.map((r, i) => [r.top + r.height / 2, i]).sort((a, b) => a[0] - b[0]);
      const rows = [];
      for (const [cy, i] of order) {
        const row = rows.find((rw) => Math.abs(rw.cy - cy) <= Math.max(8, rects[i].height / 2));
        if (row) row.items.push(i); else rows.push({ cy, items: [i] });
      }
      const header = nav.closest("header, [role='banner']") || sections[0] || nav;
      out.nav = {
        found: true, sel: sel(nav), header_height: Math.round(header.getBoundingClientRect().height),
        links: links.map((a, i) => ({ text: nameOf(a), box: box(rects[i]) })).slice(0, LIMIT),
        lines: rows.length,
        rows: rows.map((rw) => rw.items.map((i) => nameOf(links[i]))),
        wrapped: links.filter((a) => a.getClientRects().length > 1).map((a) => nameOf(a)),
        overflow: links.filter((a, i) => rects[i].right > W + 1 || rects[i].left < -1).map((a) => nameOf(a)),
      };
    }
  }

  // Content boxes: text line boxes, replaced elements and boxes a person sees (fill, border, shadow, image).
  const contentBoxes = (root) => {
    const boxes = [];
    const tw = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    while (tw.nextNode()) {
      const n = tw.currentNode;
      if (!n.nodeValue.trim()) continue;
      const el = n.parentElement;
      if (!el || el.closest("svg") || !visible(el)) continue;
      const rg = document.createRange();
      rg.selectNodeContents(n);
      for (const q of rg.getClientRects()) {
        if (q.width > 1 && q.height > 1) boxes.push([q.left, q.top + scrollY, q.right, q.bottom + scrollY]);
      }
    }
    const rootW = root.getBoundingClientRect().width;
    for (const el of root.querySelectorAll("*")) {
      if (el.closest("svg") && el.localName !== "svg") continue;
      if (!visible(el)) continue;
      const r = el.getBoundingClientRect();
      if (r.width < 6 || r.height < 6 || r.width >= rootW * 0.98) continue;
      const replaced = ["img", "svg", "canvas", "video", "picture", "input", "select", "textarea", "iframe", "button"].includes(el.localName);
      let seen = replaced;
      if (!seen) {
        const cs = getComputedStyle(el);
        const back = bgOf(el.parentElement || el);
        const c = parse(cs.backgroundColor);
        seen = cs.backgroundImage !== "none" || cs.boxShadow !== "none"
          || (c && c[3] > 0.05 && differs(blend(c, back), back))
          || ["Top", "Right", "Bottom", "Left"].some((sd) => parseFloat(cs["border" + sd + "Width"]) > 0
            && !["none", "hidden"].includes(cs["border" + sd + "Style"]) && (parse(cs["border" + sd + "Color"]) || [0, 0, 0, 0])[3] > 0.2);
      }
      if (seen) boxes.push([r.left, r.top + scrollY, r.right, r.bottom + scrollY]);
    }
    return boxes;
  };

  // Empty columns: per section, horizontal bands; a gap in the page's content frame that stays at
  // least min_share of the frame wide over min_height of bands holding content, beside that content.
  if (opts.columns) {
    const C = T.empty_column;
    const body = sections.filter((s) => !isChrome(s));
    const per = body.map((s) => [s, contentBoxes(s)]);
    const all = per.flatMap(([, b]) => b);
    out.columns = [];
    if (all.length) {
      const fx0 = Math.max(0, Math.min(...all.map((b) => b[0])));
      const fx1 = Math.min(W, Math.max(...all.map((b) => b[2])));
      const FW = fx1 - fx0;
      out.frame = [Math.round(fx0), Math.round(fx1)];
      for (const [s, boxes] of per) {
        if (!boxes.length) continue;
        const y0 = Math.min(...boxes.map((b) => b[1]));
        const y1 = Math.max(...boxes.map((b) => b[3]));
        const bands = [];
        for (let y = y0; y < y1; y += C.band) {
          const hits = boxes.filter((b) => b[1] < y + C.band && b[3] > y).map((b) => [Math.max(fx0, b[0]), Math.min(fx1, b[2])]).filter((b) => b[1] > b[0]);
          hits.sort((a, b) => a[0] - b[0]);
          const covered = [];
          for (const h of hits) {
            const last = covered[covered.length - 1];
            if (last && h[0] <= last[1]) last[1] = Math.max(last[1], h[1]); else covered.push([h[0], h[1]]);
          }
          const gaps = [];
          let x = fx0;
          for (const c of covered) { if (c[0] > x) gaps.push([x, c[0]]); x = Math.max(x, c[1]); }
          if (x < fx1) gaps.push([x, fx1]);
          bands.push({ y, content: covered.length > 0, gaps });
        }
        // A run is a gap that stays at least min_share wide band after band; bands without any
        // content (space between blocks) carry a run on, and its height counts from its first to its
        // last band that holds content beside it.
        const minW = C.min_share * FW;
        const overlap = (r, g) => Math.min(r.x1, g[1]) - Math.max(r.x0, g[0]);
        let active = [];
        const finished = [];
        for (const b of bands) {
          const wide = b.gaps.filter((g) => g[1] - g[0] >= minW);
          const next = [];
          const used = new Set();
          for (const r of active) {
            const g = wide.find((x) => overlap(r, x) >= minW);
            if (!g) { finished.push(r); continue; }
            used.add(g);
            next.push({ x0: Math.max(r.x0, g[0]), x1: Math.min(r.x1, g[1]),
              first: r.first === null && b.content ? b.y : r.first,
              last: b.content ? b.y + C.band : r.last, content: r.content + (b.content ? 1 : 0) });
          }
          for (const g of wide) {
            if (!used.has(g)) next.push({ x0: g[0], x1: g[1], first: b.content ? b.y : null, last: b.content ? b.y + C.band : null, content: b.content ? 1 : 0 });
          }
          active = next;
        }
        finished.push(...active);
        const seenRun = new Set();
        for (const r of finished) {
          if (r.first === null || r.last === null) continue;
          const tall = r.last - r.first;
          const key = Math.round(r.x0) + ":" + Math.round(r.first);
          if (seenRun.has(key)) continue;
          seenRun.add(key);
          if (tall < C.min_height || r.content < C.min_content_bands * (tall / C.band)) continue;
          const beside = boxes.filter((b) => b[1] < r.last && b[3] > r.first && (b[2] <= r.x0 + 1 || b[0] >= r.x1 - 1));
          if (!beside.length) continue;
          // Centred content (a narrow column with even margins over the whole run) leaves margins,
          // not a dead column: judged over the run's content as a whole, never one band at a time.
          const level = boxes.filter((b) => b[1] < r.last && b[3] > r.first);
          const e0 = Math.max(fx0, Math.min(...level.map((b) => b[0])));
          const e1 = Math.min(fx1, Math.max(...level.map((b) => b[2])));
          const ml = e0 - fx0;
          const mr = fx1 - e1;
          if (ml > 1 && mr > 1 && Math.abs(ml - mr) <= C.center_tolerance * FW) continue;
          let words = "";
          for (const el of s.querySelectorAll("h2, h3, h4, p, li, dt, blockquote")) {
            const q = el.getBoundingClientRect();
            if (q.top + scrollY < r.last && q.bottom + scrollY > r.first && visible(el)) { words = snip(el.innerText, 60); break; }
          }
          out.columns.push({ section: sectionName(s), x: Math.round(r.x0), width: Math.round(r.x1 - r.x0),
            share: Math.round((r.x1 - r.x0) / FW * 100) / 100, top: Math.round(r.first), height: Math.round(tall),
            side: r.x0 <= fx0 + 1 ? "left" : (r.x1 >= fx1 - 1 ? "right" : "middle"), beside: words });
        }
      }
      out.columns.sort((a, b) => b.share * b.height - a.share * a.height);
      out.columns = out.columns.slice(0, 10);
    }
  }

  // Signifiers: does each interactive element show that it can be used?
  if (opts.cues) {
    const INTERACTIVE = "a[href], button, [role='button'], [role='link'], [role='tab'], [role='menuitem'], summary, input:not([type='hidden']), select, textarea";
    const NATIVE = ["checkbox", "radio", "range", "color", "file"];
    const items = [];
    let navExempt = 0;
    for (const el of document.querySelectorAll(INTERACTIVE)) {
      if (!visible(el)) continue;
      if (el.parentElement && el.parentElement.closest(INTERACTIVE)) continue;
      // Links in the page's header or footer (navigation bars, the logo, footer link lists) are known by their place.
      const home = sectionOf(el);
      if (el.localName === "a" && ((home && isChrome(home)) || el.closest("header nav, footer nav, [role='banner'], [role='contentinfo']"))) { navExempt++; continue; }
      const cs = getComputedStyle(el);
      // A link that fills its container (a whole card) takes the container's fill, border or shadow as its cue.
      const boxes = [[el, cs]];
      const er = el.getBoundingClientRect();
      const par = el.parentElement;
      if (par && par !== document.body) {
        const pr = par.getBoundingClientRect();
        if (pr.width * pr.height > 0 && (er.width * er.height) / (pr.width * pr.height) >= 0.9) boxes.push([par, getComputedStyle(par)]);
      }
      const cues = [];
      for (const [box_el, bcs] of boxes) {
        const back = bgOf(box_el.parentElement || box_el);
        const c = parse(bcs.backgroundColor);
        if (bcs.backgroundImage !== "none" || (c && c[3] > 0.1 && differs(blend(c, back), back))) cues.push("fill");
        if (["Top", "Right", "Bottom", "Left"].some((sd) => {
          const bw = parseFloat(bcs["border" + sd + "Width"]);
          const bc = parse(bcs["border" + sd + "Color"]);
          return bw >= 1 && !["none", "hidden"].includes(bcs["border" + sd + "Style"]) && bc && bc[3] > 0.2 && differs(blend(bc, back), back);
        })) cues.push("border");
        if (bcs.boxShadow && bcs.boxShadow !== "none") cues.push("shadow");
      }
      const textEls = [el, ...el.querySelectorAll("*")].slice(0, 20);
      if (textEls.some((x) => /underline/.test(getComputedStyle(x).textDecorationLine))) cues.push("underline");
      const pseudo = ["::before", "::after"].some((p) => { const v = getComputedStyle(el, p).content; return v && !["none", "normal", '""', "''"].includes(v); });
      const icon = [...el.querySelectorAll("svg, img")].some((g) => { const q = g.getBoundingClientRect(); return q.width > 0 && q.height > 0 && q.width <= T.signifier.max_icon && q.height <= T.signifier.max_icon; });
      if (pseudo || icon || (el.localName === "summary" && cs.display === "list-item" && cs.listStyleType !== "none")) cues.push("icon");
      if ((el.localName === "input" && NATIVE.includes((el.type || "").toLowerCase()) && cs.appearance !== "none")
        || (el.localName === "select" && cs.appearance !== "none")) cues.push("native control");
      items.push({ el, cues: [...new Set(cues)] });
    }
    out.cues = {
      checked: items.length, nav_links: navExempt,
      without: items.filter((i) => !i.cues.length).slice(0, LIMIT).map((i) => ({ sel: sel(i.el), text: nameOf(i.el), tag: i.el.localName,
        box: box(i.el.getBoundingClientRect()), section: (sectionOf(i.el) && sectionName(sectionOf(i.el))) || "" })),
      without_count: items.filter((i) => !i.cues.length).length,
      by_cue: items.reduce((m, i) => { for (const k of i.cues) m[k] = (m[k] || 0) + 1; return m; }, {}),
    };
  }

  // Pictures: img, svg (outermost), canvas, video, CSS background images (url); icons left out.
  const pictures = [];
  {
    const I = T.visuals.icon_max;
    for (const el of document.body.querySelectorAll("*")) {
      let kind = null;
      if (["img", "canvas", "video"].includes(el.localName)) kind = el.localName;
      else if (el.localName === "svg") kind = el.parentElement && el.parentElement.closest("svg") ? null : "svg";
      else if (!el.closest("svg")) {
        const bi = getComputedStyle(el).backgroundImage;
        if (bi && bi.includes("url(")) kind = "background image";
      }
      if (!kind || !visible(el)) continue;
      const r = el.getBoundingClientRect();
      if (r.width < I && r.height < I) continue;
      const name = snip(el.getAttribute("aria-label") || el.getAttribute("alt") || el.getAttribute("title")
        || (el.querySelector && el.querySelector("title") && el.querySelector("title").textContent)
        || (el.closest("figure") && el.closest("figure").querySelector("figcaption") && el.closest("figure").querySelector("figcaption").innerText) || "", 60);
      const decorative = el.getAttribute("aria-hidden") === "true" || el.getAttribute("alt") === "" || el.getAttribute("role") === "presentation";
      pictures.push({ el, kind, r: [r.left, r.top + scrollY, r.right, r.bottom + scrollY], name, decorative });
    }
  }
  if (opts.visuals) {
    const G = T.visuals.grid;
    const areaOf = (rects, clip) => {
      if (!rects.length) return 0;
      const cells = new Set();
      for (const q of rects) {
        const x0 = Math.max(q[0], clip[0]), y0 = Math.max(q[1], clip[1]), x1 = Math.min(q[2], clip[2]), y1 = Math.min(q[3], clip[3]);
        if (x1 <= x0 || y1 <= y0) continue;
        for (let x = Math.floor(x0 / G); x < Math.ceil(x1 / G); x++) for (let y = Math.floor(y0 / G); y < Math.ceil(y1 / G); y++) cells.add(x + "," + y);
      }
      return cells.size * G * G;
    };
    const vs = sections.map((s) => {
      const q = s.getBoundingClientRect();
      const clip = [q.left, q.top + scrollY, q.right, q.bottom + scrollY];
      const mine = pictures.filter((p) => s.contains(p.el));
      const area = Math.max(1, (clip[2] - clip[0]) * (clip[3] - clip[1]));
      return { name: sectionName(s), chrome: isChrome(s), count: mine.length,
        share: Math.round(Math.min(1, areaOf(mine.map((p) => p.r), clip) / area) * 100) / 100,
        items: mine.slice(0, 8).map((p) => ({ kind: p.kind, size: [Math.round(p.r[2] - p.r[0]), Math.round(p.r[3] - p.r[1])],
          top: Math.round(p.r[1]), name: p.name, decorative: p.decorative })) };
    });
    out.visuals = { sections: vs,
      first_screen_share: Math.round(Math.min(1, areaOf(pictures.map((p) => p.r), [0, 0, W, H]) / (W * H)) * 100) / 100,
      none: vs.filter((v) => !v.count && !v.chrome).map((v) => v.name) };
  }

  // Text over an image, a gradient or a translucent layer: candidates for contrast from pixels.
  if (opts.overlays) {
    const cands = [];
    const done = new Set();
    const tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    while (tw.nextNode() && cands.length < 40) {
      const n = tw.currentNode;
      if (!n.nodeValue.trim()) continue;
      const el = n.parentElement;
      if (!el || done.has(el) || el.closest("svg, script, style, noscript, template") || !visible(el)) continue;
      done.add(el);
      let kind = null;
      let translucent = false;
      for (let e = el; e; e = e.parentElement) {
        const cs = getComputedStyle(e);
        if (cs.backdropFilter && cs.backdropFilter !== "none") translucent = true;
        if (cs.backgroundImage && cs.backgroundImage !== "none") { kind = cs.backgroundImage.includes("url(") ? "image" : "gradient"; break; }
        const c = parse(cs.backgroundColor);
        if (c && c[3] >= 1) break;
        if (c && c[3] > 0) translucent = true;
      }
      const rg = document.createRange();
      rg.selectNodeContents(el);
      const lines = [...rg.getClientRects()].filter((q) => q.width > 2 && q.height > 2);
      if (!lines.length) continue;
      if (!kind) {
        const tr = el.getBoundingClientRect();
        const under = pictures.find((p) => !p.el.contains(el) && !el.contains(p.el)
          && Math.max(0, Math.min(p.r[2], tr.right) - Math.max(p.r[0], tr.left)) * Math.max(0, Math.min(p.r[3], tr.bottom + scrollY) - Math.max(p.r[1], tr.top + scrollY))
            >= 0.25 * tr.width * tr.height);
        if (under) {
          const cx = tr.left + tr.width / 2, cy = tr.top + tr.height / 2;
          const top = cy >= 0 && cy < H ? document.elementFromPoint(cx, cy) : null;
          if (!top || el.contains(top) || top.contains(el) || !under.el.contains(top)) kind = "picture";
        }
      }
      if (!kind && !translucent) continue;
      const cs = getComputedStyle(el);
      const size = parseFloat(cs.fontSize);
      const weight = parseInt(cs.fontWeight, 10) || 400;
      const large = size >= 24 || (size >= 18.66 && weight >= 700);
      const color = parse(cs.color) || [0, 0, 0, 1];
      const solid = bgOf(el);
      const id = cands.length;
      el.setAttribute("data-pc-cand", String(id));
      cands.push({ id, sel: sel(el), text: snip(el.innerText, 60), size: Math.round(size), weight, large,
        needs: large ? T.text_over_image.large : T.text_over_image.normal, color,
        kind: kind || "translucent layer", declared: Math.round(ratio(blend(color, solid), solid) * 100) / 100,
        // The glyph band of each line: 0.6 em around the line's middle (line boxes also hold the space above and below).
        lines: lines.slice(0, 6).map((q) => { const band = Math.min(q.height, Math.max(4, 0.6 * size)); const mid = q.top + q.height / 2;
          return [Math.max(0, Math.floor(q.left)), Math.floor(mid - band / 2 + scrollY), Math.ceil(q.width), Math.ceil(band)]; })
          .filter((q) => q[0] < W && q[2] > 0).map((q) => [q[0], q[1], Math.min(q[2], W - q[0]), q[3]]),
        section: (sectionOf(el) && sectionName(sectionOf(el))) || "" });
    }
    out.overlays = cands;
  }

  // Running text under the dark-text minimum, light on a dark background.
  if (opts.small_dark) {
    const D = T.dark_small_text;
    const hits = [];
    const done = new Set();
    for (const el of document.querySelectorAll("p, li, dd, dt, td, th, blockquote, figcaption, span, div, a, label, small")) {
      if (hits.length >= LIMIT || done.has(el) || el.closest("svg")) continue;
      const own = [...el.childNodes].filter((n) => n.nodeType === 3).map((n) => n.nodeValue).join(" ");
      if (own.trim().split(/\s+/).filter(Boolean).length < 3) continue;
      if (!visible(el)) continue;
      const words = snip(el.innerText, 2000).split(" ").filter(Boolean).length;
      if (words < D.min_words) continue;
      const cs = getComputedStyle(el);
      const size = parseFloat(cs.fontSize);
      if (size >= D.max_px) continue;
      const bg = bgOf(el);
      const fg = blend(parse(cs.color) || [0, 0, 0, 1], bg);
      if (lum(bg) > D.max_background_luminance || lum(fg) <= lum(bg)) continue;
      for (const x of el.querySelectorAll("*")) done.add(x);
      hits.push({ sel: sel(el), text: snip(el.innerText, 60), size: Math.round(size * 10) / 10, words,
        color: rgb(fg), background: rgb(bg), section: (sectionOf(el) && sectionName(sectionOf(el))) || "" });
    }
    out.small_dark = hits;
  }
  return out;
})(__OPTS__)
