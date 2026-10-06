"""The five audience axes of a page, measured (docs/design-files.md, Design queue #38). Model-free.

A research direction sets five axes (research_contracts.AXES): density, type scale, colour energy, motion
and copy tone. This module measures them on a rendered page so a concept can be checked against its
direction, and so trial pages can be graded:

- density: the first screen at 1440x900: content items (text blocks, images, controls), words, and the
  share of the screen they cover (10 px grid);
- type scale: body size (character-weighted median of the page's text) and the largest text on the first
  screen;
- colour energy: OKLab chroma of the first screen's pixels (mean, and the share of saturated pixels),
  with the lightness spread;
- motion: animated elements after a scroll through the page, endless loops, and seconds of animation;
- copy tone: second person, contractions, reading ease, acronyms and figures in the page's words.

The same facts give token use: the share of the page's colour and font values that come from a token set.

The JavaScript runs in a browser page (playwright-mcp in temper, or the host's playwright); the levels are
computed here so every caller classifies the same way. Thresholds were set on 9 earlier concept pages and
8 public product sites before the #38 trial keys were sealed (results/research-step/CALIBRATION.md in
Design's lab).
"""
from __future__ import annotations

import json
import math
import re
from typing import Any

LEVELS = {"density": ("low", "medium", "high"),
          "type_scale": ("compact", "medium", "large"),
          "colour_energy": ("low", "medium", "high"),
          "motion": ("low", "medium", "high"),
          "copy_tone": ("expert", "neutral", "friendly")}

# What each level means, in numbers a designer can aim at (FOR_DESIGN.md quotes these).
TARGETS = {
    "density": {"low": "first screen (1440x900): at most 20 content items and 60 words",
                "medium": "first screen: about 20-45 content items or 60-120 words",
                "high": "first screen: 45+ content items or 120+ words (show the working product)"},
    "type_scale": {"compact": "body text 16 px or less and the largest text 64 px or less",
                   "medium": "between compact and large",
                   "large": "body 18 px or more, or the largest text 84 px or more"},
    "colour_energy": {"low": "mostly neutral: mean chroma under 0.025 and under 8% saturated pixels on the first screen",
                      "medium": "one or two colours with presence: between low and high",
                      "high": "colourful: mean chroma 0.065+ or 30%+ saturated pixels on the first screen"},
    "motion": {"low": "at most 3 animated elements, no endless loops, 3 s of animation in total",
               "medium": "between low and high (a load reveal, a few scroll reveals)",
               "high": "10+ animated elements, or 2+ endless loops, or 10+ s of animation"},
    "copy_tone": {"expert": "the users' working terms and figures; few 'you', few contractions",
                  "neutral": "between expert and friendly",
                  "friendly": "warm second person ('you'), contractions, short plain words"},
}

