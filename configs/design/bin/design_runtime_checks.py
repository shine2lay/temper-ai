#!/usr/bin/env python3
"""Runtime checks on a built homepage: what using it is like, measured in a real browser.

Static checks (axe, computed styles) miss how a page behaves when someone uses it.
This script drives the page the way people do, with no model and fixed rules:

  focus    Tab through the page; every stop must show a visible change (WCAG 2.4.7),
           an outline indicator needs 3:1 against what it is drawn on (1.4.11), and
           the focused element must not be hidden off screen or under other content
           (2.4.11; partly covered is noted, 2.4.12).
  order    no keyboard trap (2.1.2), no positive tabindex (2.4.3), every visible
           control reachable by Tab (2.1.1).
  names    links, buttons and fields have an accessible name with words in it (4.1.2),
           images have alt (1.1.1), fields are not named by placeholder only (3.3.2),
           an aria-label contains the visible label (2.5.3).
  reflow   at 320 x 640 CSS px nothing scrolls sideways or is cut off (1.4.10).
  zoom     400 % zoom of a 1280 x 800 window is a 320 x 200 CSS px viewport: fixed or
           sticky parts may not cover more than 40 % of it, nothing scrolls sideways,
           text is not clipped, and the viewport meta allows zoom (1.4.4, 1.4.10).
  spacing  WCAG 1.4.12 override (line height 1.5, letter 0.12 em, word 0.16 em,
           paragraph 2 em) at 1440 and 390: no text newly clipped or spilling out of
           its box, nothing newly scrolling sideways.
  motion   with prefers-reduced-motion: reduce, no animation that moves things or
           loops is still declared (page rule; WCAG 2.3.3). Short fades are allowed.
  hover    every link and button changes visibly under the pointer (a usability and
           craft check, not a WCAG criterion; severity 2).
  kept_text  from the second round on, against the previous round's raw.json: words a
           screen reader reached (screen-reader-only text, alt, aria-label, visible text)
           may not vanish for it while the page still shows the same block (1.3.1, 4.1.2;
           severity 3). Removed or rewritten visible content is the content review's call.

The browser part only measures (raw.json); judge() applies the rules, so recorded
raw results can be re-judged and tested without a browser.

    design_runtime_checks.py --site DIR [--page index.html] --out DIR
                             [--browser URL] [--serve-host HOST]
    design_runtime_checks.py --raw raw.json --out DIR      # judge a recorded result
    ... [--prev PREVIOUS_ROUND/raw.json]                   # also compare kept text

Writes OUT/runtime.json (summary + findings), OUT/RUNTIME.md, OUT/page-text.md
(visible text in reading order, for the content review) and OUT/raw.json.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import html_to_penpot as h2p  # noqa: E402

BROWSER = os.environ.get("DESIGN_BROWSER", "http://playwright-mcp:8931/mcp")
SERVE_HOST = os.environ.get("DESIGN_SERVE_HOST") or None
CHECKS = ("focus", "order", "names", "reflow", "zoom", "spacing", "motion", "hover")  # one page each
# Needs the previous round's recording; listed in a result's checks only when there was one to compare.
COMPARE_CHECKS = ("kept_text",)
A11Y_VIEWPORTS = ((1440, 900), (390, 844))
MAX_TABS = 150
MAX_HOVER = 60
STICKY_SHARE = 0.40          # of the 400 % zoom viewport height
ZOOM_VIEWPORT = (320, 200)   # 1280 x 800 window at 400 %
REFLOW_VIEWPORT = (320, 640)
SPACING_WIDTHS = (1440, 390)
MOTION_MIN_SECONDS = 0.01
GROUP_LIMIT = 8
SPACING_CSS = ("*{line-height:1.5!important;letter-spacing:0.12em!important;word-spacing:0.16em!important}"
               "p{margin-bottom:2em!important}")
FREEZE_CSS = ("*,*::before,*::after{transition:none!important;animation:none!important;"
              "caret-color:transparent!important;scroll-behavior:auto!important}")
MOVING = re.compile(r"^(transform|translate|rotate|scale|top|left|right|bottom|inset(-.*)?|margin(-.*)?|"
                    r"background-position(-.*)?|offset(-.*)?|width|height|perspective(-.*)?)$")

# In-page helpers, evaluated after every navigation (window.__rtc).
HELPERS = r"""(() => {
  const R = {};
  R.FOCUSABLE = 'a[href], area[href], button:not([disabled]), input:not([disabled]):not([type=hidden]), select:not([disabled]), textarea:not([disabled]), summary, iframe, [tabindex], [contenteditable=""], [contenteditable="true"]';
  R.INTERACTIVE = R.FOCUSABLE + ', [role=button], [role=link], [role=checkbox], [role=tab], [role=menuitem], [role=switch]';
  R.HOVERABLE = 'a[href], button:not([disabled]), [role=button], summary, input[type=submit], input[type=button]';
  R.PROPS = ['outlineStyle', 'outlineWidth', 'outlineColor', 'outlineOffset', 'boxShadow', 'borderTopColor', 'borderBottomColor',
             'borderLeftColor', 'borderRightColor', 'borderTopWidth', 'borderBottomWidth', 'borderLeftWidth', 'borderRightWidth',
             'backgroundColor', 'backgroundImage', 'color', 'textDecorationLine', 'textDecorationColor', 'textDecorationThickness',
             'textUnderlineOffset', 'transform', 'translate', 'scale', 'rotate', 'opacity', 'filter', 'fill', 'stroke'];
  R.PSEUDO = ['content', 'opacity', 'transform', 'backgroundColor', 'backgroundImage', 'borderTopColor', 'borderBottomColor',
              'borderBottomWidth', 'boxShadow', 'outlineStyle', 'outlineWidth', 'width', 'height', 'color'];
  R.KID = ['color', 'backgroundColor', 'backgroundImage', 'transform', 'translate', 'textDecorationLine', 'boxShadow', 'outlineStyle',
           'outlineWidth', 'borderBottomColor', 'borderBottomWidth', 'opacity', 'fill', 'stroke'];
  R.PARENT = ['outlineStyle', 'outlineWidth', 'boxShadow', 'backgroundColor', 'borderTopColor', 'borderBottomColor'];
  R.vis = (el) => {
    if (!el || !el.getBoundingClientRect) return false;
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) return false;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.visibility === 'collapse') return false;
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
      const c = getComputedStyle(e);
      if (c.display === 'none' || parseFloat(c.opacity) === 0) return false;
    }
    return true;
  };
  R.section = (el) => {
    const s = el.closest('[data-section]');
    if (s) return s.dataset.section;
    const l = el.closest('header, footer, nav, main, aside, section');
    return l ? l.tagName.toLowerCase() : 'page';
  };
  R.clean = (s) => String(s || '').replace(/\s+/g, ' ').trim();
  R.walk = (n, root) => {
    if (n.nodeType === 3) return n.textContent;
    if (n.nodeType !== 1) return '';
    if (n.getAttribute('aria-hidden') === 'true') return '';
    const cs = getComputedStyle(n);
    if (cs.display === 'none' || cs.visibility === 'hidden') return '';
    const tag = n.tagName.toLowerCase();
    if (n !== root) {
      const al = R.clean(n.getAttribute('aria-label'));
      if (al) return ' ' + al + ' ';
    }
    if (tag === 'img') return ' ' + (n.getAttribute('alt') || '') + ' ';
    if (tag === 'svg') { const t = n.querySelector('title'); return t ? ' ' + t.textContent + ' ' : ''; }
    let s = '';
    for (const c of n.childNodes) s += R.walk(c, root);
    return cs.display === 'inline' ? s : ' ' + s + ' ';
  };
  R.visibleText = (el) => R.clean(R.walk(el, el));
  R.name = (el) => {
    const by = el.getAttribute('aria-labelledby');
    if (by) {
      const t = R.clean(by.split(/\s+/).map((id) => document.getElementById(id)).filter(Boolean).map((e) => e.textContent).join(' '));
      if (t) return {name: t, from: 'aria-labelledby'};
    }
    const al = R.clean(el.getAttribute('aria-label'));
    if (al) return {name: al, from: 'aria-label'};
    const tag = el.tagName.toLowerCase();
    if (tag === 'img' || (tag === 'input' && el.type === 'image')) return {name: R.clean(el.getAttribute('alt')), from: 'alt'};
    if (el.labels && el.labels.length) {
      const t = R.clean([...el.labels].map((l) => l.textContent).join(' '));
      if (t) return {name: t, from: 'label'};
    }
    if (tag === 'input' || tag === 'textarea' || tag === 'select') {
      if (['submit', 'button', 'reset'].includes(el.type)) return {name: R.clean(el.value), from: 'value'};
      const t = R.clean(el.getAttribute('title'));
      if (t) return {name: t, from: 'title'};
      return {name: R.clean(el.getAttribute('placeholder')), from: 'placeholder'};
    }
    if (tag === 'svg') { const t = el.querySelector('title'); return {name: R.clean(t ? t.textContent : ''), from: 'svg-title'}; }
    const t = R.visibleText(el);
    if (t) return {name: t, from: 'content'};
    return {name: R.clean(el.getAttribute('title')), from: 'title'};
  };
  R.desc = (el) => {
    const n = R.name(el).name || R.visibleText(el);
    return {tag: el.tagName.toLowerCase(), id: el.id || null,
            cls: (el.getAttribute('class') || '').split(/\s+/).filter(Boolean).slice(0, 2).join('.') || null,
            label: n.slice(0, 80), section: R.section(el), data_name: (el.dataset && el.dataset.name) || null};
  };
  R.rect = (el) => { const r = el.getBoundingClientRect(); return {x: Math.round(r.left), y: Math.round(r.top), w: Math.round(r.width), h: Math.round(r.height)}; };
  R.pick = (cs, keys) => Object.fromEntries(keys.map((k) => [k, cs[k]]));
  R.geo = (el) => {
    const r = el.getBoundingClientRect();
    const x = r.left + window.scrollX, y = r.top + window.scrollY;
    const dw = document.documentElement.scrollWidth, dh = document.documentElement.scrollHeight;
    return {w: Math.round(r.width), h: Math.round(r.height), off: x + r.width <= 0 || y + r.height <= 0 || x >= dw || y >= dh || r.width <= 1 || r.height <= 1};
  };
  R.snap = (el) => ({
    geo: R.geo(el),
    self: R.pick(getComputedStyle(el), R.PROPS),
    before: R.pick(getComputedStyle(el, '::before'), R.PSEUDO),
    after: R.pick(getComputedStyle(el, '::after'), R.PSEUDO),
    kids: [...el.children].slice(0, 4).map((c) => R.pick(getComputedStyle(c), R.KID)),
    parent: el.parentElement ? R.pick(getComputedStyle(el.parentElement), R.PARENT) : {}});
  R.alpha = (c) => { const m = String(c).match(/rgba?\(([^)]+)\)/); if (!m) return String(c) === 'transparent' ? 0 : 1; const p = m[1].split(/[\s,\/]+/).filter(Boolean); return p.length > 3 ? parseFloat(p[3]) : 1; };
  R.rgb = (c) => { const m = String(c).match(/rgba?\(([^)]+)\)/); if (!m) return null; return m[1].split(/[\s,\/]+/).filter(Boolean).slice(0, 3).map(parseFloat); };
  R.px = (v) => parseFloat(v) || 0;
  R.shadowVisible = (v) => {
    if (!v || v === 'none') return false;
    const lengths = (String(v).match(/-?\d*\.?\d+px/g) || []).map(parseFloat);
    const colors = String(v).match(/rgba?\([^)]+\)/g) || ['rgb(0,0,0)'];
    return lengths.some((x) => x !== 0) && colors.some((c) => R.alpha(c) > 0.05);
  };
  R.outlineVisible = (s) => s.outlineStyle !== 'none' && R.px(s.outlineWidth) > 0 && (s.outlineStyle === 'auto' || R.alpha(s.outlineColor) > 0.05);
  R.rendered = (p) => p.content && p.content !== 'none' && p.content !== 'normal';
  R.visibleDiff = (a, b) => {
    const out = [];
    if (a.geo && b.geo) {
      if (a.geo.off && !b.geo.off) out.push('revealed on focus');
      else if (Math.abs(a.geo.w - b.geo.w) > 2 || Math.abs(a.geo.h - b.geo.h) > 2) out.push('size ' + a.geo.w + 'x' + a.geo.h + ' -> ' + b.geo.w + 'x' + b.geo.h);
    }
    const sa = a.self, sb = b.self;
    if (R.outlineVisible(sa) !== R.outlineVisible(sb) || (R.outlineVisible(sb) && (sa.outlineColor !== sb.outlineColor || sa.outlineWidth !== sb.outlineWidth || sa.outlineOffset !== sb.outlineOffset)))
      out.push('outline ' + sa.outlineStyle + ' ' + sa.outlineWidth + ' -> ' + sb.outlineStyle + ' ' + sb.outlineWidth + ' ' + sb.outlineColor);
    if (sa.boxShadow !== sb.boxShadow && (R.shadowVisible(sa.boxShadow) || R.shadowVisible(sb.boxShadow))) out.push('box-shadow -> ' + sb.boxShadow);
    for (const side of ['Top', 'Bottom', 'Left', 'Right']) {
      const w = 'border' + side + 'Width', c = 'border' + side + 'Color';
      if (sa[w] !== sb[w] && Math.abs(R.px(sa[w]) - R.px(sb[w])) > 0) out.push(w + ' ' + sa[w] + ' -> ' + sb[w]);
      else if (sa[c] !== sb[c] && R.px(sb[w]) > 0) out.push(c + ' -> ' + sb[c]);
    }
    if (sa.backgroundColor !== sb.backgroundColor && (R.alpha(sa.backgroundColor) > 0.05 || R.alpha(sb.backgroundColor) > 0.05)) out.push('background ' + sa.backgroundColor + ' -> ' + sb.backgroundColor);
    if (sa.backgroundImage !== sb.backgroundImage) out.push('background-image changed');
    if (sa.color !== sb.color) out.push('color ' + sa.color + ' -> ' + sb.color);
    if (sa.textDecorationLine !== sb.textDecorationLine) out.push('text-decoration ' + sa.textDecorationLine + ' -> ' + sb.textDecorationLine);
    else if (sb.textDecorationLine !== 'none' && (sa.textDecorationColor !== sb.textDecorationColor || sa.textDecorationThickness !== sb.textDecorationThickness || sa.textUnderlineOffset !== sb.textUnderlineOffset)) out.push('underline style changed');
    for (const k of ['transform', 'translate', 'scale', 'rotate', 'filter']) if (sa[k] !== sb[k]) out.push(k + ' -> ' + sb[k]);
    if (Math.abs(parseFloat(sa.opacity) - parseFloat(sb.opacity)) >= 0.1) out.push('opacity ' + sa.opacity + ' -> ' + sb.opacity);
    if (sa.fill !== sb.fill || sa.stroke !== sb.stroke) out.push('svg fill/stroke changed');
    for (const p of ['before', 'after']) {
      const pa = a[p], pb = b[p];
      if (R.rendered(pa) !== R.rendered(pb)) { out.push('::' + p + ' appears/disappears'); continue; }
      if (!R.rendered(pb)) continue;
      for (const k of R.PSEUDO) if (k !== 'content' && pa[k] !== pb[k]) { out.push('::' + p + ' ' + k + ' -> ' + pb[k]); break; }
    }
    a.kids.forEach((k, i) => {
      const kb = b.kids[i];
      if (!kb) return;
      for (const key of R.KID) if (k[key] !== kb[key]) {
        if ((key === 'outlineWidth' || key === 'outlineStyle') && !(kb.outlineStyle !== 'none' && R.px(kb.outlineWidth) > 0)) continue;
        if (key === 'boxShadow' && !R.shadowVisible(k[key]) && !R.shadowVisible(kb[key])) continue;
        out.push('child ' + i + ' ' + key + ' -> ' + kb[key]); break;
      }
    });
    const pa = a.parent, pb = b.parent;
    if (pa && pb) {
      if (R.outlineVisible(pa) !== R.outlineVisible(pb)) out.push('parent outline');
      else if (pa.boxShadow !== pb.boxShadow && (R.shadowVisible(pa.boxShadow) || R.shadowVisible(pb.boxShadow))) out.push('parent box-shadow');
    }
    return out;
  };
  R.lum = (rgb) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); }; return 0.2126 * f(rgb[0]) + 0.7152 * f(rgb[1]) + 0.0722 * f(rgb[2]); };
  R.ratio = (a, b) => { const la = R.lum(a), lb = R.lum(b); return (Math.max(la, lb) + 0.05) / (Math.min(la, lb) + 0.05); };
  R.bgBehind = (el) => {
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.backgroundImage !== 'none') return null;
      if (R.alpha(cs.backgroundColor) >= 0.99) return R.rgb(cs.backgroundColor);
    }
    return [255, 255, 255];
  };
  R.indicator = (el, s) => {
    if (s.outlineStyle === 'auto') return {kind: 'browser-default', ratio: null};
    if (!R.outlineVisible(s)) return {kind: 'other', ratio: null};
    const col = R.rgb(s.outlineColor);
    const bg = R.px(s.outlineOffset) >= 0 ? R.bgBehind(el.parentElement || el) : R.bgBehind(el);
    if (!col || !bg || R.alpha(s.outlineColor) < 0.99) return {kind: 'outline', ratio: null};
    return {kind: 'outline', color: s.outlineColor, against: 'rgb(' + bg.join(', ') + ')', ratio: Math.round(R.ratio(col, bg) * 100) / 100};
  };
  R.clipBoxes = (el) => {
    const out = [];
    for (let e = el; e && e !== document.body && e !== document.documentElement; e = e.parentElement) {
      const cs = getComputedStyle(e);
      const ox = cs.overflowX, oy = cs.overflowY;
      if (ox !== 'visible' || oy !== 'visible') {
        const r = e.getBoundingClientRect();
        const bl = R.px(cs.borderLeftWidth), bt = R.px(cs.borderTopWidth);
        out.push({el: e, x: ox !== 'visible', y: oy !== 'visible', scroll: ['auto', 'scroll'].includes(ox) || ['auto', 'scroll'].includes(oy),
                  l: r.left + bl, t: r.top + bt, r: r.left + bl + e.clientWidth, b: r.top + bt + e.clientHeight});
      }
    }
    return out;
  };
  R.textRect = (el) => {
    const range = document.createRange();
    let t = null;
    for (const n of el.childNodes) {
      if (n.nodeType !== 3 || !n.textContent.trim()) continue;
      range.selectNodeContents(n);
      for (const b of range.getClientRects()) {
        if (b.width <= 0 || b.height <= 0) continue;
        t = t ? {l: Math.min(t.l, b.left), t: Math.min(t.t, b.top), r: Math.max(t.r, b.right), b: Math.max(t.b, b.bottom)} : {l: b.left, t: b.top, r: b.right, b: b.bottom};
      }
    }
    return t;
  };
  // Text hidden on purpose: screen-reader-only boxes (1 px with overflow hidden, clip: rect(0 0 0 0),
  // clip-path: inset(50%)) or parked off-screen. It is meant to be clipped, so it is never "cut off".
  R.hiddenOnPurpose = (el) => {
    for (let e = el; e && e.nodeType === 1 && e !== document.documentElement; e = e.parentElement) {
      const cs = getComputedStyle(e);
      const r = e.getBoundingClientRect();
      const placed = cs.position === 'absolute' || cs.position === 'fixed';
      const clips = cs.overflowX !== 'visible' || cs.overflowY !== 'visible' || (cs.clip && cs.clip !== 'auto') || (cs.clipPath && cs.clipPath !== 'none');
      if (r.width <= 2 && r.height <= 2 && clips) return true;
      if (/inset\(\s*50%/.test(cs.clipPath || '')) return true;
      if (placed && /^rect\(\s*0(px)?[\s,]+0(px)?[\s,]+0(px)?[\s,]+0(px)?\s*\)$/.test(cs.clip || '')) return true;
      if (placed && (r.right + window.scrollX <= 0 || r.bottom + window.scrollY <= 0)) return true;
    }
    return false;
  };
  R.lineRects = (el) => {
    const out = [], range = document.createRange();
    for (const n of el.childNodes) {
      if (n.nodeType !== 3 || !n.textContent.trim()) continue;
      range.selectNodeContents(n);
      for (const b of range.getClientRects()) if (b.width > 0 && b.height > 0) out.push({l: b.left, t: b.top, r: b.right, b: b.bottom});
    }
    return out;
  };
  R.meet = (a, b) => Math.min(a.r, b.r) - Math.max(a.l, b.l) > 2 && Math.min(a.b, b.b) - Math.max(a.t, b.t) > 2;
  R.SOLID = ['img', 'svg', 'video', 'canvas', 'iframe', 'input', 'select', 'textarea', 'button', 'picture', 'object', 'embed'];
  // Text running out of its box loses nothing (WCAG 1.4.12, failure F104 is clipped or overlapped text)
  // unless the part outside lands on other text or content, or on a background it cannot be read against.
  R.spillHarm = (el, box) => {
    const br = box.getBoundingClientRect();
    const parts = [];
    for (const b of R.lineRects(el)) {
      if (b.r > br.right + 2) parts.push({l: Math.max(b.l, br.right), t: b.t, r: b.r, b: b.b});
      if (b.b > br.bottom + 2) parts.push({l: b.l, t: Math.max(b.t, br.bottom), r: b.r, b: b.b});
    }
    if (!parts.length) return null;
    for (const o of document.querySelectorAll('body *')) {
      if (o === el || el.contains(o) || o.contains(el)) continue;
      const tag = o.tagName.toLowerCase();
      if (['script', 'style', 'noscript', 'template'].includes(tag) || !R.vis(o)) continue;
      const cs = getComputedStyle(o);
      const solid = R.SOLID.includes(tag) || R.alpha(cs.backgroundColor) > 0.05 || cs.backgroundImage !== 'none';
      let boxes;
      if (solid) { const r = o.getBoundingClientRect(); boxes = [{l: r.left, t: r.top, r: r.right, b: r.bottom}]; }
      else boxes = R.lineRects(o);
      for (const p of parts) for (const q of boxes) if (R.meet(p, q)) return {kind: 'overlap', with: R.desc(o)};
    }
    const cs = getComputedStyle(el);
    const color = R.rgb(cs.color);
    if (!color || R.alpha(cs.color) < 0.99) return null;
    const inside = R.bgBehind(el);
    const size = R.px(cs.fontSize), weight = parseInt(cs.fontWeight, 10) || 400;
    const need = size >= 24 || (size >= 18.66 && weight >= 700) ? 3 : 4.5;
    for (const p of parts) {
      const cx = (p.l + p.r) / 2, cy = (p.t + p.b) / 2;
      let host = box.parentElement;
      while (host && host !== document.documentElement) {
        const r = host.getBoundingClientRect();
        if (cx >= r.left && cx <= r.right && cy >= r.top && cy <= r.bottom) break;
        host = host.parentElement;
      }
      const outside = R.bgBehind(host || document.body);
      if (!outside) continue;  // an image or gradient behind: cannot be measured here
      const ratio = R.ratio(color, outside);
      if (ratio < need && (!inside || ratio < R.ratio(color, inside) - 0.01))
        return {kind: 'contrast', ratio: Math.round(ratio * 100) / 100, against: 'rgb(' + outside.join(', ') + ')'};
    }
    return null;
  };
  R.textEls = () => [...document.querySelectorAll('body *')].filter((el) => {
    if (['script', 'style', 'noscript', 'template', 'title'].includes(el.tagName.toLowerCase())) return false;
    if (!R.vis(el)) return false;
    for (const n of el.childNodes) if (n.nodeType === 3 && n.textContent.trim()) return true;
    return false;
  });
  R.textState = () => R.textEls().map((el, i) => {
    const tr = R.textRect(el);
    const res = {i, ...R.desc(el), text: R.clean(el.textContent).slice(0, 90), clipped: null, spill: null};
    if (!tr) return res;
    if (tr.r + window.scrollX <= 0 || tr.b + window.scrollY <= 0 || R.hiddenOnPurpose(el)) return {...res, hidden: true};
    for (const c of R.clipBoxes(el)) {
      if (c.scroll) continue;
      const over = Math.max(c.x ? c.l - tr.l : 0, c.x ? tr.r - c.r : 0, c.y ? c.t - tr.t : 0, c.y ? tr.b - c.b : 0);
      if (over > 1.5) { res.clipped = {by: R.desc(c.el), px: Math.round(over)}; break; }
    }
    for (let e = el; e && e !== document.body && e.parentElement; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.overflowX !== 'visible' || cs.overflowY !== 'visible') break;
      if (cs.position === 'absolute' || cs.position === 'fixed') break;
      const r = e.getBoundingClientRect();
      const over = Math.max(tr.b - r.bottom, tr.r - r.right);
      if (over > 2) { res.spill = {box: R.desc(e), px: Math.round(over), harm: R.spillHarm(el, e)}; break; }
    }
    return res;
  });
  R.sideways = () => {
    const vw = document.documentElement.clientWidth;
    const html = getComputedStyle(document.documentElement), body = getComputedStyle(document.body);
    const hidden = ['hidden', 'clip'].includes(html.overflowX) || ['hidden', 'clip'].includes(body.overflowX);
    const offenders = [];
    for (const el of document.querySelectorAll('body *')) {
      if (!R.vis(el)) continue;
      const r = el.getBoundingClientRect();
      // Only overflow to the right makes a page scroll sideways; parking a skip link at
      // left: -9999px is a normal hiding technique.
      if (r.right <= vw + 1) continue;
      let clipped = false;
      for (const c of R.clipBoxes(el)) if (c.x) { clipped = true; break; }
      if (clipped) continue;
      if (offenders.some((o) => o.el.contains(el))) continue;
      offenders.push({el, d: {...R.desc(el), right: Math.round(r.right), left: Math.round(r.left), width: Math.round(r.width)}});
      if (offenders.length >= 12) break;
    }
    return {viewport: vw, scroll_width: document.documentElement.scrollWidth, body_scroll_width: document.body.scrollWidth,
            page_overflow_hidden: hidden, offenders: offenders.map((o) => o.d)};
  };
  R.covering = () => {
    const vh = window.innerHeight, vw = window.innerWidth;
    const rows = new Array(vh).fill(false);
    const items = [];
    for (const el of document.querySelectorAll('body *')) {
      const cs = getComputedStyle(el);
      if (cs.position !== 'fixed' && cs.position !== 'sticky') continue;
      if (!R.vis(el)) continue;
      const r = el.getBoundingClientRect();
      const top = Math.max(0, Math.floor(r.top)), bottom = Math.min(vh, Math.ceil(r.bottom));
      if (bottom <= top || r.right <= 0 || r.left >= vw) continue;
      if (r.width < vw * 0.5) continue;  // a small floating button does not block reading
      for (let y = top; y < bottom; y++) rows[y] = true;
      items.push({...R.desc(el), position: cs.position, top: Math.round(r.top), height: Math.round(r.height)});
    }
    return {covered_rows: rows.filter(Boolean).length, viewport_height: vh, items};
  };
  R.motion = () => {
    const kf = {};
    const visit = (rules) => {
      for (const r of rules) {
        if (r.type === CSSRule.KEYFRAMES_RULE) {
          const props = new Set();
          for (const k of r.cssRules) for (let j = 0; j < k.style.length; j++) props.add(k.style[j]);
          kf[r.name] = [...props];
        } else if (r.cssRules) {
          try { visit(r.cssRules); } catch (e) { /* cross-origin */ }
        }
      }
    };
    for (const s of document.styleSheets) { try { visit(s.cssRules); } catch (e) { /* cross-origin */ } }
    const secs = (v) => { v = v.trim(); return v.endsWith('ms') ? parseFloat(v) / 1000 : parseFloat(v); };
    const declared = [];
    for (const el of document.querySelectorAll('html, body, body *')) {
      for (const pseudo of [null, '::before', '::after']) {
        const c = getComputedStyle(el, pseudo);
        if (!c.animationName || c.animationName === 'none') continue;
        if (pseudo && !R.rendered(c)) continue;
        const names = c.animationName.split(',').map((s) => s.trim());
        const durs = c.animationDuration.split(',').map(secs);
        const iters = c.animationIterationCount.split(',').map((s) => s.trim());
        const states = c.animationPlayState.split(',').map((s) => s.trim());
        names.forEach((n, i) => {
          if (n === 'none') return;
          declared.push({...R.desc(el), pseudo, name: n, duration: durs[i % durs.length], iterations: iters[i % iters.length],
                         play_state: states[i % states.length], props: kf[n] || []});
        });
      }
    }
    const running = document.getAnimations().filter((a) => a.playState === 'running').length;
    return {declared: declared.slice(0, 200), declared_count: declared.length, running};
  };
  R.pageText = () => {
    const BLOCK = /^(h[1-6]|p|li|dt|dd|figcaption|blockquote|td|th|label|legend|summary|caption|button|a|small|address|pre)$/;
    const lines = [];
    let current = null;
    const tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    let node;
    while ((node = tw.nextNode())) {
      if (node.nodeType === 1) {
        if (node.tagName.toLowerCase() === 'img' && R.vis(node) && node.getAttribute('alt')) lines.push({section: R.section(node), tag: 'img alt', text: R.clean(node.getAttribute('alt'))});
        // A line break separates words the way a space does (innerText); without it "4.<br>Oak" read as "4.Oak"
        // and the content reviewer reported missing spaces that no reader sees (Morrow pilot, 2026-10-04).
        if (node.tagName.toLowerCase() === 'br' && current && current.el && current.el.contains(node)) current.text += ' ';
        continue;
      }
      const t = node.textContent;
      if (!t.trim() || !node.parentElement || !R.vis(node.parentElement)) continue;
      if (node.parentElement.closest('[aria-hidden="true"], script, style, svg')) continue;
      let blk = node.parentElement;
      while (blk && blk !== document.body) {
        const tag = blk.tagName.toLowerCase();
        if (BLOCK.test(tag) || getComputedStyle(blk).display !== 'inline') break;
        blk = blk.parentElement;
      }
      if (current && current.el === blk) { current.text += t; continue; }
      current = {el: blk, section: R.section(node.parentElement), tag: blk ? blk.tagName.toLowerCase() : 'body', text: t};
      lines.push(current);
    }
    return lines.map((l) => ({section: l.section, tag: l.tag, text: R.clean(l.text)})).filter((l) => l.text);
  };
  // Kept text: every piece of text a screen reader can reach and every piece a sighted reader sees, in page
  // order and grouped into blocks, so a revision can be compared with the round before it (Morrow pilot r01
  // -> r02 deleted its board's screen-reader labels and hid others to quiet two false alarms).
  R.INLINE_TAGS = /^(span|a|b|i|em|strong|small|abbr|code|kbd|mark|q|s|sub|sup|u|time|var|bdi|bdo|cite|dfn|data|font|samp|del|ins|img|svg|picture|wbr|br)$/;
  // ARIA 1.2 does not allow naming these roles, so an aria-label on them is not announced.
  R.GENERIC_TAGS = /^(div|span|p|b|i|em|strong|small|code|del|ins|sub|sup|s|u|font|data|pre|q|var|kbd|samp|mark|abbr|time|cite|dfn|bdi|bdo)$/;
  R.NAME_FROM = ['aria-labelledby', 'aria-label', 'alt', 'svg-title', 'title'];
  R.shown = (el) => {
    if (el.checkVisibility) return el.checkVisibility({visibilityProperty: true});
    if (getComputedStyle(el).visibility !== 'visible') return false;
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) if (getComputedStyle(e).display === 'none') return false;
    return true;
  };
  R.atHidden = (el) => !!el.closest('[aria-hidden="true"], [inert]');
  // An ancestor whose own name stands in for its content: a graphic, or a link/button-like control named by aria-label.
  R.replacedBy = (el, self) => {
    for (let e = self ? el : el.parentElement; e && e !== document.body; e = e.parentElement) {
      const role = (e.getAttribute('role') || '').trim().toLowerCase();
      const tag = e.tagName.toLowerCase();
      if (role === 'img' || tag === 'svg' || tag === 'math') return e;
      const named = R.clean(e.getAttribute('aria-label')) || e.hasAttribute('aria-labelledby');
      if (named && (e.matches('a[href], button, summary') || /^(button|link|tab|menuitem|switch|checkbox|radio|option)$/.test(role))) return e;
    }
    return null;
  };
  R.a11yItems = () => {
    const items = [], blocks = new Map();
    const blockOf = (el) => {
      let b = el;
      while (b && b !== document.body && R.INLINE_TAGS.test(b.tagName.toLowerCase())) b = b.parentElement;
      b = b || document.body;
      if (!blocks.has(b)) blocks.set(b, blocks.size);
      return blocks.get(b);
    };
    const tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    let node;
    while ((node = tw.nextNode()) && items.length < 4000) {
      const el = node.parentElement;
      const t = R.clean(node.textContent);
      if (!t || !el || el.closest('script, style, noscript, template, svg, math, title')) continue;
      if (!R.shown(el)) continue;
      const at = !R.atHidden(el) && !R.replacedBy(el, true);
      const vis = R.vis(el) && !R.hiddenOnPurpose(el);
      if (at || vis) items.push({k: 't', t: t.slice(0, 300), at, vis, b: blockOf(el), sec: R.section(el)});
    }
    for (const el of document.querySelectorAll('img, svg, [role=img], input[type=image], area, [aria-label], [aria-labelledby]')) {
      if (items.length >= 5000) break;
      const tag = el.tagName.toLowerCase(), role = (el.getAttribute('role') || '').trim().toLowerCase();
      if (tag !== 'svg' && el.closest('svg')) continue;
      if (!role && R.GENERIC_TAGS.test(tag)) continue;
      const nm = R.name(el);
      const t = R.NAME_FROM.includes(nm.from) ? R.clean(nm.name) : '';
      // Graphics are recorded even without a name, so an image whose alt was emptied is still matched to itself.
      const graphic = /^(img|svg|area|input)$/.test(tag) || role === 'img';
      if ((!t && !graphic) || !R.shown(el)) continue;
      const at = !R.atHidden(el) && !R.replacedBy(el, false) && !/^(presentation|none)$/.test(role);
      items.push({k: 'n', t: t.slice(0, 300), at, vis: R.vis(el), b: blockOf(el), sec: R.section(el), tag, from: nm.from});
    }
    return items;
  };
  window.__rtc = R;
  return true;
})()"""

RUNTIME_CODE = r"""async (page) => {
  const A = __ARGS__;
  const url = A.base + '/' + A.page;
  const raw = {page: A.page, errors: []};
  const settle = async () => {
    await page.evaluate(async () => {
      const within = (p, ms) => Promise.race([p, new Promise((r) => setTimeout(r, ms))]);
      await within(document.fonts.ready, 8000);
      await within(Promise.all([...document.images].map((i) => i.complete ? null : new Promise((r) => { i.onload = r; i.onerror = r; }))), 8000);
      await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
    });
  };
  // Park the pointer outside the viewport so no element starts out hovered.
  const away = async () => { try { await page.mouse.move(-20, -20); } catch (e) { try { await page.mouse.move(0, 0); } catch (e2) { /* ignore */ } } };
  const open = async (w, h, motion, css) => {
    await page.setViewportSize({width: w, height: h});
    await page.emulateMedia({reducedMotion: motion, colorScheme: 'light'});
    await away();
    await page.goto(url, {waitUntil: 'networkidle', timeout: 30000});
    if (css) await page.addStyleTag({content: css});
    await settle();
    await page.evaluate(A.helpers);
  };
  const step = async (name, fn) => { try { raw[name] = await fn(); } catch (e) { raw.errors.push(name + ': ' + String(e).slice(0, 300)); } };

  await step('motion', async () => {
    await open(1440, 900, 'reduce', null);
    const reduce = await page.evaluate(() => window.__rtc.motion());
    await open(1440, 900, 'no-preference', null);
    const allowed = await page.evaluate(() => window.__rtc.motion());
    return {reduce, allowed};
  });

  await step('focus', async () => {
    await open(1440, 900, 'reduce', A.freeze);
    const meta = await page.evaluate(() => {
      const R = window.__rtc;
      R.cands = [...document.querySelectorAll(R.FOCUSABLE)];
      R.base = R.cands.map((el) => R.snap(el));
      const vm = document.querySelector('meta[name=viewport]');
      return {viewport_meta: vm ? vm.getAttribute('content') : null, title: document.title,
              candidates: R.cands.map((el, i) => ({i, ...R.desc(el), tabindex: el.getAttribute('tabindex'), visible: R.vis(el),
                                                   disabled: !!el.disabled, inert: !!el.closest('[inert]')}))};
    });
    await page.evaluate(() => { if (document.activeElement && document.activeElement.blur) document.activeElement.blur(); window.scrollTo(0, 0); });
    const seq = [];
    let trap = null, cycle = false, same = 0, prev = null;
    for (let n = 0; n < A.maxTabs; n++) {
      await page.keyboard.press('Tab');
      await page.waitForTimeout(25);
      const info = await page.evaluate(() => {
        const R = window.__rtc;
        const el = document.activeElement;
        if (!el || el === document.body || el === document.documentElement) return {body: true};
        const i = R.cands.indexOf(el);
        const r = el.getBoundingClientRect();
        const vw = innerWidth, vh = innerHeight;
        const inView = r.bottom > 0 && r.right > 0 && r.top < vh && r.left < vw;
        const pts = [[r.left + r.width / 2, r.top + r.height / 2], [r.left + 2, r.top + 2], [r.right - 2, r.top + 2], [r.left + 2, r.bottom - 2], [r.right - 2, r.bottom - 2]];
        let covered = 0, coveredBy = null;
        for (const [x, y] of pts) {
          if (x < 0 || y < 0 || x >= vw || y >= vh) { covered++; continue; }
          const top = document.elementFromPoint(x, y);
          if (top && top !== el && !el.contains(top) && !top.contains(el)) { covered++; coveredBy = coveredBy || R.desc(top); }
        }
        const snap = R.snap(el);
        const changes = i >= 0 ? R.visibleDiff(R.base[i], snap) : null;
        return {i, ...R.desc(el), tabindex: el.getAttribute('tabindex'), rect: R.rect(el), visible: R.vis(el), in_view: inView,
                covered, covered_by: coveredBy, changes: changes ? changes.slice(0, 6) : null, indicator: R.indicator(el, snap.self),
                focus_visible: el.matches(':focus-visible')};
      });
      if (info.body) { if (seq.length) { cycle = true; break; } continue; }
      if (seq.length && info.i === seq[0].i && info.i >= 0) { cycle = true; break; }
      if (prev !== null && info.i === prev) { same++; if (same >= 2) { trap = info; break; } continue; }
      same = 0;
      prev = info.i;
      seq.push(info);
    }
    const names = await page.evaluate(() => {
      const R = window.__rtc;
      const out = [];
      for (const el of document.querySelectorAll(R.INTERACTIVE + ', img, svg[role=img], [role=img]')) {
        if (!R.vis(el)) continue;
        if (el.closest('[aria-hidden="true"]')) continue;
        const tag = el.tagName.toLowerCase();
        const kind = tag === 'img' || el.getAttribute('role') === 'img' || (tag === 'svg') ? 'image'
          : (['input', 'select', 'textarea'].includes(tag) && !['submit', 'button', 'reset', 'image'].includes(el.type)) ? 'field' : 'control';
        if (kind === 'control' && el.getAttribute('tabindex') === '-1' && !el.matches('a[href], button')) continue;
        const nm = R.name(el);
        out.push({...R.desc(el), kind, name: nm.name, from: nm.from, has_alt: tag === 'img' ? el.hasAttribute('alt') : null,
                  aria_label: R.clean(el.getAttribute('aria-label')) || null, visible_text: kind === 'control' ? R.visibleText(el) : null});
      }
      return out;
    });
    const text = await page.evaluate(() => window.__rtc.pageText());
    return {...meta, seq, trap, cycle_complete: cycle, max_tabs: A.maxTabs, names, text};
  });

  await step('a11y', async () => {
    const out = {};
    for (const [w, h] of A.a11yViewports) {
      await open(w, h, 'reduce', A.freeze);
      out[w] = await page.evaluate(() => window.__rtc.a11yItems());
    }
    return out;
  });

  await step('hover', async () => {
    await open(1440, 900, 'reduce', A.freeze);
    const count = await page.evaluate((max) => {
      const R = window.__rtc;
      // Parked off-screen elements (skip links) appear only on focus: nothing to hover.
      R.hov = [...document.querySelectorAll(R.HOVERABLE)].filter((el) => R.vis(el) && !R.geo(el).off).slice(0, max);
      return R.hov.length;
    }, A.maxHover);
    const out = [];
    for (let k = 0; k < count; k++) {
      await away();
      const pos = await page.evaluate((k) => {
        const R = window.__rtc;
        const el = R.hov[k];
        el.scrollIntoView({block: 'center', inline: 'center'});
        const r = el.getBoundingClientRect();
        R.hbase = R.snap(el);
        return {x: r.left + r.width / 2, y: r.top + r.height / 2};
      }, k);
      await page.mouse.move(pos.x, pos.y);
      await page.waitForTimeout(25);
      out.push(await page.evaluate(([k, x, y]) => {
        const R = window.__rtc;
        const el = R.hov[k];
        const top = document.elementFromPoint(x, y);
        const hit = !!top && (top === el || el.contains(top));
        return {k, ...R.desc(el), hit, covered_by: hit || !top ? null : R.desc(top), changes: R.visibleDiff(R.hbase, R.snap(el)).slice(0, 6)};
      }, [k, pos.x, pos.y]));
    }
    await away();
    return {tested: count, items: out};
  });

  await step('reflow', async () => {
    await open(A.reflow[0], A.reflow[1], 'reduce', A.freeze);
    return await page.evaluate(() => ({...window.__rtc.sideways(), text: window.__rtc.textState().filter((t) => t.clipped)}));
  });

  await step('zoom', async () => {
    await open(A.zoom[0], A.zoom[1], 'reduce', A.freeze);
    const res = await page.evaluate(() => ({...window.__rtc.sideways(), text: window.__rtc.textState().filter((t) => t.clipped)}));
    const total = await page.evaluate(() => document.documentElement.scrollHeight);
    const cover = [];
    for (const f of [0, 0.25, 0.5, 0.75]) {
      await page.evaluate((y) => window.scrollTo(0, y), Math.round(total * f));
      await page.waitForTimeout(30);
      cover.push({at: f, ...(await page.evaluate(() => window.__rtc.covering()))});
    }
    return {...res, covering: cover, page_height: total};
  });

  await step('spacing', async () => {
    const out = {};
    for (const w of A.spacingWidths) {
      await open(w, w === 390 ? 844 : 900, 'reduce', A.freeze);
      const before = await page.evaluate(() => ({text: window.__rtc.textState(), side: window.__rtc.sideways()}));
      await page.addStyleTag({content: A.spacing});
      await settle();
      const after = await page.evaluate(() => ({text: window.__rtc.textState(), side: window.__rtc.sideways()}));
      const pairs = [];
      for (const a of after.text) {
        const b = before.text[a.i];
        const same = b && b.label === a.label && b.tag === a.tag;
        const newClip = a.clipped && !(same && b.clipped);
        const newSpill = a.spill && !(same && b.spill);
        if (newClip || newSpill) pairs.push({...a, new_clip: !!newClip, new_spill: !!newSpill, before_clipped: same ? !!b.clipped : null});
      }
      out[w] = {elements: after.text.length, matched: before.text.length === after.text.length, problems: pairs.slice(0, 40),
                scroll_before: before.side.scroll_width, scroll_after: after.side.scroll_width, viewport: after.side.viewport,
                offenders_after: after.side.offenders};
    }
    return out;
  });
  return raw;
}"""


# ---------------------------------------------------------------- judging


def _label(d: dict) -> str:
    label = (d.get("label") or "").strip()
    where = d.get("section") or "page"
    tag = d.get("tag") or "?"
    return f'{tag} "{label[:60]}" ({where})' if label else f"{tag} without text ({where})"


def _group(check: str, criterion: str, severity: int, problem: str, items: list[dict], evidence: str,
           suggestion: str, viewport: str = "desktop") -> dict:
    labels = []
    for it in items:
        lab = _label(it)
        if lab not in labels:
            labels.append(lab)
    element = "; ".join(labels[:GROUP_LIMIT]) + (f"; and {len(labels) - GROUP_LIMIT} more" if len(labels) > GROUP_LIMIT else "")
    return {"check": check, "criterion": criterion, "severity": severity, "viewport": viewport, "element": element,
            "count": len(labels), "problem": problem, "evidence": evidence, "suggestion": suggestion}


def _letters(s: str) -> bool:
    return bool(re.search(r"[A-Za-z0-9\u00C0-\u024F\u0370-\u03FF\u0400-\u04FF\u4E00-\u9FFF]", s or ""))


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


# ---------------------------------------------------------------- kept text (this round against the last)

STOPWORDS = frozenset("a an and are as at be by for from in is it its of on or our per that the this to we with you your".split())
NAME_FROM = ("aria-labelledby", "aria-label", "alt", "svg-title", "title")
_TOKEN = re.compile(r"\$?\d(?:[\d,.]*\d)?%?|[^\W\d_]+(?:['\u2019-][^\W\d_]+)*")


def _tokens(text: str) -> list[str]:
    """Words and numbers that carry meaning, in order. Single letters, runs of single characters
    (split-flap tiles 'C E D A R', '0 1') and filler words are left out."""
    raw = _TOKEN.findall((text or "").lower())
    out = []
    for i, t in enumerate(raw):
        if len(t) == 1 and (not t.isdigit() or (i > 0 and len(raw[i - 1]) == 1) or (i + 1 < len(raw) and len(raw[i + 1]) == 1)):
            continue
        if t not in STOPWORDS:
            out.append(t)
    return out


def _blocks(items: list[dict]) -> list[dict]:
    """Group one viewport's recorded items (R.a11yItems) into blocks: what each block shows and what
    assistive tech reaches in it."""
    found: dict = {}
    for it in items or []:
        b = found.setdefault(it.get("b"), {"sec": it.get("sec") or "page", "vis": [], "at": [], "graphic": False, "shape": []})
        if it.get("vis") and it.get("k") == "t":
            b["vis"].append(it.get("t") or "")
        if it.get("vis") and it.get("k") == "n":
            b["graphic"] = True
            b["shape"].append(it.get("tag") or "graphic")
        if it.get("at"):
            b["at"].append(it.get("t") or "")
    out = []
    for b in found.values():
        vis_text = _norm(" ".join(b["vis"]))
        at = set(_tokens(" ".join(b["at"])))
        out.append({"sec": b["sec"], "vis_key": vis_text, "vis_tokens": set(_tokens(" ".join(b["vis"]))), "at_tokens": at,
                    "has_visible": bool(vis_text) or b["graphic"], "shape": " ".join(b["shape"]),
                    "label": (" ".join(b["vis"]) or " ".join(b["at"]) or (b["shape"][0] if b["shape"] else ""))[:70]})
    return out


def _block_key(b: dict) -> str:
    return b["vis_key"] or "@" + " ".join(sorted(b["at_tokens"]))


def _compare_blocks(prev: list[dict], cur: list[dict]) -> tuple[dict[str, int], list[dict]]:
    """Words assistive tech lost between two recordings of one viewport, and where.

    A block of the last round is matched to this round's block that shows the same text (same section
    first, then anywhere; blocks that show nothing match on what they say). A matched block that now
    gives assistive tech fewer words lost them. A block that showed something and has no match was
    removed or rewritten: that is the content review's business, not a loss. A block that showed
    nothing (screen-reader-only text) and has no match is lost. Words that moved to another block
    are not lost: per word, the loss is capped by the drop in blocks that carry it."""
    used: set[int] = set()
    by_sec: dict = {}
    by_key: dict = {}
    by_shape: dict = {}  # blocks that show only graphics: the same graphics in the same section
    for j, c in enumerate(cur):
        by_sec.setdefault((c["sec"], _block_key(c)), []).append(j)
        by_key.setdefault(_block_key(c), []).append(j)
        if not c["vis_key"] and c["shape"]:
            by_shape.setdefault((c["sec"], c["shape"]), []).append(j)
    loss: dict[str, int] = {}
    where: list[dict] = []
    for p in prev:
        if not p["at_tokens"]:
            continue
        key = _block_key(p)
        j = next((j for j in by_sec.get((p["sec"], key), []) if j not in used), None)
        if j is None:
            j = next((j for j in by_key.get(key, []) if j not in used), None)
        if j is None and not p["vis_key"] and p["shape"]:
            j = next((j for j in by_shape.get((p["sec"], p["shape"]), []) if j not in used), None)
        if j is not None:
            used.add(j)
            gone = p["at_tokens"] - cur[j]["at_tokens"]
            how = "hidden from assistive tech" if gone & cur[j]["vis_tokens"] else "screen-reader text removed"
        elif not p["has_visible"]:
            gone, how = set(p["at_tokens"]), "screen-reader-only text removed"
        else:
            continue
        if gone:
            for t in gone:
                loss[t] = loss.get(t, 0) + 1
            where.append({"section": p["sec"], "block": p["label"], "lost": sorted(gone), "how": how})
    carried_prev: dict[str, int] = {}
    carried_cur: dict[str, int] = {}
    for blocks, into in ((prev, carried_prev), (cur, carried_cur)):
        for b in blocks:
            for t in b["at_tokens"]:
                into[t] = into.get(t, 0) + 1
    lost = {t: min(n, carried_prev.get(t, 0) - carried_cur.get(t, 0)) for t, n in loss.items()}
    lost = {t: n for t, n in lost.items() if n > 0}
    where = [{**w, "lost": [t for t in w["lost"] if t in lost]} for w in where]
    return lost, [w for w in where if w["lost"]]


def _legacy_counts(raw: dict) -> dict[str, int]:
    """Per word, the page-text lines (1440 px, what a screen reader reaches) and attribute names that
    carry it: all an older recording without the a11y step can tell."""
    focus = raw.get("focus") or {}
    counts: dict[str, int] = {}
    for line in focus.get("text") or []:
        for t in set(_tokens(line.get("text"))):
            counts[t] = counts.get(t, 0) + 1
    for n in focus.get("names") or []:
        if n.get("from") in NAME_FROM and n.get("name"):
            for t in set(_tokens(n["name"])):
                counts[t] = counts.get(t, 0) + 1
    return counts


def kept_text(prev: dict | None, cur: dict, base: dict | list | None = None) -> dict:
    """Compare what assistive tech reaches on this round's page with the previous round's recording.

    base: the recording (or recordings) of earlier rounds whose words a later round had already lost.
    Those words stay lost, and flagged, until a round gives them back, so comparing only neighbours
    cannot let a loss drop out of sight. vs_bases lists each base's own status, in order."""
    if prev is None:
        return {"status": "not run", "note": "first round: nothing to compare", "viewports": {}}
    out = _kept_pair(prev, cur)
    out["vs_previous"] = out["status"]
    out["vs_bases"] = []
    for older_raw in (base if isinstance(base, list) else [base] if base is not None else []):
        older = _kept_pair(older_raw, cur)
        out["vs_bases"].append(older["status"])
        for w, v in older["viewports"].items():
            mine = out["viewports"].setdefault(w, {"compared": v["compared"], "lost": {}, "where": []})
            for t, n in v["lost"].items():
                mine["lost"][t] = max(mine["lost"].get(t, 0), n)
            seen = {(e["section"], e["block"]) for e in mine["where"]}
            mine["where"] += [{**e, "how": e["how"] + " in an earlier round, not given back"} for e in v["where"]
                              if (e["section"], e["block"]) not in seen]
        if older.get("note") and not out.get("note"):
            out["note"] = older["note"]
        if out["status"] == "not run" and older["status"] != "not run":
            out["status"] = "pass"
    if any(v["lost"] for v in out["viewports"].values()):
        out["status"] = "fail"
    return out


