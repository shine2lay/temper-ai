#!/usr/bin/env python3
"""Design-owned homepage workflow v2: art-directed HTML/CSS, then editable Penpot.

v1 drew its pages from fixed templates, so it could only ever be tidy. v2 lets
models do what they do well, compose real web pages, and keeps Penpot as the
editable master by converting the rendered page (html_to_penpot.py).

Stages (one CLI, ``design_homepage_v2.py <stage> --workspace W``):

  brief           validate the brief, write homepage/BRIEF.md (+ copy assets)
  references      screenshot 8-12 acclaimed homepages, research only
  concepts_fixture  (model-free fixture) three hand-written concepts
  concepts_check  validate the art director's three concepts, fetch their
                  licensed fonts, render each at 1440 and 390, check they are
                  distinct, and build the contact sheet for the owner
  direction       OWNER DIRECTION gate decision -> prepare site/
  build_fixture   (fixture) the chosen concept becomes the page
  plan_round      round bookkeeping: build, or revise with a fix list
  revise_fixture  (fixture) a tiny scripted revision
  measure         capture + axe + measured facts for the critics, craft metrics
  review_fixture  (fixture) stand-in critic/merge/craft files
  combine         merge usability/accessibility findings with craft findings,
                  decide revise (at most two automatic revisions) or done
  next_round      the decision, for the workflow's loop
  convert         HTML -> editable Penpot (fonts, colours, typographies, components)
  verify          fresh reopen + fidelity bar; fails visibly
  handoff         packet with manifest
  final           OWNER FINAL gate decision (approve or request changes)

Every completed stage leaves a receipt in homepage/job.json, keyed by its
inputs. Re-entry with the same inputs reuses the receipt (no repeated paid or
Penpot work); changed inputs for a completed stage fail instead of silently
repeating. Gate decisions are saved JSON only; the fixture workflow labels its
decisions "fixture-test" and can never record owner approval.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import design_homepage_v1 as v1  # noqa: E402
import html_to_penpot as h2p  # noqa: E402

VERSION = 1
CONCEPT_IDS = ("A", "B", "C")
FIXTURE_SITE = HERE.parent / "testpages" / "html-fixtures"
FIXTURE_CONCEPTS = {"A": "atlas.html", "B": "pulse.html", "C": "harbor.html"}
# Overused faces that make AI pages look alike (handbook 2.11). A brand that
# really uses one may list it in brief.brand.fonts.
BANNED_FONTS = {"inter", "roboto", "open sans", "lato", "space grotesk", "arial", "helvetica",
                "helvetica neue", "system-ui", "-apple-system", "segoe ui", "times new roman",
                "georgia", "verdana", "montserrat", "poppins", "sans-serif", "serif", "monospace"}
FONT_HOSTS = {"fonts.googleapis.com", "fonts.gstatic.com", "raw.githubusercontent.com"}
LICENCE_URLS = (("ofl", "OFL.txt"), ("apache", "LICENSE.txt"), ("ufl", "UFL.txt"))
MAX_AUTO_REVISIONS = 2
MAX_OWNER_CHANGES = 2
# Distinctness bars, fixed before any run: a pair of concepts must differ on all.
EXTERNAL_TIMEOUT = 90  # seconds per outside page (load + scroll + screenshot)
DISTINCT = {"min_dominant_delta_e": 0.10, "max_signature_jaccard": 0.5, "min_thumbnail_diff": 0.06}
BROWSER = os.environ.get("DESIGN_BROWSER", "http://playwright-mcp:8931/mcp")
SERVE_HOST = os.environ.get("DESIGN_SERVE_HOST") or None
EXTERNAL = re.compile(r"""(?:(?:src|href|action|poster|data)\s*=\s*["']?\s*(?:https?:)?//)|(?:url\(\s*["']?\s*(?:https?:)?//)|@import""", re.I)
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
# Written to homepage/PAGE_RULES.md by the brief stage: the one rule sheet the art
# director, designer and reviser follow, so the page converts faithfully to Penpot.
PAGE_RULES = """# Page rules (HTML/CSS that becomes an editable Penpot file)

Files
- One page: index.html (+ optional styles.css) in its folder; everything local. Link the
  generated font sheet with <link rel="stylesheet" href="fonts/fonts.css"> and use exactly its
  family names and weights. Images only from images/ (supplied, sanitized) or drawn in code
  (inline SVG, CSS gradients, patterns). No external URLs, CDNs, web fonts from elsewhere,
  stock photos, AI-generated images, iframes or <script>.

Structure the converter reads
- Every top-level block is <header>, <section> or <footer> with data-section="Name"
  (Header, Hero, ...). Give meaningful elements data-name="...".
- Repeated items with the same structure (cards, stats, steps, buttons) carry
  data-component="Name"; each becomes a Penpot component, the copies its instances.
- Text styles may carry data-typography="Display" / "Body" ...
- Colours are CSS custom properties on :root (--dominant, --accent, --ink, --surface, ...);
  use var(--...) everywhere so they become shared Penpot colours.

What converts faithfully: solid, linear and radial gradient backgrounds; background images
(cover/contain); borders; border radius; drop shadows; images; inline SVG paths, shapes and
lines with solid fills and strokes; text in any loaded font, size, weight, line height,
letter spacing, case and colour; grid and flex layout.
Avoid (the converter can only approximate them, and lists each one): ::before/::after with
content (draw decoration as real elements or inline SVG), transforms on content (rotate,
skew), filters, backdrop-filter, blend modes, clip-path and masks, text shadows,
background-clip:text, inset shadows, SVG <text>/<use>/filters/gradient strokes, form controls.

Motion
- One orchestrated load animation (a staggered reveal) in CSS @keyframes, inside
  @media (prefers-reduced-motion: no-preference). Animate from an offset to the element's
  natural style, so the page is complete when motion is off (renders use reduced motion).

Quality bar
- Widths 390, 768 and 1440 without sideways scrolling (fluid grid, clamp()).
- WCAG 2.2 AA: text contrast 4.5:1 (3:1 large text), one h1, headings in order, landmarks,
  alt text, visible :focus-visible styles, targets at least 44x44 px, body text >= 16 px.
- Claims only from the brief's facts. A fictional product shows its disclosure. No invented
  customers, logos, quotes, ratings or numbers.
"""
FIXTURE_BRIEF = {
    "product": "Fixture Studio", "fictional": True, "fixture": True,
    "category": "converter fixture pages",
    "audience": "Design department engineers proving the v2 workflow at no model cost.",
    "purpose": "Exercise gates, measure, review loop, conversion and handoff with hand-written pages.",
    "cta": "Read the fixture", "disclosure": "Fixture pages for workflow tests; nothing here is a product.",
    "facts": ["Three hand-written pages stand in for model concepts.",
              "Fonts are vendored OFL files.", "Images are made in code."],
}


def now() -> str:
    return v1.now()


def save(path: Path, value: Any) -> None:
    v1.save(path, value)


def load(path: Path) -> Any:
    return v1.load(path)


def digest(value: Any) -> str:
    return v1.digest(value)


def tree_digest(root: Path) -> str:
    """Hash of every file under root (relative names + content)."""
    items = []
    for f in sorted(root.rglob("*")):
        if f.is_file():
            items.append([str(f.relative_to(root)), hashlib.sha256(f.read_bytes()).hexdigest()])
    return digest(items)


# ---------------------------------------------------------------- contracts


def brief_contract(value: Any) -> dict:
    if not isinstance(value, dict) or not isinstance(value.get("fictional"), bool):
        raise ValueError("brief needs an explicit fictional boolean")
    for key in ("product", "category", "audience", "purpose", "cta"):
        if not isinstance(value.get(key), str) or not value[key].strip():
            raise ValueError(f"brief needs {key}")
    facts = value.get("facts")
    if not isinstance(facts, list) or len(facts) < 3 or not all(isinstance(f, str) and f.strip() for f in facts):
        raise ValueError("brief needs at least three facts (the only source for claims on the page)")
    if value["fictional"] and not str(value.get("disclosure", "")).strip():
        raise ValueError("a fictional brief needs a disclosure line")
    if len(value["product"]) > 40 or len(value["cta"]) > 40:
        raise ValueError("product and cta must be short (<=40 characters)")
    for asset in value.get("assets", []):
        if not isinstance(asset, dict) or not asset.get("path") or not asset.get("alt"):
            raise ValueError("each asset needs path and alt")
        if asset.get("kind") not in ("screenshot", "logo", "photo"):
            raise ValueError("asset kind must be screenshot, logo or photo")
    brand = value.get("brand", {})
    if not isinstance(brand, dict):
        raise ValueError("brand must be an object")
    return value


def references_contract(value: Any, fixture: bool) -> list[dict]:
    if not isinstance(value, list):
        raise ValueError("references must be a JSON list")
    low, high = (2, 4) if fixture else (8, 12)
    if not low <= len(value) <= high:
        raise ValueError(f"give {low}-{high} references")
    seen = set()
    for ref in value:
        if not isinstance(ref, dict) or not str(ref.get("name", "")).strip() or not str(ref.get("why", "")).strip():
            raise ValueError("each reference needs name and why")
        if fixture:
            if ref.get("fixture") not in FIXTURE_CONCEPTS.values():
                raise ValueError("fixture references name a fixture page")
        else:
            url = urllib.parse.urlparse(str(ref.get("url", "")))
            if url.scheme != "https" or not url.hostname:
                raise ValueError("references need https URLs")
        key = ref.get("url") or ref.get("fixture")
        if key in seen:
            raise ValueError("duplicate reference")
        seen.add(key)
    return value


def font_slug(family: str) -> str:
    return re.sub(r"[^a-z0-9]", "", family.lower())


def oklab(hex_value: str) -> tuple[float, float, float]:
    rgb = [int(hex_value[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= .04045 else ((c + .055) / 1.055) ** 2.4 for c in rgb]
    r, g, b = lin
    lv = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    mv = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    sv = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    return (0.2104542553 * lv + 0.7936177850 * mv - 0.0040720468 * sv,
            1.9779984951 * lv - 2.4285922050 * mv + 0.4505937099 * sv,
            0.0259040371 * lv + 0.7827717662 * mv - 0.8086757660 * sv)


def delta_e(a: str, b: str) -> float:
    return round(math.dist(oklab(a), oklab(b)), 4)


def jaccard(a: list[str], b: list[str]) -> float:
    sa = {x.strip().lower() for x in a if x.strip()}
    sb = {x.strip().lower() for x in b if x.strip()}
    return round(len(sa & sb) / len(sa | sb), 3) if sa | sb else 1.0


def concept_contract(concept: Any, brand_fonts: set[str]) -> list[str]:
    """Problems with one concept (empty = fine)."""
    problems: list[str] = []
    if not isinstance(concept, dict):
        return ["concept is not an object"]
    cid = concept.get("id")
    where = f"concept {cid}"
    for key in ("name", "brief", "imagery", "signature_move", "motion"):
        if not isinstance(concept.get(key), str) or not concept[key].strip():
            problems.append(f"{where}: needs {key}")
    words = len(str(concept.get("brief", "")).split())
    if not 150 <= words <= 700:
        problems.append(f"{where}: design brief has {words} words; write about 300 (150-700)")
    sig = concept.get("layout_signature")
    if not isinstance(sig, list) or not 3 <= len(sig) <= 8 or not all(isinstance(s, str) and s.strip() for s in sig):
        problems.append(f"{where}: layout_signature needs 3-8 short keywords")
    fonts = concept.get("fonts")
    if not isinstance(fonts, dict):
        problems.append(f"{where}: needs fonts.display and fonts.text")
    else:
        for role in ("display", "text"):
            face = fonts.get(role)
            if not isinstance(face, dict) or not str(face.get("family", "")).strip():
                problems.append(f"{where}: fonts.{role}.family missing")
                continue
            weights = face.get("weights")
            if not isinstance(weights, list) or not weights or not all(isinstance(w, int) and 100 <= w <= 900 and w % 100 == 0 for w in weights) or len(weights) > 3:
                problems.append(f"{where}: fonts.{role}.weights needs 1-3 weights from 100-900")
            if face["family"].strip().lower() in BANNED_FONTS and face["family"].strip().lower() not in brand_fonts:
                problems.append(f"{where}: {face['family']} is on the overused list; choose a face with character")
    palette = concept.get("palette")
    keys = ("dominant", "accent", "ink", "surface", "on_dominant", "on_accent")
    if not isinstance(palette, dict) or any(not HEX.match(str(palette.get(k, ""))) for k in keys):
        problems.append(f"{where}: palette needs #RRGGBB for {', '.join(keys)}")
    else:
        for fg, bg in (("ink", "surface"), ("on_dominant", "dominant"), ("on_accent", "accent")):
            ratio = v1.contrast(palette[fg], palette[bg])
            if ratio < 4.5:
                problems.append(f"{where}: {fg} on {bg} contrast {ratio}:1 is below 4.5:1 (WCAG 1.4.3)")
    return problems


def html_problems(path: Path) -> list[str]:
    if not path.is_file():
        return [f"{path.name} missing"]
    text = path.read_text(errors="replace")
    problems = []
    if len(text) > 400_000:
        problems.append(f"{path.name} is over 400 KB")
    if EXTERNAL.search(text):
        problems.append(f"{path.parent.name}/{path.name} refers to an outside URL; keep every asset and link local (fonts/, images/, #anchors)")
    if re.search(r"<(iframe|object|embed)\b", text, re.I):
        problems.append(f"{path.name} uses iframe/object/embed")
    if re.search(r"<script\b", text, re.I):
        problems.append(f"{path.name} uses <script>; the page is HTML and CSS only")
    return problems


def safe_gate(raw: str) -> dict:
    return v1.safe_gate(raw)


# ---------------------------------------------------------------- fonts


def fetch(url: str, timeout: int = 60) -> bytes:
    host = urllib.parse.urlparse(url).hostname
    if host not in FONT_HOSTS:
        raise ValueError(f"refusing to fetch from {host}")
    req = urllib.request.Request(url, headers={"User-Agent": "curl/8"})
    with urllib.request.urlopen(req, timeout=timeout) as res:  # noqa: S310 - host allow-listed above
        return res.read()


def font_files(family: str, weights: list[int], italic: bool, dest: Path, issues: list[str]) -> list[dict]:
    """Download static TTFs from Google Fonts + licence. Reuses files already present."""
    slug = font_slug(family)
    folder = dest / slug
    folder.mkdir(parents=True, exist_ok=True)
    faces = []
    styles = ["normal", "italic"] if italic else ["normal"]
    for style in styles:
        for weight in weights:
            name = f"{re.sub(r'[^A-Za-z0-9]', '', family)}-{weight}{'italic' if style == 'italic' else ''}.ttf"
            target = folder / name
            if not target.exists():
                axis = f"ital,wght@{1 if style == 'italic' else 0},{weight}"
                url = "https://fonts.googleapis.com/css2?family=" + urllib.parse.quote_plus(family) + ":" + axis
                try:
                    css = fetch(url).decode()
                except (urllib.error.URLError, OSError, ValueError) as exc:
                    issues.append(f"{family} {weight} {style}: not on Google Fonts ({exc.__class__.__name__})")
                    continue
                blocks = re.findall(r"@font-face\s*{([^}]*)}", css)
                chosen = next((b for b in blocks if "unicode-range" not in b), blocks[-1] if blocks else "")
                m = re.search(r"url\((https://fonts\.gstatic\.com/[^)]+)\)", chosen)
                if not m:
                    issues.append(f"{family} {weight} {style}: no font file in Google Fonts response")
                    continue
                data = fetch(m.group(1))
                if data[:4] not in (b"\x00\x01\x00\x00", b"true", b"OTTO"):
                    issues.append(f"{family} {weight} {style}: not a TTF/OTF file")
                    continue
                target.write_bytes(data)
            faces.append({"family": family, "weight": weight, "style": style, "file": f"{slug}/{name}"})
    if faces and not any((folder / n).exists() for n in h2p.LICENCE_NAMES):
        for kind, fname in LICENCE_URLS:
            try:
                text = fetch(f"https://raw.githubusercontent.com/google/fonts/main/{kind}/{slug}/{fname}")
            except (urllib.error.URLError, OSError):
                continue
            (folder / fname).write_bytes(text)
            break
        else:
            issues.append(f"{family}: no licence file found; font not usable")
            return []
    return faces


def fonts_css(faces: list[dict]) -> str:
    rows = [f'@font-face {{ font-family: "{f["family"]}"; font-weight: {f["weight"]}; font-style: {f["style"]}; '
            f'font-display: block; src: url("{f["file"]}") format("truetype"); }}' for f in faces]
    return "/* Licensed fonts for this page; licence files sit beside each font. */\n" + "\n".join(rows) + "\n"


def copy_fonts(faces: list[dict], src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for slug in sorted({f["file"].split("/")[0] for f in faces}):
        shutil.copytree(src / slug, dest / slug, dirs_exist_ok=True)
    (dest / "fonts.css").write_text(fonts_css(faces))


# ---------------------------------------------------------------- browser work

RENDER_CODE = r"""async (page) => {
  const A = __ARGS__;
  const BLOCKED = /\b(403 forbidden|access denied|security verification|verify (that )?you are (a )?human|just a moment|attention required|are you a robot|captcha|request blocked|not available in your (country|region))\b/i;
  const out = [];
  for (const job of A.jobs) {
    await page.setViewportSize({width: job.width, height: job.height});
    await page.emulateMedia({reducedMotion: 'reduce', colorScheme: 'light'});
    let info = {name: job.name, ok: true};
    try {
      // Outside sites never reach network idle and some never fire load: wait for the DOM, then a fixed pause.
      await page.goto(job.url, {waitUntil: job.external ? 'domcontentloaded' : 'networkidle', timeout: job.external ? 30000 : 20000});
      if (job.freeze) await page.addStyleTag({content: A.css});
      if (job.external) {
        await page.waitForTimeout(2500);
        const total = Math.min(await page.evaluate(() => document.documentElement.scrollHeight), job.maxHeight);
        for (let y = 0; y < total; y += Math.round(job.height * 0.8)) {  // lazy images load only when scrolled to
          await page.evaluate((v) => window.scrollTo(0, v), y);
          await page.waitForTimeout(120);
        }
        await page.evaluate(() => window.scrollTo(0, 0));
      }
      await page.waitForTimeout(job.external ? 1500 : 200);
      info = await page.evaluate(async () => {
        // Bounded: a lazy image that never loads must not hang the job.
        const within = (p, ms) => Promise.race([p, new Promise((r) => setTimeout(r, ms))]);
        await within(document.fonts.ready, 8000);
        await within(Promise.all([...document.images].map((i) => i.complete ? null : new Promise((r) => { i.onload = r; i.onerror = r; }))), 8000);
        const loaded = [...document.fonts].filter((f) => f.status === 'loaded').map((f) => f.family.replace(/["']/g, ''));
        const text = (document.body ? document.body.innerText : '').replace(/\s+/g, ' ').trim();
        return {ok: true, title: document.title, scrollWidth: document.documentElement.scrollWidth,
                height: document.documentElement.scrollHeight, loadedFamilies: [...new Set(loaded)],
                textLength: text.length, head: (document.title + ' | ' + text.slice(0, 400))};
      });
      info.name = job.name;
      // A bot wall or error page is not a reference: fail it visibly instead of counting it as captured.
      if (job.external && (info.textLength < 300 || BLOCKED.test(info.head))) {
        throw new Error('blocked or empty page: ' + info.head.slice(0, 120));
      }
      const h = Math.min(info.height, job.maxHeight);
      const shot = await page.screenshot({fullPage: true, clip: {x: 0, y: 0, width: job.width, height: h}, animations: 'disabled', caret: 'hide', scale: 'css', timeout: 30000});
      const r = await page.request.put(A.base + '/__put/' + job.name + '.png', {data: shot, headers: {'content-type': 'application/octet-stream'}});
      if (!r.ok()) throw new Error('upload failed ' + r.status());
    } catch (e) {
      info = {name: job.name, ok: false, error: String(e).slice(0, 300)};
    }
    out.push(info);
  }
  return out;
}"""

THUMB_CODE = r"""async (page) => {
  const A = __ARGS__;
  await page.goto(A.base + '/__out/' + A.names[0] + '.png');
  return await page.evaluate(async (A) => {
    const load = (u) => new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = () => rej(new Error('load ' + u)); i.src = u; });
    const pix = [];
    for (const n of A.names) {
      const img = await load(A.base + '/__out/' + n + '.png');
      const c = document.createElement('canvas'); c.width = 64; c.height = 40;
      const g = c.getContext('2d');
      const h = Math.min(img.height, img.width * 900 / 1440);
      g.drawImage(img, 0, 0, img.width, h, 0, 0, 64, 40);
      pix.push(g.getImageData(0, 0, 64, 40).data);
    }
    const res = {};
    for (let i = 0; i < pix.length; i++) for (let j = i + 1; j < pix.length; j++) {
      let s = 0;
      for (let k = 0; k < pix[i].length; k += 4) s += Math.abs(pix[i][k] - pix[j][k]) + Math.abs(pix[i][k + 1] - pix[j][k + 1]) + Math.abs(pix[i][k + 2] - pix[j][k + 2]);
      res[A.names[i] + '|' + A.names[j]] = Math.round(s / (pix[i].length / 4 * 3 * 255) * 10000) / 10000;
    }
    return res;
  }, A);
}"""

CRAFT_CODE = r"""async (page) => {
  const A = __ARGS__;
  const out = {};
  for (const w of A.widths) {
    await page.setViewportSize({width: w, height: w === 390 ? 844 : 900});
    await page.goto(A.url, {waitUntil: 'networkidle'});
    out[w] = await page.evaluate(async (w) => {
      await document.fonts.ready;
      const vis = (el) => { const r = el.getBoundingClientRect(); const cs = getComputedStyle(el); return r.width > 0 && r.height > 0 && cs.visibility !== 'hidden' && cs.display !== 'none' && parseFloat(cs.opacity) > 0; };
      const sizes = {}, families = {}, colors = {}, weights = {};
      const tw = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
      let node;
      while ((node = tw.nextNode())) {
        const t = node.textContent.replace(/\s+/g, ' ').trim();
        if (!t || !node.parentElement || !vis(node.parentElement)) continue;
        const cs = getComputedStyle(node.parentElement);
        const size = Math.round(parseFloat(cs.fontSize));
        const fam = cs.fontFamily.split(',')[0].replace(/["']/g, '').trim();
        sizes[size] = (sizes[size] || 0) + t.length;
        families[fam] = (families[fam] || 0) + t.length;
        colors[cs.color] = (colors[cs.color] || 0) + t.length;
        weights[cs.fontWeight] = (weights[cs.fontWeight] || 0) + t.length;
      }
      const bySize = Object.entries(sizes).map(([s, n]) => [+s, n]).sort((a, b) => b[1] - a[1]);
      const body = bySize.length ? bySize[0][0] : 16;
      const display = bySize.length ? Math.max(...bySize.map((x) => x[0])) : 16;
      const bgs = new Set(); let gradients = 0, bgImages = 0;
      const spacing = []; let animated = 0;
      for (const el of document.querySelectorAll('body *')) {
        if (!vis(el)) continue;
        const cs = getComputedStyle(el);
        if (cs.backgroundColor !== 'rgba(0, 0, 0, 0)' && cs.backgroundColor !== 'transparent') bgs.add(cs.backgroundColor);
        if (cs.backgroundImage.includes('gradient')) gradients++;
        if (cs.backgroundImage.includes('url(')) bgImages++;
        if (cs.animationName !== 'none' || (cs.transitionDuration && cs.transitionDuration !== '0s')) animated++;
        for (const p of ['paddingTop', 'paddingBottom', 'paddingLeft', 'marginTop', 'marginBottom', 'rowGap', 'columnGap']) {
          const v = parseFloat(cs[p]);
          if (v > 0) spacing.push(Math.round(v));
        }
      }
      let sections = [...document.querySelectorAll('[data-section]')];
      if (!sections.length) sections = [...document.querySelectorAll('body > header, body > main > section, body > main > *, body > section, body > footer')];
      const sig = sections.filter(vis).map((s) => {
        const cs = getComputedStyle(s);
        const inner = s.querySelector('div, ul, ol') || s;
        const ics = getComputedStyle(inner);
        const cols = ics.display.includes('grid') ? ics.gridTemplateColumns.split(' ').filter(Boolean).length : (ics.display.includes('flex') ? 'flex-' + ics.flexDirection : 'flow');
        const bg = cs.backgroundImage !== 'none' ? (cs.backgroundImage.includes('url(') ? 'image' : 'gradient') : cs.backgroundColor;
        const h = s.getBoundingClientRect().height;
        const head = s.querySelector('h1, h2, h3');
        return {name: s.dataset.section || s.dataset.name || s.tagName.toLowerCase(), height: Math.round(h),
                signature: [cols, bg, head ? getComputedStyle(head).textAlign : '-', h > 700 ? 'tall' : h > 350 ? 'mid' : 'short'].join(' | ')};
      });
      const distinct = new Set(sig.map((s) => s.signature)).size;
      let repeats = 0;
      for (let i = 1; i < sig.length; i++) if (sig[i].signature === sig[i - 1].signature) repeats++;
      const onScale = spacing.length ? spacing.filter((v) => v % 4 === 0).length / spacing.length : 1;
      const loaded = [...document.fonts].filter((f) => f.status === 'loaded').map((f) => f.family.replace(/["']/g, ''));
      const h1 = document.querySelector('h1');
      return {
        width: w, body_px: body, display_px: display, scale_ratio: Math.round(display / body * 100) / 100,
        text_sizes: bySize.length, families: Object.keys(families), loaded_families: [...new Set(loaded)],
        unloaded_families: Object.keys(families).filter((f) => !loaded.includes(f)),
        weights: Object.keys(weights).length, text_colors: Object.keys(colors).length, background_colors: bgs.size,
        gradients, background_images: bgImages, images: document.images.length,
        svgs: document.querySelectorAll('svg').length, animated_elements: animated,
        sections: sig, section_count: sig.length, distinct_section_layouts: distinct, consecutive_repeats: repeats,
        spacing_values: new Set(spacing).size, spacing_on_4px: Math.round(onScale * 100) / 100,
        h1_px: h1 ? Math.round(parseFloat(getComputedStyle(h1).fontSize)) : null,
        hero_height: sig.length ? sig[0].height : null,
        page_height: document.documentElement.scrollHeight, overflow_x: document.documentElement.scrollWidth > w,
      };
    }, w);
  }
  return out;
}"""


def browser_jobs(root: Path, out: Path, jobs: list[dict]) -> list[dict]:
    """Serve root, run render jobs (screenshots land in out)."""
    out.mkdir(parents=True, exist_ok=True)
    host = SERVE_HOST or urllib.parse.urlparse(BROWSER).hostname or "playwright-mcp"
    base, srv = h2p.serve(root, out, host)
    try:
        for job in jobs:
            if not job.get("external"):
                job["url"] = base + "/" + job["path"].lstrip("/")
        local = [j for j in jobs if not j.get("external")]
        results = []
        if local:
            code = RENDER_CODE.replace("__ARGS__", json.dumps({"base": base, "jobs": local, "css": h2p.FREEZE_CSS}))
            results += h2p.browser_run(BROWSER, [code])[0]
        # Outside sites: one browser session per site with a time limit, so one bad site cannot stall the rest.
        groups: dict[str, list[dict]] = {}
        for job in jobs:
            if job.get("external"):
                groups.setdefault(job["url"], []).append(job)
        for group in groups.values():
            code = RENDER_CODE.replace("__ARGS__", json.dumps({"base": base, "jobs": group, "css": h2p.FREEZE_CSS}))
            try:
                results += h2p.browser_run(BROWSER, [code], timeout=EXTERNAL_TIMEOUT * len(group))[0]
            except Exception as exc:  # noqa: BLE001 - a failed site is recorded, never fatal on its own
                results += [{"name": j["name"], "ok": False, "error": f"{exc.__class__.__name__}: {str(exc)[:200]}"} for j in group]
        return results
    finally:
        srv.shutdown()


def thumbnail_diffs(out: Path, names: list[str]) -> dict[str, float]:
    host = SERVE_HOST or urllib.parse.urlparse(BROWSER).hostname or "playwright-mcp"
    base, srv = h2p.serve(out, out, host)
    try:
        return h2p.browser_run(BROWSER, [THUMB_CODE.replace("__ARGS__", json.dumps({"base": base, "names": names}))])[0]
    finally:
        srv.shutdown()


def craft_metrics(site: Path) -> dict:
    host = SERVE_HOST or urllib.parse.urlparse(BROWSER).hostname or "playwright-mcp"
    base, srv = h2p.serve(site, site, host)
    try:
        code = CRAFT_CODE.replace("__ARGS__", json.dumps({"url": base + "/index.html", "widths": [1440, 390]}))
        return h2p.browser_run(BROWSER, [code])[0]
    finally:
        srv.shutdown()


# ---------------------------------------------------------------- the job


class Job:
    def __init__(self, workspace: str, fixture: bool):
        self.root = Path(workspace).resolve()
        self.fixture = fixture
        self.packet = self.root / "homepage"
        self.packet.mkdir(parents=True, exist_ok=True)
        self.state_path = self.packet / "job.json"
        self.state = load(self.state_path) if self.state_path.exists() else {
            "version": VERSION, "workflow": "design_homepage_v2" + ("_fixture" if fixture else ""),
            "created_at": now(), "stages": {}, "round": 0, "revisions": 0, "owner_changes": 0,
            "decision_seq": 0, "planned_seq": -1, "owner_direction_approved": False,
            "owner_final_approved": False}
        if self.state.get("workflow", "").endswith("_fixture") != fixture:
            raise ValueError("workspace belongs to the other workflow (fixture vs real); use a fresh workspace")

    def commit(self) -> None:
        save(self.state_path, self.state)

    def receipt(self, stage: str, fingerprint: str, output: dict) -> dict:
        self.state["stages"][stage] = {"fingerprint": fingerprint, "completed_at": now(), "output": output}
        self.commit()
        return output

    def cached(self, stage: str, fingerprint: str) -> dict | None:
        receipt = self.state["stages"].get(stage)
        if receipt:
            if receipt["fingerprint"] != fingerprint:
                raise ValueError(f"saved {stage} inputs changed; use a fresh workspace rather than silently repeating work")
            return {**receipt["output"], "reused": True}
        return None

    @property
    def concepts_dir(self) -> Path:
        return self.packet / "concepts"

    @property
    def site(self) -> Path:
        return self.packet / "site"

    # -- brief and research

    def brief(self, raw: str) -> dict:
        value = brief_contract(json.loads(raw) if raw.strip() else dict(FIXTURE_BRIEF) if self.fixture else None)
        if self.fixture and not value.get("fixture"):
            raise ValueError("the fixture workflow refuses real briefs")
        if not self.fixture and value.get("fixture"):
            raise ValueError("the real workflow refuses fixture briefs")
        fp = digest(value)
        cached = self.cached("brief", fp)
        if cached:
            return cached
        save(self.packet / "brief.json", value)
        assets = []
        for asset in value.get("assets", []):
            src = Path(asset["path"])
            if not src.is_absolute():
                src = self.root / src
            if not src.is_file() or h2p.image_kind(src.read_bytes()) is None:
                raise ValueError(f"asset {asset['path']} missing or not an image")
            dest = self.packet / "assets" / src.name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest)
            assets.append({**asset, "file": f"assets/{src.name}"})
        lines = [f"# Homepage brief — {value['product']}", "",
                 f"Category: {value['category']}", f"Audience: {value['audience']}",
                 f"Homepage job: {value['purpose']}", f"Primary action: {value['cta']}",
                 f"Fictional: {value['fictional']}" + (f" — disclosure: {value['disclosure']}" if value['fictional'] else ""),
                 "", "## Facts (the only source for claims on the page)"]
        lines += [f"- {f}" for f in value["facts"]]
        for key in ("headline", "voice", "sections", "brand", "avoid"):
            if value.get(key):
                lines += ["", f"## {key.title()}", json.dumps(value[key], ensure_ascii=False, indent=1)]
        if assets:
            lines += ["", "## Images supplied (sanitized, usable on the page)"]
            lines += [f"- {a['file']} ({a['kind']}): {a['alt']}" for a in assets]
        lines += ["", "## Constraints",
                  "- Widths 390, 768, 1440. WCAG 2.2 AA. Body text >= 16 px.",
                  "- All assets local: licensed fonts fetched by the workflow, supplied images, code-made SVG/CSS art.",
                  "- No AI-generated images, no stock photos, no invented customers, numbers, logos or quotes.",
                  "- No signup, payment, analytics or tracking. Penpot is the editable master after conversion."]
        (self.packet / "BRIEF.md").write_text("\n".join(lines) + "\n")
        (self.packet / "PAGE_RULES.md").write_text(PAGE_RULES)
        self.state["assets"] = assets
        return self.receipt("brief", fp, {"status": "completed", "brief_path": "homepage/BRIEF.md", "assets": len(assets)})

    def references(self, raw: str) -> dict:
        if self.fixture and not raw.strip():
            raw = json.dumps([{"name": f"Fixture {k}", "fixture": v, "why": "stand-in reference (fixture)"}
                              for k, v in FIXTURE_CONCEPTS.items()])
        refs = references_contract(json.loads(raw or "[]"), self.fixture)
        fp = digest(refs)
        cached = self.cached("references", fp)
        if cached:
            return cached
        out = self.packet / "references"
        if out.exists():
            shutil.rmtree(out)
        jobs = []
        for i, ref in enumerate(refs, 1):
            stem = f"ref-{i:02d}"
            for width, height in ((1440, 900), (390, 844)):
                job = {"name": f"{stem}-{width}", "width": width, "height": height,
                       "maxHeight": 4200 if width == 1440 else 3400, "freeze": False}
                if self.fixture:
                    job["path"] = ref["fixture"]
                else:
                    job.update({"external": True, "url": ref["url"]})
                jobs.append(job)
        root = FIXTURE_SITE if self.fixture else self.packet
        results = browser_jobs(root, out, jobs)
        captured = []
        for i, ref in enumerate(refs, 1):
            stem = f"ref-{i:02d}"
            got = {r["name"]: r for r in results if r["name"].startswith(stem)}
            ok = all(got.get(f"{stem}-{w}", {}).get("ok") for w in (1440, 390))
            captured.append({**ref, "id": stem, "ok": ok, "shots": [f"references/{stem}-1440.png", f"references/{stem}-390.png"] if ok else [],
                             "error": None if ok else "; ".join(str(r.get("error")) for r in got.values() if not r.get("ok"))[:300]})
        good = [c for c in captured if c["ok"]]
        need = 2 if self.fixture else 8
        save(out / "references.json", captured)
        lines = ["# References — research only", "",
                 "Acclaimed homepages in this category, captured to study what makes them memorable.",
                 "Never copy or trace their layouts, illustrations, copy or assets.", ""]
        for c in captured:
            lines.append(f"- {c['id']} {c['name']}: {c['why']}" + (f" — shots {', '.join(c['shots'])}" if c["ok"] else f" — NOT CAPTURED: {c['error']}"))
        (out / "REFERENCES.md").write_text("\n".join(lines) + "\n")
        if len(good) < need:
            raise ValueError(f"only {len(good)} of {len(refs)} references captured; need {need} (see homepage/references/REFERENCES.md)")
        return self.receipt("references", fp, {"status": "completed", "captured": len(good), "failed": len(refs) - len(good),
                                               "references_path": "homepage/references/REFERENCES.md"})

    # -- concepts

    def concepts_fixture(self) -> dict:
        fp = digest({"fixture": FIXTURE_CONCEPTS, "site": tree_digest(FIXTURE_SITE)})
        cached = self.cached("concepts_fixture", fp)
        if cached:
            return cached
        specs = {
            "A": ("Ridgeline Atlas", {"display": {"family": "Fraunces", "weights": [600, 800]}, "text": {"family": "Instrument Sans", "weights": [400, 600]}},
                  {"dominant": "#B8482A", "accent": "#3E5B4A", "ink": "#1F1A17", "surface": "#FBF6EE", "on_dominant": "#FFFFFF", "on_accent": "#FFFFFF"},
                  ["gradient-hero", "image-right", "three-card-grid", "serif-display"]),
            "B": ("Pulse Board", {"display": {"family": "Bricolage Grotesque", "weights": [700, 800]}, "text": {"family": "Atkinson Hyperlegible", "weights": [400, 700]}},
                  {"dominant": "#5B4BDB", "accent": "#FF5C48", "ink": "#18163A", "surface": "#FFFFFF", "on_dominant": "#FFFFFF", "on_accent": "#18163A"},
                  ["radial-glow", "dashboard-screenshot", "pricing-table", "chart-svg"]),
            "C": ("Harbor Night", {"display": {"family": "DM Serif Display", "weights": [400]}, "text": {"family": "Figtree", "weights": [400, 600, 800]}},
                  {"dominant": "#0E1626", "accent": "#E2AA5A", "ink": "#F4EFE6", "surface": "#0E1626", "on_dominant": "#F4EFE6", "on_accent": "#0E1626"},
                  ["photo-overlay-hero", "stat-strip", "wave-divider", "menu-list"]),
        }
        concepts = []
        for cid, page in FIXTURE_CONCEPTS.items():
            name, fonts, palette, sig = specs[cid]
            dest = self.concepts_dir / cid
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(FIXTURE_SITE, dest, ignore=shutil.ignore_patterns("*.html"))
            shutil.copyfile(FIXTURE_SITE / page, dest / "index.html")
            words = ("Fixture concept " + name + " stands in for an art director's design brief. ") * 20
            concepts.append({"id": cid, "name": name, "brief": words.strip(), "fonts": fonts, "palette": palette,
                             "imagery": "code-made images and inline SVG", "signature_move": sig[0],
                             "motion": "none (fixture)", "layout_signature": sig, "page": f"homepage/concepts/{cid}/index.html"})
        save(self.concepts_dir / "concepts.json", {"concepts": concepts, "fixture": True})
        return self.receipt("concepts_fixture", fp, {"status": "completed", "concepts": len(concepts)})

    def concepts_check(self, phase: str) -> dict:
        if phase not in ("draft", "final"):
            raise ValueError("phase is draft or final")
        cdir = self.concepts_dir
        spec_path = cdir / "concepts.json"
        if not spec_path.exists():
            raise ValueError("homepage/concepts/concepts.json missing: the art director wrote nothing")
        spec = load(spec_path)
        fp = digest({"phase": phase, "concepts": tree_digest(cdir / "A") + tree_digest(cdir / "B") + tree_digest(cdir / "C")
                     if all((cdir / c).exists() for c in CONCEPT_IDS) else "", "spec": spec})
        attempt = self.state.setdefault("concept_checks", {}).get(phase, 0)
        key = f"concepts_check-{phase}-{attempt}"
        prior = self.state["stages"].get(key)
        if prior and prior["fingerprint"] == fp:
            return {**prior["output"], "reused": True}
        if prior:  # new art-director work since the last check: a new attempt
            attempt += 1
            key = f"concepts_check-{phase}-{attempt}"
        self.state["concept_checks"][phase] = attempt
        brief = load(self.packet / "brief.json")
        brand_fonts = {f.lower() for f in brief.get("brand", {}).get("fonts", [])}
        concepts = spec.get("concepts") if isinstance(spec, dict) else None
        problems: list[str] = []
        if not isinstance(concepts, list) or sorted(str(c.get("id")) for c in concepts if isinstance(c, dict)) != list(CONCEPT_IDS) or len(concepts) != 3:
            problems.append("concepts.json needs exactly three concept objects with ids A, B and C")
            check = {"phase": phase, "attempt": attempt, "checked_at": now(), "verdict": "retry", "problems": problems}
            save(cdir / "check.json", check)
            save(cdir / f"check-{phase}-{attempt}.json", check)
            return self.receipt(key, fp, {"status": "completed", "phase": phase, "attempt": attempt, "verdict": "retry",
                                          "problems": len(problems), "check_path": "homepage/concepts/check.json"})
        for c in concepts:
            problems += concept_contract(c, brand_fonts)
            problems += html_problems(cdir / c["id"] / "index.html")
        font_issues: list[str] = []
        faces_by_concept: dict[str, list[dict]] = {}
        for c in concepts:
            faces: list[dict] = []
            fonts = c.get("fonts") or {}
            if spec.get("fixture"):
                faces_by_concept[c["id"]] = []
                continue
            for role in ("display", "text"):
                face = fonts.get(role) or {}
                if face.get("family") and isinstance(face.get("weights"), list):
                    got = font_files(face["family"], [w for w in face["weights"] if isinstance(w, int)], bool(face.get("italic")),
                                     self.packet / "fonts", font_issues)
                    if not got:
                        problems.append(f"concept {c['id']}: font {face['family']} unavailable (needs a Google Fonts family with a licence)")
                    faces += got
            faces_by_concept[c["id"]] = faces
            copy_fonts(faces, self.packet / "fonts", cdir / c["id"] / "fonts")
        jobs = []
        for c in concepts:
            for width, height in ((1440, 900), (390, 844)):
                jobs.append({"name": f"{c['id'].lower()}-{width}", "path": f"{c['id']}/index.html", "width": width, "height": height,
                             "maxHeight": 3600 if width == 1440 else 3200, "freeze": True})
        shots = cdir / "shots"
        results = {r["name"]: r for r in browser_jobs(cdir, shots, jobs)}
        renders = {}
        for c in concepts:
            for width in (1440, 390):
                r = results.get(f"{c['id'].lower()}-{width}", {})
                renders[f"{c['id']}-{width}"] = r
                if not r.get("ok"):
                    problems.append(f"concept {c['id']} did not render at {width}: {r.get('error')}")
                    continue
                if r.get("scrollWidth", 0) > width + 1:
                    problems.append(f"concept {c['id']} scrolls sideways at {width} ({r['scrollWidth']} px)")
                loaded = {f.lower() for f in r.get("loadedFamilies", [])}
                for role in ("display", "text"):
                    fam = str((c.get("fonts") or {}).get(role, {}).get("family", "")).lower()
                    if fam and fam not in loaded:
                        problems.append(f"concept {c['id']} at {width}: {role} font {fam} never loaded (link fonts/fonts.css and use the family name)")
        thumbs = thumbnail_diffs(shots, [f"{cid.lower()}-1440" for cid in CONCEPT_IDS]) if all(renders.get(f"{cid}-1440", {}).get("ok") for cid in CONCEPT_IDS) else {}
        pairs = []
        by_id = {c["id"]: c for c in concepts}
        for i, a in enumerate(CONCEPT_IDS):
            for b in CONCEPT_IDS[i + 1:]:
                ca, cb = by_id[a], by_id[b]
                fa, fb = ca.get("fonts") or {}, cb.get("fonts") or {}
                pa, pb = ca.get("palette") or {}, cb.get("palette") or {}
                pair = {"pair": f"{a}-{b}",
                        "same_display_font": str(fa.get("display", {}).get("family", "")).lower() == str(fb.get("display", {}).get("family", "")).lower(),
                        "same_type_pairing": [str(fa.get(r, {}).get("family", "")).lower() for r in ("display", "text")] == [str(fb.get(r, {}).get("family", "")).lower() for r in ("display", "text")],
                        "dominant_delta_e": delta_e(pa["dominant"], pb["dominant"]) if HEX.match(str(pa.get("dominant", ""))) and HEX.match(str(pb.get("dominant", ""))) else None,
                        "signature_jaccard": jaccard(ca.get("layout_signature") or [], cb.get("layout_signature") or []),
                        "thumbnail_diff": thumbs.get(f"{a.lower()}-1440|{b.lower()}-1440")}
                why = []
                if pair["same_display_font"] or pair["same_type_pairing"]:
                    why.append("same display face or type pairing")
                if pair["dominant_delta_e"] is not None and pair["dominant_delta_e"] < DISTINCT["min_dominant_delta_e"]:
                    why.append(f"dominant colours too close (OKLab ΔE {pair['dominant_delta_e']})")
                if pair["signature_jaccard"] > DISTINCT["max_signature_jaccard"]:
                    why.append(f"layout signatures overlap ({pair['signature_jaccard']})")
                if pair["thumbnail_diff"] is not None and pair["thumbnail_diff"] < DISTINCT["min_thumbnail_diff"]:
                    why.append(f"first screens look alike (difference {pair['thumbnail_diff']})")
                pair["near_duplicate"] = bool(why)
                pair["why"] = why
                if why:
                    problems.append(f"concepts {a} and {b} are near-duplicates: " + "; ".join(why))
                pairs.append(pair)
        sheet = self.contact_sheet(concepts)
        verdict = "ok" if not problems else "retry"
        check = {"phase": phase, "attempt": attempt, "checked_at": now(), "verdict": verdict, "problems": problems,
                 "font_issues": font_issues, "distinctness_bar": DISTINCT, "pairs": pairs, "renders": renders,
                 "fonts": {cid: [f"{f['family']} {f['weight']} {f['style']}" for f in faces] for cid, faces in faces_by_concept.items()},
                 "contact_sheet": sheet}
        save(cdir / "check.json", check)
        save(cdir / f"check-{phase}-{attempt}.json", check)
        output = {"status": "completed", "phase": phase, "attempt": attempt, "verdict": verdict, "problems": len(problems),
                  "contact_sheet": sheet, "check_path": "homepage/concepts/check.json"}
        if verdict == "ok":
            output["questions"] = [{"id": "direction", "question": "Choose one concept (A, B or C) and add notes; this is the owner's taste decision",
                                    "options": [f"{c['id']}: {c['name']}" for c in concepts]}]
        return self.receipt(key, fp, output)

    def concepts_next(self) -> dict:
        """Loop control after the final concept check: report its verdict, change nothing.

        A separate node so that a failing check (browser down) fails the run instead of
        sending the art director round again (temper loops on a failed node too)."""
        path = self.concepts_dir / "check.json"
        if not path.exists():
            raise ValueError("no concept check to act on")
        check = load(path)
        if check.get("phase") != "final":
            raise ValueError("the last concept check was not the final one")
        return {"status": "completed", "verdict": check["verdict"], "attempt": check.get("attempt"),
                "problems": len(check.get("problems", []))}

    def contact_sheet(self, concepts: list[dict]) -> str:
        cdir = self.concepts_dir
        cols = []
        for c in concepts:
            pal = c.get("palette") or {}
            sw = "".join(f'<span style="background:{pal[k]}" title="{k} {pal[k]}"></span>' for k in ("dominant", "accent", "ink", "surface") if HEX.match(str(pal.get(k, ""))))
            fonts = c.get("fonts") or {}
            pair = " + ".join(str(fonts.get(r, {}).get("family", "?")) for r in ("display", "text"))
            cols.append(f'<section><h2>{c["id"]} — {_esc(c.get("name", ""))}</h2><p class="m">{_esc(pair)}</p><p class="sw">{sw}</p>'
                        f'<p>{_esc(c.get("signature_move", ""))}</p><div class="shots"><img src="shots/{c["id"].lower()}-1440.png" class="d">'
                        f'<img src="shots/{c["id"].lower()}-390.png" class="p"></div></section>')
        html = ('<!doctype html><meta charset="utf-8"><title>Concepts</title><style>body{margin:0;padding:32px;background:#e9e7e2;'
                'font:16px/1.4 system-ui;color:#222}main{display:grid;grid-template-columns:repeat(3,1fr);gap:28px}h2{font-size:22px;margin:0 0 4px}'
                '.m{color:#555;margin:0 0 6px}.sw span{display:inline-block;width:28px;height:28px;border-radius:4px;margin-right:4px;border:1px solid #0002}'
                '.shots{display:grid;grid-template-columns:3fr 1fr;gap:10px;align-items:start}img{width:100%;border:1px solid #0003}</style>'
                '<h1 style="margin:0 0 20px">Three directions — choose one</h1><main>' + "".join(cols) + "</main>")
        (cdir / "sheet.html").write_text(html)
        try:
            browser_jobs(cdir, cdir / "shots", [{"name": "contact-sheet", "path": "sheet.html", "width": 1800, "height": 1000, "maxHeight": 6000, "freeze": True}])
        except Exception as exc:  # noqa: BLE001 - the sheet is a convenience; the shots stay
            return f"homepage/concepts/sheet.html (png failed: {exc.__class__.__name__})"
        return "homepage/concepts/shots/contact-sheet.png"

    # -- owner direction

    def direction(self, raw: str) -> dict:
        decision = safe_gate(raw)
        check = load(self.concepts_dir / "check.json") if (self.concepts_dir / "check.json").exists() else {}
        if check.get("verdict") != "ok":
            raise ValueError("concepts have not passed the final check; no direction can be recorded")
        if decision.get("concept") not in CONCEPT_IDS:
            raise ValueError("direction needs concept A, B or C")
        want = "fixture-test" if self.fixture else "owner-direction"
        if decision.get("approval") != want:
            raise ValueError(f"this workflow's direction gate needs approval {want!r}")
        fp = digest(decision)
        cached = self.cached("direction", fp)
        if cached:
            return cached
        spec = load(self.concepts_dir / "concepts.json")
        chosen = next(c for c in spec["concepts"] if c["id"] == decision["concept"])
        site = self.site
        if site.exists():
            raise ValueError("site/ already exists before a direction was recorded; use a fresh workspace")
        site.mkdir(parents=True)
        cdir = self.concepts_dir / chosen["id"]
        if (cdir / "fonts").exists():
            shutil.copytree(cdir / "fonts", site / "fonts")
        if (self.packet / "assets").exists():
            shutil.copytree(self.packet / "assets", site / "images")
        save(self.packet / "direction.json", {**decision, "concept_name": chosen["name"], "saved_at": now(),
                                              "owner_approved": not self.fixture})
        self.state["direction"] = {**decision, "concept_name": chosen["name"]}
        self.state["owner_direction_approved"] = not self.fixture
        return self.receipt("direction", fp, {"status": "completed", "concept": chosen["id"], "concept_name": chosen["name"],
                                              "owner_direction_approved": not self.fixture})

    def build_fixture(self) -> dict:
        cid = self.state["direction"]["concept"]
        fp = digest({"concept": cid})
        cached = self.cached("build_fixture", fp)
        if cached:
            return cached
        shutil.copytree(self.concepts_dir / cid, self.site, dirs_exist_ok=True)
        return self.receipt("build_fixture", fp, {"status": "completed", "site": "homepage/site/index.html"})

    # -- review rounds

    def plan_round(self) -> dict:
        seq = self.state["decision_seq"]
        if self.state["planned_seq"] == seq and self.state.get("plan"):
            return {**self.state["plan"], "reused": True}
        if not (self.site / "index.html").exists():
            raise ValueError("homepage/site/index.html missing: the designer wrote nothing")
        if self.state["round"] == 0:
            plan = {"status": "completed", "round": 1, "action": "build"}
        else:
            if self.state.get("verdict") not in ("revise", "owner_changes"):
                raise ValueError("no revision was requested; refusing to start another round")
            number = self.state["round"] + 1
            fixes = self.state.get("fix_list", [])
            rdir = self.packet / "rounds" / f"r{number:02d}"
            save(rdir / "fix-list.json", {"round": number, "reason": self.state["verdict"], "fixes": fixes})
            (self.root / "review").mkdir(exist_ok=True)
            save(self.root / "review" / "fix-list.json", {"round": number, "reason": self.state["verdict"], "fixes": fixes})
            if self.state["verdict"] == "revise":
                self.state["revisions"] += 1
            else:
                self.state["owner_changes"] += 1
            plan = {"status": "completed", "round": number, "action": "revise", "fixes": len(fixes),
                    "fix_list": "review/fix-list.json"}
        self.state["round"] = plan["round"]
        self.state["planned_seq"] = seq
        self.state["plan"] = plan
        self.commit()
        return plan

    def revise_fixture(self) -> dict:
        number = self.state["round"]
        fp = digest({"round": number})
        cached = self.cached(f"revise_fixture-{number}", fp)
        if cached:
            return cached
        index = self.site / "index.html"
        text = index.read_text()
        text = text.replace("</title>", f" (fixture revision r{number:02d})</title>", 1)
        index.write_text(text)
        return self.receipt(f"revise_fixture-{number}", fp, {"status": "completed", "round": number, "changed": "title"})

    def measure(self) -> dict:
        number = self.state["round"]
        problems = html_problems(self.site / "index.html")
        for f in self.site.rglob("*.html"):
            problems += [p for p in html_problems(f) if "missing" not in p]
        if problems:
            raise ValueError("site breaks the page contract: " + "; ".join(sorted(set(problems))))
        fp = digest({"round": number, "site": tree_digest(self.site)})
        cached = self.cached(f"measure-{number}", fp)
        review = self.root / "review"
        if cached:
            if not (review / "facts.md").exists():
                raise ValueError("saved measurement artifacts missing; refusing a silent repeat")
            return cached
        if review.exists():
            keep = review / "fix-list.json"
            fix = keep.read_text() if keep.exists() else None
            shutil.rmtree(review)
            review.mkdir()
            if fix:
                keep.write_text(fix)
        cmd = [sys.executable, str(HERE / "design_capture.py"), "--out", str(review), "--site", str(self.site),
               "--pages", "index.html", "--viewports", "desktop,mobile", "--browser", BROWSER]
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
        if done.returncode != 0:
            raise ValueError("capture failed: " + (done.stderr or done.stdout)[-600:])
        for sub in ("critic", "craft"):
            (review / sub).mkdir(exist_ok=True)
        brief = load(self.packet / "brief.json")
        direction = self.state.get("direction", {})
        (review / "brief.md").write_text(
            f"# Homepage review — {brief['product']} (round {number})\n\n"
            f"Who it is for: {brief['audience']}\nHomepage job: {brief['purpose']}\nPrimary action: {brief['cta']}\n"
            + (f"Fictional study: {brief['disclosure']}\n" if brief["fictional"] else "")
            + "\nPage: index.html (the homepage), desktop and mobile. A static design built in HTML/CSS; links to other pages"
            " are not part of this review. Report problems only.\n")
        metrics = craft_metrics(self.site)
        rdir = self.packet / "rounds" / f"r{number:02d}"
        save(rdir / "craft-metrics.json", metrics)
        save(review / "craft-metrics.json", metrics)
        spec = load(self.concepts_dir / "concepts.json")
        chosen = next((c for c in spec["concepts"] if c["id"] == direction.get("concept")), {})
        lines = [f"# Measured craft facts — round {number}", "",
                 "Numbers from the rendered page (computed styles). They are facts; judge what they mean.", ""]
        for w, m in metrics.items():
            lines += [f"## {w} px", f"- body text {m['body_px']} px, largest text {m['display_px']} px, scale ratio {m['scale_ratio']}x (aim >= 3x)",
                      f"- text sizes {m['text_sizes']}, weights {m['weights']}, families {', '.join(m['families'])}; not loaded: {', '.join(m['unloaded_families']) or 'none'}",
                      f"- text colours {m['text_colors']}, background colours {m['background_colors']}, gradients {m['gradients']}, background images {m['background_images']}",
                      f"- images {m['images']}, inline svg {m['svgs']}, animated elements (before reduced motion) {m['animated_elements']}",
                      f"- sections {m['section_count']}, distinct section layouts {m['distinct_section_layouts']}, back-to-back repeats {m['consecutive_repeats']}",
                      f"- spacing values {m['spacing_values']}, share on a 4 px grid {m['spacing_on_4px']}",
                      f"- hero height {m['hero_height']} px, page height {m['page_height']} px, sideways scroll {m['overflow_x']}",
                      "- sections: " + "; ".join(f"{s['name']} [{s['signature']}]" for s in m["sections"]), ""]
        (review / "craft-facts.md").write_text("\n".join(lines) + "\n")
        (review / "concept.md").write_text(
            f"# Chosen direction {chosen.get('id', '?')} — {chosen.get('name', '?')}\n\n{chosen.get('brief', '')}\n\n"
            f"Signature move: {chosen.get('signature_move', '')}\nMotion: {chosen.get('motion', '')}\nImagery: {chosen.get('imagery', '')}\n"
            f"Owner notes: {direction.get('notes', '')}\n")
        refs = self.packet / "references" / "REFERENCES.md"
        if refs.exists():
            shutil.copyfile(refs, review / "references.md")
        return self.receipt(f"measure-{number}", fp, {"status": "completed", "round": number, "facts_path": "review/facts.md",
                                                      "craft_facts": "review/craft-facts.md",
                                                      "scale_ratio_1440": metrics.get("1440", {}).get("scale_ratio")})

    def review_fixture(self) -> dict:
        number = self.state["round"]
        fp = digest({"round": number})
        cached = self.cached(f"review_fixture-{number}", fp)
        if cached:
            return cached
        review = self.root / "review"
        sev = 3 if number == 1 else 1
        save(review / "findings.json", {"fixture": True, "findings": [
            {"id": "D1", "status": "confirmed", "page": "index.html", "viewport": "desktop", "element": "page title",
             "problem": "fixture finding", "evidence": "fixture", "severity": sev, "suggestion": "fixture fix"}]})
        (review / "report.md").write_text(f"# Fixture review round {number}\n\nStand-in merged findings (no model).\n")
        save(review / "craft" / "craft.json", {"critic": "craft", "fixture": True, "findings": [], "template_test": {"verdict": "fixture"}})
        return self.receipt(f"review_fixture-{number}", fp, {"status": "completed", "round": number, "severity": sev})

    def combine(self) -> dict:
        number = self.state["round"]
        review = self.root / "review"
        merged = load(review / "findings.json")
        craft_files = sorted((review / "craft").glob("*.json"))
        if not craft_files:
            raise ValueError("no craft review in review/craft/")
        craft = [load(f) for f in craft_files]
        fp = digest({"round": number, "merged": merged, "craft": craft})
        cached = self.cached(f"combine-{number}", fp)
        if cached:
            return cached
        blocking, minor = [], []
        for f in merged.get("findings", []):
            item = {"source": "usability", "id": f.get("id"), "severity": f.get("severity"), "element": f.get("element"),
                    "problem": f.get("problem"), "evidence": f.get("evidence"), "suggestion": f.get("suggestion"),
                    "criterion": f.get("criterion") or f.get("heuristic")}
            sev = f.get("severity") if isinstance(f.get("severity"), int) else 0
            (blocking if sev >= 4 or (sev >= 3 and f.get("status") == "confirmed") else minor).append(item)
        template = []
        for c in craft:
            for f in c.get("findings", []):
                item = {"source": "craft", "id": f.get("id"), "severity": f.get("severity"), "element": f.get("element"),
                        "problem": f.get("problem"), "evidence": f.get("evidence"), "suggestion": f.get("suggestion"),
                        "check": f.get("check")}
                sev = f.get("severity") if isinstance(f.get("severity"), int) else 0
                (blocking if sev >= 3 else minor).append(item)
            template.append(c.get("template_test", {}))
        can_revise = self.state["revisions"] < MAX_AUTO_REVISIONS
        verdict = "revise" if blocking and can_revise else "done"
        fixes = blocking + sorted(minor, key=lambda x: -(x["severity"] or 0))[:6]
        rdir = self.packet / "rounds" / f"r{number:02d}"
        if rdir.joinpath("review").exists():
            shutil.rmtree(rdir / "review")
        shutil.copytree(review, rdir / "review")
        summary = {"round": number, "verdict": verdict, "blocking": len(blocking), "minor": len(minor),
                   "unresolved_blocking": [] if verdict == "revise" else blocking,
                   "template_test": template, "revisions_done": self.state["revisions"], "decided_at": now()}
        save(rdir / "decision.json", {**summary, "fixes": fixes})
        self.state["verdict"] = verdict
        self.state["fix_list"] = fixes
        self.state["decision_seq"] += 1
        self.state["last_round"] = summary
        return self.receipt(f"combine-{number}", fp, {"status": "completed", **{k: summary[k] for k in ("round", "verdict", "blocking", "minor")},
                                                      "unresolved_blocking": len(summary["unresolved_blocking"])})

    def next_round(self) -> dict:
        return {"status": "completed", "verdict": self.state.get("verdict"), "round": self.state["round"]}

    # -- Penpot

    def convert(self) -> dict:
        number = self.state["round"]
        out = self.packet / "penpot" / f"r{number:02d}"
        fp = digest({"round": number, "site": tree_digest(self.site)})
        cached = self.cached(f"convert-{number}", fp)
        if cached:
            if not (out / "conversion.json").exists():
                raise ValueError("saved conversion report missing; refusing a silent repeat")
            return cached
        if (out / "pending.json").exists():
            raise ValueError(f"an earlier conversion of round {number} stopped part-way ({out / 'pending.json'}); inspect that Penpot file before retrying, never duplicate it")
        if out.exists():
            shutil.rmtree(out)
        brief = load(self.packet / "brief.json")
        name = f"{brief['product']} — homepage v2 r{number:02d}" + (" (fixture)" if self.fixture else "")
        report = h2p.convert(self.site, "index.html", out, name, browser=BROWSER, serve_host=SERVE_HOST,
                             label=brief["product"])
        summary = {"status": "completed", "round": number, "passed": report["passed"], "file_id": report["file"]["file_id"],
                   "url": report["file"]["url"], "fidelity_passed": report["fidelity_passed"],
                   "verify_passed": report["verify"]["passed"], "issues": report["issue_counts"],
                   "conversion": f"homepage/penpot/r{number:02d}/conversion.json"}
        return self.receipt(f"convert-{number}", fp, summary)

    def verify(self) -> dict:
        number = self.state["round"]
        out = self.packet / "penpot" / f"r{number:02d}"
        report = load(out / "conversion.json")
        client = h2p.penpot_client()
        client.login()
        fresh = client.get(report["file"]["file_id"])
        objects = fresh["data"]["pages-index"][report["file"]["page_id"]]["objects"]
        checks = {
            "conversion_verified": report["verify"]["passed"],
            "fidelity_within_bar": report["fidelity_passed"],
            "unchanged_since_conversion": fresh.get("revn") == report["file"]["revn"],
            "boards_present": all(b["id"] in objects and round(objects[b["id"]]["width"]) == b["width"] for b in report["boards"]),
            "component_mains_present": all(c["root"] in objects for c in report["components"]),
            "text_layers": sum(1 for o in objects.values() if o.get("type") == "text") > 0,
            "exports_saved": all((out / f"penpot-{w}.{k}").exists() for w in report["widths"] for k in ("png", "svg")),
        }
        fidelity = {w: {k: f.get(k) for k in ("overall_pct", "nontext_pct", "text_pct", "tile_max_pct", "tile_mean_max")}
                    for w, f in report["fidelity"].items()}
        result = {"round": number, "checked_at": now(), "checks": checks, "passed": all(checks.values()),
                  "fidelity": fidelity, "fidelity_bar": report["fidelity_bar"], "issues": report["issue_counts"]}
        save(out / "verify.json", result)
        if not result["passed"]:
            raise ValueError("Penpot check failed: " + ", ".join(k for k, v in checks.items() if not v)
                             + f" (see homepage/penpot/r{number:02d}/verify.json and conversion.json)")
        self.state["verified_round"] = number
        self.commit()
        return {"status": "completed", "round": number, "passed": True, "fidelity": fidelity}

    # -- handoff and owner final

    def handoff(self) -> dict:
        number = self.state["round"]
        if self.state.get("verified_round") != number:
            raise ValueError("this round's Penpot file has not passed verify")
        conv = load(self.packet / "penpot" / f"r{number:02d}" / "conversion.json")
        fp = digest({"round": number, "file": conv["file"]["file_id"], "site": tree_digest(self.site)})
        cached = self.cached(f"handoff-{number}", fp)
        if cached:
            return cached
        dest = self.packet / "packet" / f"r{number:02d}"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(self.site, dest / "site")
        pen = dest / "penpot"
        pen.mkdir(parents=True)
        src = self.packet / "penpot" / f"r{number:02d}"
        for f in sorted(src.iterdir()):
            if f.suffix in (".png", ".svg") or f.name in ("conversion.json", "verify.json"):
                shutil.copyfile(f, pen / f.name)
        for f in ("BRIEF.md", "brief.json", "direction.json"):
            if (self.packet / f).exists():
                shutil.copyfile(self.packet / f, dest / f)
        shutil.copytree(self.concepts_dir, dest / "concepts", ignore=shutil.ignore_patterns("fonts"))
        if (self.packet / "rounds").exists():
            shutil.copytree(self.packet / "rounds", dest / "rounds")
        if (self.packet / "references" / "REFERENCES.md").exists():
            shutil.copyfile(self.packet / "references" / "REFERENCES.md", dest / "REFERENCES.md")
        brief = load(self.packet / "brief.json")
        last = self.state.get("last_round", {})
        fonts = conv.get("fonts", [])
        lines = [f"# Homepage handoff — {brief['product']} (round {number})", "",
                 f"Direction: {self.state['direction']['concept']} — {self.state['direction']['concept_name']}"
                 + (" (fixture-test, not owner approval)" if self.fixture else " (owner direction)"),
                 f"Editable master: Penpot file {conv['file']['name']} — {conv['file']['url']}",
                 f"Boards: {', '.join(b['name'] for b in conv['boards'])}; components {len(conv['components'])}, instances {len(conv['instances'])},"
                 f" shared colours {len(conv['colors'])}, typographies {len(conv['typographies'])}.",
                 "", "## Fidelity (Penpot export vs browser render, % of pixels differing)"]
        for w, f in conv["fidelity"].items():
            lines.append(f"- {w}: overall {f.get('overall_pct')}%, non-text {f.get('nontext_pct')}%, text {f.get('text_pct')}%, worst tile {f.get('tile_max_pct')}% — {'pass' if f.get('passed') else 'FAIL'}")
        lines += ["", "## Review", f"Rounds: {number}; automatic revisions {self.state['revisions']}, owner change rounds {self.state['owner_changes']}.",
                  f"Last round: {last.get('blocking', 0)} blocking, {last.get('minor', 0)} minor; unresolved blocking: {len(last.get('unresolved_blocking', []))}."]
        for item in last.get("unresolved_blocking", []):
            lines.append(f"- UNRESOLVED {item.get('source')} {item.get('id')}: {item.get('problem')} ({item.get('element')})")
        for t in last.get("template_test", []):
            lines.append(f"- Craft critic 'could this be a template?': {t.get('verdict')} — {t.get('evidence', '')}")
        lines += ["", "## Fonts (licences travel with the files)"]
        lines += [f"- {f.get('family')} {f.get('weight')} {f.get('style')}: {f.get('licence', {}).get('file') if isinstance(f.get('licence'), dict) else f.get('licence')}" for f in fonts]
        lines += ["", "## Converter notes (approximations, never silent)"]
        lines += [f"- {k}: {v}" for k, v in sorted(conv["issue_counts"].items())] or ["- none"]
        lines += ["", "## Not checked here", "- Motion as designed (renders use reduced motion), real keyboard/screen-reader use beyond axe and the critics,",
                  "  real content beyond the brief's facts, publication. AI review is advisory; the owner decides taste.",
                  "", f"Owner taste approval: {'not applicable (fixture)' if self.fixture else 'pending the final gate'}."]
        (dest / "HANDOFF.md").write_text("\n".join(lines) + "\n")
        manifest = {"round": number, "created_at": now(), "files": {}}
        for f in sorted(dest.rglob("*")):
            if f.is_file():
                manifest["files"][str(f.relative_to(dest))] = hashlib.sha256(f.read_bytes()).hexdigest()
        save(dest / "manifest.json", manifest)
        rel = f"homepage/packet/r{number:02d}"
        return self.receipt(f"handoff-{number}", fp, {
            "status": "completed", "round": number, "handoff_path": f"{rel}/HANDOFF.md", "manifest_path": f"{rel}/manifest.json",
            "penpot_url": conv["file"]["url"], "files": len(manifest["files"]),
            "questions": [{"id": "final", "question": "Approve this homepage, or request changes with notes",
                           "options": ["approve", "request changes"]}]})

    def final(self, raw: str) -> dict:
        decision = safe_gate(raw)
        number = self.state["round"]
        if f"handoff-{number}" not in self.state["stages"]:
            raise ValueError(f"round {number} has no verified handoff to decide on")
        if decision.get("verdict") == "request_changes":
            notes = decision.get("notes")
            if not isinstance(notes, list) or not notes or not all(isinstance(n, str) and n.strip() for n in notes):
                raise ValueError("request_changes needs notes: a list of concrete changes")
            if self.state["owner_changes"] >= MAX_OWNER_CHANGES:
                raise ValueError("two owner change rounds used; start a new run for further work")
            key = f"final-{number}"
            fp = digest(decision)
            cached = self.cached(key, fp)
            if cached:
                return cached
            save(self.packet / f"final-r{number:02d}.json", {**decision, "recorded_at": now()})
            self.state["verdict"] = "owner_changes"
            self.state["fix_list"] = [{"source": "owner", "id": f"O{i}", "severity": 4, "problem": n} for i, n in enumerate(notes, 1)]
            self.state["decision_seq"] += 1
            return self.receipt(key, fp, {"status": "completed", "round": number, "verdict": "request_changes",
                                          "final_owner_approved": False})
        want = "fixture-test" if self.fixture else "owner-final"
        if decision.get("approval") != want:
            raise ValueError(f"final gate needs approval {want!r} or verdict request_changes")
        save(self.packet / "owner-final.json", {**decision, "round": number, "recorded_at": now(), "owner_approved": not self.fixture})
        self.state["owner_final_approved"] = not self.fixture
        self.commit()
        return {"status": "completed", "round": number, "verdict": "approved", "final_owner_approved": not self.fixture}


def _esc(value: str) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


STAGES = ("brief", "references", "concepts_fixture", "concepts_check", "concepts_next", "direction", "build_fixture",
          "plan_round", "revise_fixture", "measure", "review_fixture", "combine", "next_round", "convert", "verify",
          "handoff", "final")
FIXTURE_ONLY = {"concepts_fixture", "build_fixture", "revise_fixture", "review_fixture"}


def main() -> None:
    global BROWSER, SERVE_HOST
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("stage", choices=STAGES)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--fixture", action="store_true")
    parser.add_argument("--phase", default="draft")
    parser.add_argument("--browser", default=None)
    parser.add_argument("--serve-host", default=None)
    args = parser.parse_args()
    BROWSER = args.browser or BROWSER
    SERVE_HOST = args.serve_host or SERVE_HOST
    if args.stage in FIXTURE_ONLY and not args.fixture:
        raise SystemExit(f"{args.stage} is a fixture-only stage")
    job = Job(args.workspace, args.fixture)
    raw = os.environ.get("HOMEPAGE_DATA", "")
    methods = {
        "brief": lambda: job.brief(raw), "references": lambda: job.references(raw),
        "concepts_fixture": job.concepts_fixture, "concepts_check": lambda: job.concepts_check(args.phase),
        "concepts_next": job.concepts_next,
        "direction": lambda: job.direction(raw), "build_fixture": job.build_fixture, "plan_round": job.plan_round,
        "revise_fixture": job.revise_fixture, "measure": job.measure, "review_fixture": job.review_fixture,
        "combine": job.combine, "next_round": job.next_round, "convert": job.convert, "verify": job.verify,
        "handoff": job.handoff, "final": lambda: job.final(raw)}
    started = time.monotonic()
    try:
        result = methods[args.stage]()
    except (ValueError, RuntimeError, KeyError, OSError) as exc:
        # Our own messages; never raw HTTP bodies, environment or session data.
        raise SystemExit(f"{args.stage}: {exc}") from None
    result["seconds"] = round(time.monotonic() - started, 3)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