PAGE_FN = r"""async () => {
  const vw = window.innerWidth, vh = window.innerHeight;
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const within = (p, ms) => Promise.race([p, sleep(ms)]);
  await within(document.fonts.ready, 8000);
  const all = () => (document.getAnimations ? document.getAnimations() : []);
  const running = () => all().filter((a) => {
    const t = a.effect && a.effect.getComputedTiming ? a.effect.getComputedTiming() : null;
    return a.playState === 'running' && t && t.endTime !== Infinity;
  });
  const arrival = all().length;
  for (let i = 0; i < 40 && running().length; i++) await sleep(150);
  const hidden = (el) => {
    for (let e = el; e && e.nodeType === 1; e = e.parentElement) {
      const s = getComputedStyle(e);
      if (s.display === 'none' || s.visibility === 'hidden' || parseFloat(s.opacity) < 0.05) return true;
    }
    return false;
  };
  // scroll through: scroll reveals start when their section comes into view
  const height = Math.min(document.documentElement.scrollHeight, 12000);
  let seen = arrival;
  for (let y = 0; y < height; y += Math.round(vh * 0.8)) {
    window.scrollTo(0, y); await sleep(220); seen = Math.max(seen, all().length);
  }
  window.scrollTo(0, 0); await sleep(200);
  for (let i = 0; i < 40 && running().length; i++) await sleep(150);
  const rgb = (c) => {
    const m = /rgba?\(\s*([\d.]+)[ ,]+([\d.]+)[ ,]+([\d.]+)(?:\s*[,/]\s*([\d.]+%?))?\s*\)/.exec(c || '');
    if (!m) return null;
    let a = m[4] === undefined ? 1 : (m[4].endsWith('%') ? parseFloat(m[4]) / 100 : parseFloat(m[4]));
    if (a <= 0.02) return null;
    const h = (v) => Math.max(0, Math.min(255, Math.round(parseFloat(v)))).toString(16).padStart(2, '0');
    return '#' + h(m[1]) + h(m[2]) + h(m[3]);
  };
  const colours = new Map(), fonts = new Map(), sizes = new Map();
  const add = (m, k, n) => { if (k) m.set(k, (m.get(k) || 0) + n); };
  const first = (f) => (f || '').split(',')[0].replace(/["']/g, '').trim().toLowerCase();
  const cell = 10, gw = Math.ceil(vw / cell), gh = Math.ceil(vh / cell), grid = new Uint8Array(gw * gh);
  const mark = (r) => {
    const x0 = Math.max(0, Math.floor(r.left / cell)), x1 = Math.min(gw, Math.ceil(r.right / cell));
    const y0 = Math.max(0, Math.floor(r.top / cell)), y1 = Math.min(gh, Math.ceil(r.bottom / cell));
    for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) grid[y * gw + x] = 1;
  };
  const onFirst = (r) => r.bottom > 0 && r.top < vh && r.right > 0 && r.left < vw;
  const items = new Set(), texts = [];
  let firstWords = 0, display = 0, h1 = 0;
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  while (walker.nextNode()) {
    const node = walker.currentNode, t = node.textContent.replace(/\s+/g, ' ').trim(), el = node.parentElement;
    if (!t || !el || ['SCRIPT', 'STYLE', 'NOSCRIPT', 'TEMPLATE', 'TITLE'].includes(el.tagName) || hidden(el)) continue;
    const range = document.createRange(); range.selectNodeContents(node);
    const rects = [...range.getClientRects()].filter((r) => r.width > 2 && r.height > 2);
    if (!rects.length) continue;
    const s = getComputedStyle(el), fs = parseFloat(s.fontSize);
    const n = (t.match(/[\p{L}\p{N}][\p{L}\p{N}'\u2019.-]*/gu) || []).length;
    texts.push(t);
    add(sizes, String(fs), t.length);
    add(colours, rgb(s.color), 1);
    add(fonts, first(s.fontFamily), t.length);
    const shown = rects.filter(onFirst);
    if (shown.length) {
      items.add(el); firstWords += n; shown.forEach(mark);
      if (t.replace(/\s/g, '').length >= 2) display = Math.max(display, fs);
    }
    if (el.closest('h1')) h1 = Math.max(h1, fs);
  }
  const media = 'img, svg, canvas, video, picture, input, select, textarea, button, [role=img], [role=button]';
  for (const el of document.querySelectorAll(media)) {
    const tag = el.tagName.toLowerCase();
    if (tag === 'svg' ? (el.parentElement && el.parentElement.closest('svg')) : el.closest('svg')) continue;
    if (hidden(el)) continue;
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4 || !onFirst(r)) continue;
    const area = Math.max(0, Math.min(r.right, vw) - Math.max(r.left, 0)) * Math.max(0, Math.min(r.bottom, vh) - Math.max(r.top, 0));
    if (area > 0.7 * vw * vh) continue;  // a backdrop, not content
    items.add(el); mark(r);
  }
  let animated = 0, loops = 0, seconds = 0, transitions = 0;
  const secs = (v) => (v || '0s').split(',').map((x) => x.trim().endsWith('ms') ? parseFloat(x) / 1000 : parseFloat(x) || 0);
  for (const el of document.querySelectorAll('body, body *')) {
    if (hidden(el)) continue;
    const s = getComputedStyle(el);
    const svgPart = el instanceof SVGElement && el.tagName.toLowerCase() !== 'svg';
    if (s.animationName && s.animationName !== 'none') {
      animated++;
      const d = secs(s.animationDuration), dl = secs(s.animationDelay), it = (s.animationIterationCount || '1').split(',');
      d.forEach((x, i) => {
        const n = (it[i % it.length] || '1').trim();
        if (n === 'infinite') { if (x > 0) loops++; } else seconds += (dl[i % dl.length] || 0) + x * (parseFloat(n) || 1);
      });
    }
    if (secs(s.transitionDuration).some((x) => x > 0)) transitions++;
    const r = svgPart ? null : el.getBoundingClientRect();
    if (s.backgroundColor) add(colours, rgb(s.backgroundColor), 1);
    for (const m of (s.backgroundImage || '').matchAll(/rgba?\([^)]*\)/g)) add(colours, rgb(m[0]), 1);
    for (const side of ['Top', 'Right', 'Bottom', 'Left']) {
      if (parseFloat(s['border' + side + 'Width']) > 0 && s['border' + side + 'Style'] !== 'none') add(colours, rgb(s['border' + side + 'Color']), 1);
    }
    for (const m of (s.boxShadow || '').matchAll(/rgba?\([^)]*\)/g)) add(colours, rgb(m[0]), 1);
    if (el instanceof SVGElement) {
      if (s.fill && s.fill !== 'none') add(colours, rgb(s.fill), 1);
      if (s.stroke && s.stroke !== 'none') add(colours, rgb(s.stroke), 1);
    }
  }
  for (const a of all()) {
    const t = a.effect && a.effect.getComputedTiming ? a.effect.getComputedTiming() : null;
    if (a.playState === 'running' && t && t.endTime === Infinity && !(a instanceof CSSAnimation)) loops++;
  }
  const covered = grid.reduce((x, y) => x + y, 0) / grid.length;
  return {
    viewport: [vw, vh], first_items: items.size, first_words: firstWords, first_fill: Math.round(covered * 1000) / 1000,
    sizes: Object.fromEntries(sizes), display_px: display, h1_px: h1,
    animated, loops, animation_seconds: Math.round(seconds * 100) / 100, transitions, arrival_animations: arrival,
    scroll_animations: seen,
    colours: Object.fromEntries(colours), fonts: Object.fromEntries(fonts),
    text: texts.join('\n').slice(0, 60000), height: document.documentElement.scrollHeight
  };
}"""