def _kept_pair(prev: dict, cur: dict) -> dict:
    pa, ca = prev.get("a11y") or {}, cur.get("a11y") or {}
    if not pa:
        return {"status": "not run", "note": "the previous round was recorded before this check: not compared", "viewports": {}}
    out: dict = {"status": "pass", "viewports": {}}
    if not ca:
        # This round was recorded without the a11y step (only for checking a recorded page against a newer
        # recording of the round before): only screen-reader-only words can be judged, from page-text lines.
        pb = _blocks(pa.get("1440") or pa.get(1440) or [])
        sr: dict[str, int] = {}
        for b in pb:
            for t in b["at_tokens"] - b["vis_tokens"]:
                sr[t] = sr.get(t, 0) + 1
        before, after = _legacy_counts(prev), _legacy_counts(cur)
        lost = {t: min(n, before.get(t, 0) - after.get(t, 0)) for t, n in sr.items()}
        lost = {t: n for t, n in lost.items() if n > 0}
        where = [{"section": b["sec"], "block": b["label"], "lost": sorted((b["at_tokens"] - b["vis_tokens"]) & set(lost)),
                  "how": "screen-reader text removed"} for b in pb if (b["at_tokens"] - b["vis_tokens"]) & set(lost)]
        out["note"] = "this round was recorded without the a11y step: screen-reader-only words compared by page-text lines"
        out["viewports"]["1440"] = {"compared": len(pb), "lost": lost, "where": where}
    else:
        for w in sorted(set(map(str, pa)) & set(map(str, ca)), key=lambda x: -int(x)):
            pb, cb = _blocks(pa.get(w) or pa.get(int(w))), _blocks(ca.get(w) or ca.get(int(w)))
            lost, where = _compare_blocks(pb, cb)
            out["viewports"][w] = {"compared": sum(1 for b in pb if b["at_tokens"]), "lost": lost, "where": where}
    if any(v["lost"] for v in out["viewports"].values()):
        out["status"] = "fail"
    return out