# Pixel statistics of a first-screen screenshot (PNG at 1440 wide), drawn into a canvas.
COLOUR_FN = r"""async (url) => {
  const img = await new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => rej(new Error('load ' + url)); i.src = url; });
  const W = 360, H = 225, c = document.createElement('canvas'); c.width = W; c.height = H;
  const g = c.getContext('2d');
  g.drawImage(img, 0, 0, img.width, Math.min(img.height, img.width * 900 / 1440), 0, 0, W, H);
  const d = g.getImageData(0, 0, W, H).data;
  const lin = (v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
  let n = 0, sc = 0, sat = 0, vivid = 0, sl = 0, sl2 = 0, dark = 0;
  for (let k = 0; k < d.length; k += 4) {
    const r = lin(d[k]), gg = lin(d[k + 1]), b = lin(d[k + 2]);
    const l = Math.cbrt(0.4122214708 * r + 0.5363325363 * gg + 0.0514459929 * b);
    const m = Math.cbrt(0.2119034982 * r + 0.6806995451 * gg + 0.1073969566 * b);
    const s = Math.cbrt(0.0883024619 * r + 0.2817188376 * gg + 0.6299787005 * b);
    const L = 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s;
    const A = 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s;
    const B = 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s;
    const C = Math.hypot(A, B);
    n++; sc += C; sl += L; sl2 += L * L;
    if (C > 0.08) sat++;
    if (C > 0.15) vivid++;
    if (L < 0.35) dark++;
  }
  const mean = sl / n;
  return {mean_chroma: Math.round(sc / n * 10000) / 10000, saturated_share: Math.round(sat / n * 1000) / 1000,
          vivid_share: Math.round(vivid / n * 1000) / 1000, lightness_mean: Math.round(mean * 1000) / 1000,
          lightness_spread: Math.round(Math.sqrt(Math.max(0, sl2 / n - mean * mean)) * 1000) / 1000,
          dark_share: Math.round(dark / n * 1000) / 1000};
}"""

# playwright-mcp: measure pages served at A.base; first screens go to A.base/__put/<name>-first.png.
MEASURE_CODE = r"""async (page) => {
  const A = __ARGS__;
  const out = [];
  for (const job of A.jobs) {
    try {
      await page.setViewportSize({width: 1440, height: 900});
      await page.emulateMedia({reducedMotion: 'no-preference', colorScheme: 'light'});
      await page.goto(job.url, {waitUntil: job.external ? 'domcontentloaded' : 'networkidle', timeout: job.external ? 30000 : 20000});
      if (job.external) await page.waitForTimeout(2500);
      const facts = await page.evaluate(__PAGE_FN__);
      const shot = await page.screenshot({clip: {x: 0, y: 0, width: 1440, height: 900}, animations: 'disabled', caret: 'hide', scale: 'css', timeout: 30000});
      const r = await page.request.put(A.base + '/__put/' + job.name + '-first.png', {data: shot, headers: {'content-type': 'application/octet-stream'}});
      if (!r.ok()) throw new Error('upload failed ' + r.status());
      await page.goto(A.base + '/__out/' + job.name + '-first.png');
      facts.pixels = await page.evaluate(__COLOUR_FN__, A.base + '/__out/' + job.name + '-first.png');
      out.push({name: job.name, ok: true, facts});
    } catch (e) {
      out.push({name: job.name, ok: false, error: String(e).slice(0, 300)});
    }
  }
  return out;
}"""