def _kept_finding(kept: dict) -> dict | None:
    views = {w: v for w, v in kept.get("viewports", {}).items() if v["lost"]}
    if not views:
        return None
    words: dict[str, int] = {}
    for v in views.values():
        for t, n in v["lost"].items():
            words[t] = max(words.get(t, 0), n)
    entries, seen = [], set()
    for v in views.values():
        for e in v["where"]:
            lab = f'{e["section"]}: "{e["block"][:50]}" lost {", ".join(e["lost"][:5])} ({e["how"]})'
            if lab not in seen:
                seen.add(lab)
                entries.append(lab)
    named = ", ".join(f"'{t}'" + (f" x{n}" if n > 1 else "") for t, n in sorted(words.items(), key=lambda x: (-x[1], x[0]))[:12])
    evidence = "; ".join(f"{w} px: {sum(v['lost'].values())} words lost in {len(v['where'])} blocks" for w, v in views.items())
    return {"check": "kept_text", "criterion": "1.3.1, 4.1.2", "severity": 3,
            "viewport": ", ".join("desktop" if w == "1440" else "mobile" for w in views),
            "element": "; ".join(entries[:GROUP_LIMIT]) + (f"; and {len(entries) - GROUP_LIMIT} more" if len(entries) > GROUP_LIMIT else ""),
            "count": len(entries),
            "problem": f"Words a screen reader reached in an earlier round are gone for it now, while the page still shows the same content: {named}.",
            "evidence": f"compared with the earlier rounds' recordings ({evidence})" + (f"; {kept['note']}" if kept.get("note") else ""),
            "suggestion": "Give the words back to assistive tech (visually hidden text, alt or aria-label), or take the visible content "
                          "away too if it should go. Never hide labels (aria-hidden, display:none) or delete screen-reader text to quiet a finding."}


def judge(raw: dict, prev: dict | None = None, base: dict | None = None) -> dict:
    """Turn raw browser measurements into findings (fixed rules, no model). With prev (the previous
    round's raw recording) the kept-text check also runs; base: see kept_text."""
    findings: list[dict] = []
    notes: list[str] = []  # measured and judged harmless: shown in the report, never a finding
    status: dict[str, dict] = {c: {"tested": 0, "findings": 0} for c in CHECKS}
    errors = list(raw.get("errors") or [])

    # -- focus and order
    focus = raw.get("focus")
    if focus:
        seq = focus.get("seq") or []
        status["focus"]["tested"] = len(seq)
        status["order"]["tested"] = len(focus.get("candidates") or [])
        no_ring = [s for s in seq if s.get("changes") is not None and not s["changes"]]
        if no_ring:
            findings.append(_group("focus", "2.4.7", 3, "Keyboard focus is not visible: nothing on screen changes when this gets focus.",
                                   no_ring, "Tab stops with no visible style change between unfocused and focused: "
                                   + ", ".join(f"#{s['i']}" for s in no_ring[:GROUP_LIMIT]),
                                   "Give it a :focus-visible style that shows clearly, e.g. a 2-3 px outline in a colour with 3:1 contrast."))
        low = [s for s in seq if (s.get("indicator") or {}).get("ratio") is not None and s["indicator"]["ratio"] < 3]
        if low:
            first = low[0]["indicator"]
            findings.append(_group("focus", "1.4.11", 3, "The focus outline is too faint against what it is drawn on.",
                                   low, f"outline {first.get('color')} on {first.get('against')} = {first.get('ratio')}:1 (needs 3:1)",
                                   "Use an outline colour with at least 3:1 contrast against the surrounding background."))
        hidden = [s for s in seq if not s.get("in_view") or s.get("covered", 0) >= 5]
        if hidden:
            cov = next((s.get("covered_by") for s in hidden if s.get("covered_by")), None)
            findings.append(_group("focus", "2.4.11", 3, "The focused element is hidden: off screen or covered by other content when it gets focus.",
                                   hidden, "covered by " + _label(cov) if cov else "outside the viewport when focused",
                                   "Keep focused elements on screen; give sticky parts scroll-padding or move them out of the way."))
        partly = [s for s in seq if s.get("in_view") and 0 < s.get("covered", 0) < 5]
        if partly:
            findings.append(_group("focus", "2.4.12", 1, "The focused element is partly covered by other content.", partly,
                                   "covered at some sample points by " + _label(partly[0].get("covered_by") or {}),
                                   "Add scroll-padding-top equal to the sticky part's height."))
        invisible = [s for s in seq if not s.get("visible")]
        if invisible:
            findings.append(_group("focus", "2.4.7", 3, "Tab lands on something that cannot be seen.", invisible,
                                   "focused element has no size, opacity 0 or visibility hidden",
                                   "Remove it from the tab order (tabindex=-1, hidden) or make it visible when focused."))
        if focus.get("trap"):
            findings.append(_group("order", "2.1.2", 4, "Keyboard trap: Tab stops moving.", [focus["trap"]],
                                   "focus stayed on the same element for three Tab presses", "Make Tab move on; remove the trap."))
        positive = [c for c in focus.get("candidates") or [] if (c.get("tabindex") or "").strip().lstrip("+").isdigit()
                    and int((c.get("tabindex") or "0").strip()) > 0]
        if positive:
            findings.append(_group("order", "2.4.3", 3, "A positive tabindex changes the focus order away from the reading order.", positive,
                                   "tabindex=" + ", ".join(str(c.get("tabindex")) for c in positive[:GROUP_LIMIT]),
                                   "Remove the positive tabindex; order the HTML the way it reads."))
        if focus.get("cycle_complete"):
            reached = {s.get("i") for s in seq}
            missed = [c for c in focus.get("candidates") or [] if c.get("visible") and c.get("i") not in reached
                      and (c.get("tabindex") or "") != "-1" and not c.get("inert") and not c.get("disabled")]
            if missed:
                findings.append(_group("order", "2.1.1", 3, "Visible controls that Tab never reaches.", missed,
                                       f"{len(missed)} of {len(focus.get('candidates') or [])} focusable elements were not reached",
                                       "Make every control reachable by keyboard in reading order."))
        elif seq:
            errors.append(f"focus: Tab did not cycle within {focus.get('max_tabs')} presses; reachability not judged")
        # names
        names = focus.get("names") or []
        status["names"]["tested"] = len(names)
        empty = [n for n in names if n["kind"] in ("control", "field") and not n.get("name")]
        if empty:
            findings.append(_group("names", "4.1.2", 3, "Control without an accessible name: a screen reader says only its role.", empty,
                                   "computed accessible name is empty", "Add visible text or an aria-label that says what it does."))
        symbols = [n for n in names if n["kind"] == "control" and n.get("name") and not _letters(n["name"])]
        if symbols:
            findings.append(_group("names", "4.1.2", 3, "Control named only by symbols.", symbols,
                                   "names: " + ", ".join(repr(n["name"]) for n in symbols[:GROUP_LIMIT]),
                                   "Give it a name in words (aria-label) and hide the symbol from assistive technology."))
        no_alt = [n for n in names if n["kind"] == "image" and ((n.get("tag") == "img" and not n.get("has_alt"))
                                                               or (n.get("tag") != "img" and not n.get("name")))]
        if no_alt:
            findings.append(_group("names", "1.1.1", 3, "Image without a text alternative.", no_alt,
                                   "img without alt attribute, or role=img without a name",
                                   "Add alt text (alt=\"\" only if purely decorative)."))
        placeholder = [n for n in names if n["kind"] == "field" and n.get("from") == "placeholder" and n.get("name")]
        if placeholder:
            findings.append(_group("names", "3.3.2", 3, "Field labelled only by its placeholder.", placeholder,
                                   "the only name comes from placeholder text, which disappears while typing",
                                   "Add a visible <label> tied to the field."))
        mismatch = []
        for n in names:
            vt, al = _norm(n.get("visible_text") or ""), _norm(n.get("aria_label") or "")
            if n["kind"] == "control" and al and vt and _letters(vt) and vt not in al:
                mismatch.append(n)
        if mismatch:
            n0 = mismatch[0]
            findings.append(_group("names", "2.5.3", 3, "The accessible name does not contain the visible label (voice users say what they see).",
                                   mismatch, f"visible \"{n0.get('visible_text')}\" vs aria-label \"{n0.get('aria_label')}\"",
                                   "Start the aria-label with the visible text, or drop the aria-label."))
        # page text for the content review
    hover = raw.get("hover")
    if hover:
        items = hover.get("items") or []
        status["hover"]["tested"] = len(items)
        flat = [h for h in items if h.get("hit") and not h.get("changes")]
        if flat:
            findings.append(_group("hover", "none (usability/craft)", 2, "No hover state: nothing changes under the pointer.", flat,
                                   f"{len(flat)} of {len(items)} links/buttons show no visible change on hover",
                                   "Add a :hover style (colour, underline, background or shadow) consistent with the page's system."))
        blocked = [h for h in items if not h.get("hit")]
        if blocked:
            findings.append(_group("hover", "none (usability/craft)", 2, "Another element sits on top of this control, so the pointer cannot reach its centre.",
                                   blocked, "covered by " + _label(blocked[0].get("covered_by") or {}),
                                   "Move the covering element or give it pointer-events: none."))

    reflow = raw.get("reflow")
    if reflow:
        status["reflow"]["tested"] = 1
        vw = reflow.get("viewport") or REFLOW_VIEWPORT[0]
        if (reflow.get("scroll_width") or 0) > vw + 1:
            off = reflow.get("offenders") or []
            findings.append(_group("reflow", "1.4.10", 3, f"At {REFLOW_VIEWPORT[0]} px wide the page scrolls sideways.", off or [{"tag": "page"}],
                                   f"document {reflow.get('scroll_width')} px wide in a {vw} px viewport; widest: "
                                   + ", ".join(f"{_label(o)} right edge {o.get('right')} px" for o in off[:3]),
                                   "Let rows wrap (flex-wrap, grid auto-fit, minmax) and avoid fixed widths; nothing wider than the viewport.",
                                   viewport="320"))
        elif reflow.get("page_overflow_hidden") and reflow.get("offenders"):
            off = reflow["offenders"]
            findings.append(_group("reflow", "1.4.10", 3, f"At {REFLOW_VIEWPORT[0]} px content runs past the edge and is cut off (the page hides sideways overflow).",
                                   off, ", ".join(f"{_label(o)} right edge {o.get('right')} px" for o in off[:3]),
                                   "Make the content fit instead of hiding the overflow.", viewport="320"))
        clipped = reflow.get("text") or []
        if clipped:
            findings.append(_group("reflow", "1.4.10", 3, f"Text is cut off at {REFLOW_VIEWPORT[0]} px.", clipped,
                                   "clipped by " + _label((clipped[0].get("clipped") or {}).get("by") or {})
                                   + f" by {(clipped[0].get('clipped') or {}).get('px')} px",
                                   "Let the box grow with its text (min-height, no fixed height) or wrap the text.", viewport="320"))

    zoom = raw.get("zoom")
    if zoom:
        status["zoom"]["tested"] = 1
        vh = ZOOM_VIEWPORT[1]
        worst = max(zoom.get("covering") or [{}], key=lambda c: c.get("covered_rows", 0))
        share = (worst.get("covered_rows", 0) / (worst.get("viewport_height") or vh)) if worst else 0
        if share > STICKY_SHARE:
            findings.append(_group("zoom", "1.4.10", 3, "At 400% zoom fixed or sticky parts cover too much of the screen to read.",
                                   worst.get("items") or [{"tag": "page"}],
                                   f"{round(share * 100)}% of the {worst.get('viewport_height')} px viewport covered at scroll {worst.get('at')} (limit {round(STICKY_SHARE * 100)}%)",
                                   "Make the header static at narrow or short viewports (e.g. @media (max-height: 480px) or (max-width: 480px)).",
                                   viewport="400% zoom"))
        reflow_failed = bool(reflow) and (reflow.get("scroll_width") or 0) > (reflow.get("viewport") or REFLOW_VIEWPORT[0]) + 1
        if (zoom.get("scroll_width") or 0) > (zoom.get("viewport") or ZOOM_VIEWPORT[0]) + 1 and not reflow_failed:
            off = zoom.get("offenders") or []
            findings.append(_group("zoom", "1.4.10", 3, "At 400% zoom the page scrolls sideways.", off or [{"tag": "page"}],
                                   f"document {zoom.get('scroll_width')} px in a {zoom.get('viewport')} px viewport",
                                   "Remove fixed widths; let content wrap.", viewport="400% zoom"))
        seen = {(t.get("tag"), t.get("label")) for t in (reflow or {}).get("text") or []}
        clipped = [t for t in zoom.get("text") or [] if (t.get("tag"), t.get("label")) not in seen]
        if clipped:
            findings.append(_group("zoom", "1.4.10", 3, "Text is cut off at 400% zoom.", clipped,
                                   "clipped by " + _label((clipped[0].get("clipped") or {}).get("by") or {}),
                                   "Avoid fixed heights on text boxes; use min-height.", viewport="400% zoom"))
        meta = ((focus or {}).get("viewport_meta") or "").lower().replace(" ", "")
        m = re.search(r"maximum-scale=([0-9.]+)", meta)
        if "user-scalable=no" in meta or "user-scalable=0" in meta or (m and float(m.group(1)) < 2):
            findings.append(_group("zoom", "1.4.4", 3, "The viewport meta tag stops people zooming.", [{"tag": "meta", "label": meta, "section": "head"}],
                                   f"content=\"{meta}\"", "Remove user-scalable=no and maximum-scale below 2.", viewport="mobile"))

    spacing = raw.get("spacing")
    if spacing:
        problems, side = [], []
        for w, res in sorted(spacing.items(), key=lambda kv: -int(kv[0])):
            status["spacing"]["tested"] += res.get("elements", 0)
            for p in res.get("problems") or []:
                spill = p.get("spill") or {}
                if not p.get("new_clip") and "harm" in spill and not spill["harm"]:
                    # ran out of its box onto free space it can still be read on: nothing is lost (not F104)
                    notes.append(f"spacing at {w} px: {_label(p)} runs {spill.get('px')} px out of "
                                 f"{_label(spill.get('box') or {})} into free space; nothing is cut off or covered")
                    continue
                problems.append({**p, "width": int(w)})
            if (res.get("scroll_after") or 0) > (res.get("viewport") or 0) + 1 and (res.get("scroll_before") or 0) <= (res.get("viewport") or 0) + 1:
                side.append({"tag": "page", "label": f"{res.get('scroll_after')} px wide at {w}", "section": "page", "width": int(w)})
        uniq: dict[tuple, dict] = {}
        widths: set[int] = set()
        for p in problems:
            uniq.setdefault((p.get("tag"), p.get("label")), p)
            widths.add(p["width"])
        if uniq:
            items = list(uniq.values())
            p0 = items[0]
            spill0 = p0.get("spill") or {}
            harm0 = spill0.get("harm") or {}
            onto = (f" onto {_label(harm0.get('with') or {})}" if harm0.get("kind") == "overlap" else
                    f" onto a background where its contrast is {harm0.get('ratio')}:1" if harm0.get("kind") == "contrast" else "")
            how = (f"clipped by {_label((p0.get('clipped') or {}).get('by') or {})} by {(p0.get('clipped') or {}).get('px')} px"
                   if p0.get("new_clip") else f"spills {spill0.get('px')} px out of {_label(spill0.get('box') or {})}{onto}")
            findings.append(_group("spacing", "1.4.12", 3, "With WCAG text spacing (line 1.5, letters 0.12 em, words 0.16 em, paragraphs 2 em) text is cut off or runs out of its box.",
                                   items, f"at {p0.get('width')} px: {how}",
                                   "Use min-height instead of fixed heights and let boxes grow with their text.",
                                   viewport=", ".join(str(w) for w in sorted(widths, reverse=True))))
        if side:
            findings.append(_group("spacing", "1.4.12", 3, "With WCAG text spacing the page starts scrolling sideways.", side,
                                   "; ".join(s["label"] for s in side), "Let rows wrap; avoid nowrap and fixed widths on text.",
                                   viewport=", ".join(str(s["width"]) for s in side)))

    motion = raw.get("motion")
    if motion:
        reduce = (motion.get("reduce") or {}).get("declared") or []
        status["motion"]["tested"] = len((motion.get("allowed") or {}).get("declared") or []) or len(reduce)
        bad: dict[str, list[dict]] = {}
        for a in reduce:
            if (a.get("duration") or 0) <= MOTION_MIN_SECONDS:
                continue
            moving = [p for p in a.get("props") or [] if MOVING.match(p)]
            if moving or a.get("iterations") == "infinite":
                bad.setdefault(a.get("name") or "?", []).append({**a, "moving": moving})
        for name, items in bad.items():
            a0 = items[0]
            what = ("animates " + ", ".join(sorted(set(a0["moving"])))) if a0["moving"] else "loops forever"
            findings.append(_group("motion", "2.3.3", 3, f"Animation \"{name}\" still runs when the visitor asks for reduced motion.", items,
                                   f"with prefers-reduced-motion: reduce, {name} {what}, {a0.get('duration')} s x {a0.get('iterations')}",
                                   "Wrap the animation in @media (prefers-reduced-motion: no-preference), or replace movement with a short fade."))

    # -- kept text: nothing a screen reader reached in the last round may vanish while the page still shows it
    kept = kept_text(prev, raw, base)
    if prev is not None:
        status["kept_text"] = {"tested": sum(v["compared"] for v in kept["viewports"].values()), "findings": 0}
    lost = _kept_finding(kept)
    if lost:
        findings.append(lost)

    for i, f in enumerate(findings, 1):
        f["id"] = f"R{i}"
        status[f["check"]]["findings"] += 1
    ran = {"focus": "focus", "order": "focus", "names": "focus", "hover": "hover", "reflow": "reflow", "zoom": "zoom",
           "spacing": "spacing", "motion": "motion"}
    for c, s in status.items():
        if (c == "kept_text" and kept["status"] == "not run") or (c in ran and not raw.get(ran[c])):
            s["status"] = "not run"
        else:
            s["status"] = "fail" if any(f["check"] == c and f["severity"] >= 2 for f in findings) else "pass"
    text = (focus or {}).get("text") or []
    return {"version": 1, "page": raw.get("page"), "checks": status, "findings": findings, "kept_text": kept,
            "failures": sum(1 for f in findings if f["severity"] >= 3), "errors": errors, "notes": notes[:20],
            "tab_order": [{"stop": n + 1, "element": _label(s), "focus_change": (s.get("changes") or ["none"])[0] if s.get("changes") is not None else "?"}
                          for n, s in enumerate((focus or {}).get("seq") or [])],
            "text_lines": len(text)}