def measure_code(base: str, jobs: list[dict]) -> str:
    return (MEASURE_CODE.replace("__PAGE_FN__", PAGE_FN).replace("__COLOUR_FN__", COLOUR_FN)
            .replace("__ARGS__", json.dumps({"base": base, "jobs": jobs})))


# ---------------------------------------------------------------- copy tone

WORD = re.compile(r"[A-Za-z][A-Za-z'\u2019]*")
YOU = {"you", "your", "you're", "you'll", "you've", "you'd", "yours", "yourself"}
CONTRACTION = re.compile(r"\b[A-Za-z]+(?:'|\u2019)(?:s|re|ll|ve|d|t|m)\b", re.I)
ACRONYM = re.compile(r"\b[A-Z]{2,5}s?\b")
FIGURE = re.compile(r"(?<![\w.])\d[\d,.:/%-]*")
NOT_ACRONYMS = {"OK", "AM", "PM", "US", "UK", "EU", "FAQ", "I", "A"}


def syllables(word: str) -> int:
    w = word.lower().strip("'\u2019")
    if len(w) <= 3:
        return 1
    w = re.sub(r"(?:[^laeiouy]es|ed|[^laeiouy]e)$", "", w)
    w = re.sub(r"^y", "", w)
    return max(1, len(re.findall(r"[aeiouy]{1,2}", w)))