# ---------------------------------------------------------------- reports


def page_text_md(raw: dict) -> str:
    lines = ["# Page text (visible, reading order; from the rendered page at 1440 px)", "",
             "Quote from here exactly; each line is one block: [tag] text.", ""]
    section = None
    for t in ((raw.get("focus") or {}).get("text") or []):
        if t.get("section") != section:
            section = t.get("section")
            lines += ["", f"## {section}"]
        lines.append(f"- [{t.get('tag')}] {t.get('text')}")
    return "\n".join(lines) + "\n"


def report_md(result: dict) -> str:
    lines = [f"# Runtime checks — {result.get('page')}", "",
             "Measured in a real browser with fixed rules (no model): keyboard and focus, accessible names, reflow at 320 px,",
             "400% zoom (320 x 200 CSS px), WCAG 1.4.12 text spacing, prefers-reduced-motion, hover states.", "",
             "| check | status | tested | findings |", "|---|---|---|---|"]
    for c, s in result["checks"].items():
        lines.append(f"| {c} | {s['status']} | {s['tested']} | {s['findings']} |")
    lines += ["", "## Findings", ""]
    if not result["findings"]:
        lines.append("None.")
    for f in result["findings"]:
        lines += [f"- {f['id']} [{f['check']}, WCAG {f['criterion']}, severity {f['severity']}, {f['viewport']}] {f['problem']}",
                  f"  Element: {f['element']}", f"  Evidence: {f['evidence']}", f"  Suggestion: {f['suggestion']}"]
    kept = result.get("kept_text") or {}
    if kept:
        lines += ["", "## Kept text (against the previous round)", "", f"- {kept.get('status')}" + (f": {kept['note']}" if kept.get("note") else "")]
        for w, v in kept.get("viewports", {}).items():
            lines.append(f"- {w} px: {v['compared']} blocks compared, words lost: " + (", ".join(f"{t} x{n}" for t, n in v["lost"].items()) or "none"))
    if result.get("notes"):
        lines += ["", "## Measured and judged harmless", ""] + [f"- {n}" for n in result["notes"]]
    if result.get("errors"):
        lines += ["", "## Could not check", ""] + [f"- {e}" for e in result["errors"]]
    lines += ["", "## Tab order", ""]
    for t in result.get("tab_order", [])[:60]:
        lines.append(f"{t['stop']}. {t['element']} — {t['focus_change']}")
    return "\n".join(lines) + "\n"


def write_outputs(raw: dict, out: Path, prev: dict | None = None, base: dict | None = None) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    result = judge(raw, prev, base)
    (out / "raw.json").write_text(json.dumps(raw, indent=1, ensure_ascii=False))
    (out / "runtime.json").write_text(json.dumps(result, indent=1, ensure_ascii=False))
    (out / "RUNTIME.md").write_text(report_md(result))
    (out / "page-text.md").write_text(page_text_md(raw))
    return result


# ---------------------------------------------------------------- fixture proof

FIXTURE_DIR = HERE.parent / "testpages" / "runtime"


def _matches(finding: dict, want: dict) -> bool:
    if finding.get("check") != want.get("check") or finding.get("criterion") != want.get("criterion"):
        return False
    hay = " ".join(str(finding.get(k, "")) for k in ("element", "problem", "evidence")).lower()
    return str(want.get("match", "")).lower() in hay


def grade(planted: dict, control: dict, expected: dict) -> dict:
    """Recall of the planted problems and false alarms on the clean control (any finding counts)."""
    plants = []
    used: set[str] = set()
    for want in expected["plants"]:
        hit = next((f for f in planted["findings"] if _matches(f, want)), None)
        plants.append({"id": want["id"], "check": want["check"], "criterion": want["criterion"], "found": hit["id"] if hit else None})
        if hit:
            used.add(hit["id"])
    explained = []
    for f in planted["findings"]:
        if f["id"] in used:
            continue
        why = next((c for c in expected.get("consequences", []) if _matches(f, c)), None)
        explained.append({"finding": f["id"], "check": f["check"], "criterion": f["criterion"],
                          "consequence_of": why["plant"] if why else None})
    found = sum(1 for p in plants if p["found"])
    unexplained = [e for e in explained if not e["consequence_of"]]
    false_alarms = [{"id": f["id"], "check": f["check"], "criterion": f["criterion"], "element": f["element"]}
                    for f in control["findings"]]
    return {"plants": plants, "recall": f"{found}/{len(plants)}", "extra_findings": explained,
            "unexplained_on_planted": len(unexplained), "control_false_alarms": false_alarms,
            "passed": found == len(plants) and not false_alarms and not unexplained,
            "errors": {"planted": planted.get("errors"), "control": control.get("errors")}}