def tone_facts(text: str) -> dict:
    """The words' tone: second person, contractions, reading ease (Flesch), acronyms and figures per 100 words."""
    words = WORD.findall(text)
    n = max(1, len(words))
    sentences = max(1, len(re.findall(r"[.!?]+(?:\s|$)", text)) + text.count("\n") // 2)
    syl = sum(syllables(w) for w in words)
    ease = 206.835 - 1.015 * (n / sentences) - 84.6 * (syl / n)
    acronyms = [a for a in ACRONYM.findall(text) if a.rstrip("s") not in NOT_ACRONYMS]
    return {"words": len(words),
            "you_per_100": round(100 * sum(w.lower().replace("\u2019", "'") in YOU for w in words) / n, 2),
            "contractions_per_100": round(100 * len(CONTRACTION.findall(text)) / n, 2),
            "reading_ease": round(ease, 1),
            "acronyms_per_100": round(100 * len(acronyms) / n, 2),
            "figures_per_100": round(100 * len(FIGURE.findall(text)) / n, 2),
            "exclaims_per_100": round(100 * text.count("!") / n, 2)}


# ---------------------------------------------------------------- levels

def body_px(sizes: dict) -> float:
    """Character-weighted median font size."""
    pairs = sorted((float(k), v) for k, v in (sizes or {}).items())
    total = sum(v for _, v in pairs)
    if not total:
        return 0.0
    run = 0
    for size, count in pairs:
        run += count
        if run >= total / 2:
            return size
    return pairs[-1][0]


def levels(facts: dict) -> dict:
    """The five axes from measured facts: {axis: {level, why}}."""
    out = {}
    items, words, fill = facts.get("first_items", 0), facts.get("first_words", 0), facts.get("first_fill", 0.0)
    # Items and words, not covered area: a full-bleed picture covers the screen without adding content.
    if items >= 45 or words >= 120:
        lvl = "high"
    elif items <= 20 and words <= 60:
        lvl = "low"
    else:
        lvl = "medium"
    out["density"] = {"level": lvl, "why": f"{items} items, {words} words, {round(fill * 100)}% covered on the first screen"}
    body, display = body_px(facts.get("sizes", {})), float(facts.get("display_px") or 0)
    if body <= 16 and display <= 64:
        lvl = "compact"
    elif body >= 18 or display >= 84:
        lvl = "large"
    else:
        lvl = "medium"
    out["type_scale"] = {"level": lvl, "why": f"body {body:g} px, largest first-screen text {display:g} px"}
    px = facts.get("pixels") or {}
    mc, ss = px.get("mean_chroma", 0.0), px.get("saturated_share", 0.0)
    if mc >= 0.065 or ss >= 0.30:
        lvl = "high"
    elif mc < 0.025 and ss < 0.08:
        lvl = "low"
    else:
        lvl = "medium"
    out["colour_energy"] = {"level": lvl, "why": f"mean chroma {mc}, {round(ss * 100)}% saturated pixels, "
                                                 f"lightness spread {px.get('lightness_spread')}"}
    n, loops, secs = facts.get("animated", 0), facts.get("loops", 0), facts.get("animation_seconds", 0.0)
    if n >= 10 or loops >= 2 or secs >= 10:
        lvl = "high"
    elif n <= 3 and loops == 0 and secs <= 3:
        lvl = "low"
    else:
        lvl = "medium"
    out["motion"] = {"level": lvl, "why": f"{n} animated elements, {loops} endless loops, {secs:g} s of animation"}
    tone = tone_facts(facts.get("text", ""))
    friendly = (tone["you_per_100"] >= 3) + (tone["contractions_per_100"] >= 1) + (tone["reading_ease"] >= 65) \
        + (tone["exclaims_per_100"] >= 0.5)
    expert = (tone["acronyms_per_100"] >= 1) + (tone["figures_per_100"] >= 4) + (tone["reading_ease"] < 50) \
        + (tone["you_per_100"] < 1.5)
    score = friendly - expert
    lvl = "friendly" if score >= 2 else "expert" if score <= -2 else "neutral"
    out["copy_tone"] = {"level": lvl, "why": f"friendly {friendly}/4, expert {expert}/4 (you {tone['you_per_100']}, "
                                              f"contractions {tone['contractions_per_100']}, ease {tone['reading_ease']}, "
                                              f"acronyms {tone['acronyms_per_100']}, figures {tone['figures_per_100']} per 100 words)",
                        "facts": tone}
    return out


def agreement(measured: dict, wanted: dict) -> dict:
    """How many of the five axes a page matches: {matched, total, misses: [axis: wanted vs measured]}."""
    misses = [f"{k}: wanted {wanted[k]}, measured {measured[k]['level']} ({measured[k]['why']})"
              for k in LEVELS if k in wanted and measured.get(k, {}).get("level") != wanted[k]]
    total = sum(1 for k in LEVELS if k in wanted)
    return {"matched": total - len(misses), "total": total, "misses": misses}


def axes_apart(a: dict, b: dict) -> int:
    return sum(1 for k in LEVELS if a.get(k, {}).get("level") != b.get(k, {}).get("level"))


# ---------------------------------------------------------------- token use

def _hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def token_use(facts: dict, hexes: list[str], fonts: list[str], tolerance: int = 2) -> dict:
    """Share of the page's colour values (text, backgrounds, gradients, borders, shadows, SVG paint; alpha
    ignored) and of its text (by characters, first font family) that come from the tokens."""
    want = [_hex_rgb(h) for h in hexes]
    colours = facts.get("colours", {}) or {}
    total = sum(colours.values()) or 0
    good = 0
    off: dict[str, int] = {}
    for value, count in colours.items():
        rgb = _hex_rgb(value)
        if any(max(abs(rgb[i] - w[i]) for i in range(3)) <= tolerance for w in want):
            good += count
        else:
            off[value] = count
    families = {f.lower() for f in fonts}
    font_counts = facts.get("fonts", {}) or {}
    ftotal = sum(font_counts.values()) or 0
    fgood = sum(v for k, v in font_counts.items() if k.lower() in families)
    return {"colour_share": round(good / total, 4) if total else 1.0, "colour_values": total,
            "off_token_colours": dict(sorted(off.items(), key=lambda kv: -kv[1])[:12]),
            "font_share": round(fgood / ftotal, 4) if ftotal else 1.0,
            "off_token_fonts": {k: v for k, v in font_counts.items() if k.lower() not in families}}


def chroma(hex_value: str) -> float:
    """OKLab chroma of one colour (for describing palettes)."""
    def lin(v: float) -> float:
        v /= 255
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(x) for x in _hex_rgb(hex_value))
    l_ = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m_ = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s_ = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    bb = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    return round(math.hypot(a, bb), 4)


def summary(facts: dict) -> dict[str, Any]:
    """The measured facts without the page text (for reports)."""
    return {k: v for k, v in facts.items() if k not in ("text",)}