def fixture_proof(out: Path, browser: str | None = None, serve_host: str | None = None, raws: dict | None = None) -> dict:
    """Run (or re-judge recorded raws for) the planted page and the clean control; grade them."""
    expected = json.loads((FIXTURE_DIR / "expected.json").read_text())
    results = {}
    for kind in ("planted", "control"):
        raw = raws[kind] if raws else measure(FIXTURE_DIR, expected[kind], browser, serve_host)
        results[kind] = write_outputs(raw, out / kind)
    graded = grade(results["planted"], results["control"], expected)
    (out / "grade.json").write_text(json.dumps(graded, indent=1))
    lines = ["# Runtime checks — planted fixture and clean control", "",
             f"Recall {graded['recall']}; unexplained findings on the planted page {graded['unexplained_on_planted']}; "
             f"false alarms on the control {len(graded['control_false_alarms'])}; passed: {graded['passed']}.", "",
             "| plant | check | WCAG | found as |", "|---|---|---|---|"]
    lines += [f"| {p['id']} | {p['check']} | {p['criterion']} | {p['found'] or 'MISSED'} |" for p in graded["plants"]]
    lines += ["", "Other findings on the planted page (consequences of a plant):", ""]
    lines += [f"- {e['finding']} {e['check']} {e['criterion']}: {('consequence of ' + e['consequence_of']) if e['consequence_of'] else 'UNEXPLAINED'}"
              for e in graded["extra_findings"]] or ["- none"]
    lines += ["", "Control findings:", ""] + ([f"- {f['id']} {f['check']} {f['criterion']}: {f['element']}" for f in graded["control_false_alarms"]] or ["- none"])
    (out / "GRADE.md").write_text("\n".join(lines) + "\n")
    return graded


# ---------------------------------------------------------------- browser


def measure(site: Path, page: str = "index.html", browser: str | None = None, serve_host: str | None = None) -> dict:
    """Serve the site and run every runtime measurement in one browser session."""
    browser = browser or BROWSER
    host = serve_host or SERVE_HOST or urllib.parse.urlparse(browser).hostname or "playwright-mcp"
    base, srv = h2p.serve(site, site, host)
    try:
        args = {"base": base, "page": page.lstrip("/"), "helpers": HELPERS, "freeze": FREEZE_CSS, "spacing": SPACING_CSS,
                "maxTabs": MAX_TABS, "maxHover": MAX_HOVER, "reflow": list(REFLOW_VIEWPORT), "zoom": list(ZOOM_VIEWPORT),
                "spacingWidths": list(SPACING_WIDTHS), "a11yViewports": [list(v) for v in A11Y_VIEWPORTS]}
        raw = h2p.browser_run(browser, [RUNTIME_CODE.replace("__ARGS__", json.dumps(args))], timeout=600)[0]
    finally:
        srv.shutdown()
    if not isinstance(raw, dict):
        raise RuntimeError(f"runtime checks returned no result: {str(raw)[:200]}")
    return raw


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("--site")
    p.add_argument("--page", default="index.html")
    p.add_argument("--out", required=True)
    p.add_argument("--browser", default=None)
    p.add_argument("--serve-host", default=None)
    p.add_argument("--raw", default=None, help="judge a recorded raw.json instead of opening a browser")
    p.add_argument("--prev", default=None, help="the previous round's raw.json: also check that no accessible text was lost")
    p.add_argument("--base", default=None, help="with --prev: an earlier round's raw.json whose lost words must come back")
    p.add_argument("--fixture-proof", action="store_true", help="run the planted page and clean control and grade them")
    a = p.parse_args()
    if a.fixture_proof:
        graded = fixture_proof(Path(a.out), a.browser, a.serve_host)
        print(json.dumps({k: graded[k] for k in ("recall", "unexplained_on_planted", "passed")}
                         | {"control_false_alarms": len(graded["control_false_alarms"])}))
        return 0 if graded["passed"] else 1
    if a.raw:
        raw = json.loads(Path(a.raw).read_text())
    else:
        if not a.site:
            raise SystemExit("--site or --raw required")
        raw = measure(Path(a.site).resolve(), a.page, a.browser, a.serve_host)
    prev = json.loads(Path(a.prev).read_text()) if a.prev else None
    base = json.loads(Path(a.base).read_text()) if a.base else None
    result = write_outputs(raw, Path(a.out), prev, base)
    print(json.dumps({"page": result["page"], "failures": result["failures"], "findings": len(result["findings"]),
                      "checks": {c: s["status"] for c, s in result["checks"].items()}, "errors": result["errors"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
