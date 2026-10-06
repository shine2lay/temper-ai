"""Model-free page checks for design reviews (design role, queue #39, 2026-10-05).

design_page_checks.js collects raw facts in the page; this module judges them against the frozen
thresholds in design_page_checks_thresholds.json (calibrated on the planted test pages and their
clean controls before any model run, then frozen) and writes the lines a critic reads in facts.md.
Used by design_capture.py --page-checks. Every problem line names its check, so a critic's finding
can carry the same check name:

  repeated-copy        the same word run in several sections (prose only)
  first-screen-action  the brief's primary action inside the first phone screen (390x844)
  nav-fit              the main navigation on one line on the phone
  empty-column         no empty column wider than a set share of the content width (desktop)
  signifier            every interactive element shows a cue: border, fill, shadow, underline or icon
                       (links in a header or footer navigation bar are known by their place)
  text-over-image      text over an image, gradient or translucent layer: contrast from the pixels
                       behind it (the worst small region), not from the declared colours
  dark-small-text      running text under 14 px as light text on a dark background (dark theme)
  visuals              non-text pictures per section and in the first screen (facts for judging a
                       section's visual against its purpose; not pass or fail)
"""

from __future__ import annotations

import json
import pathlib
import re

HERE = pathlib.Path(__file__).resolve().parent
JS = HERE / "design_page_checks.js"
THRESHOLDS = HERE / "design_page_checks_thresholds.json"
PLAYBOOK = HERE.parent / "knowledge" / "context-playbook.json"

STOPWORDS = frozenset(
    "a an the and or but to of in on at for with by from as is are be been was were it its this that these those "
    "you your yours we our us they their them he she his her i me my so if then than not no can will just about "
    "into over up out all any each every more most some such only own same too very s t don do does did has have "
    "had".split()
)

PIXEL_CODE = r"""async (page) => {
  const A = __ARGS__;
  await page.evaluate(() => {
    const st = document.createElement('style');
    st.id = 'pc-hide';
    st.textContent = '[data-pc-cand], [data-pc-cand] * { color: transparent !important; -webkit-text-fill-color: transparent !important; '
      + 'text-shadow: none !important; text-decoration-color: transparent !important; caret-color: transparent !important; }';
    document.head.appendChild(st);
    return new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
  });
  const shots = [];
  try {
    for (const c of A.cands) {
      for (const q of c.lines) {
        const b64 = (await page.screenshot({fullPage: true, type: 'png', clip: {x: q[0], y: q[1], width: q[2], height: q[3]}})).toString('base64');
        shots.push({id: c.id, q, b64});
      }
    }
  } finally {
    await page.evaluate(() => {
      const st = document.getElementById('pc-hide');
      if (st) st.remove();
      for (const e of document.querySelectorAll('[data-pc-cand]')) e.removeAttribute('data-pc-cand');
    });
  }
  return await page.evaluate(async (B) => {
    const lum = ([r, g, b]) => {
      const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
      return 0.2126 * f(r) + 0.7152 * f(g) + 0.0722 * f(b);
    };
    const ratio = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
    const blend = (fg, bg) => [0, 1, 2].map((i) => fg[i] * fg[3] + bg[i] * (1 - fg[3]));
    const res = {};
    for (const s of B.shots) {
      const img = new Image();
      img.src = 'data:image/png;base64,' + s.b64;
      await img.decode();
      const cv = document.createElement('canvas');
      cv.width = img.width; cv.height = img.height;
      const g = cv.getContext('2d');
      g.drawImage(img, 0, 0);
      const d = g.getImageData(0, 0, cv.width, cv.height).data;
      const cell = Math.max(1, Math.round(B.cell * img.width / Math.max(1, s.q[2])));
      const col = B.colors[s.id];
      let worst = null;
      for (let y = 0; y < img.height; y += cell) {
        for (let x = 0; x < img.width; x += cell) {
          let r = 0, gg = 0, b = 0, n = 0;
          for (let yy = y; yy < Math.min(y + cell, img.height); yy++) {
            for (let xx = x; xx < Math.min(x + cell, img.width); xx++) {
              const i = (yy * img.width + xx) * 4; r += d[i]; gg += d[i + 1]; b += d[i + 2]; n++;
            }
          }
          const bg = [r / n, gg / n, b / n];
          const cr = ratio(col[3] < 1 ? blend(col, bg) : col.slice(0, 3), bg);
          if (!worst || cr < worst.ratio) worst = {ratio: cr, bg};
        }
      }
      if (worst && (!res[s.id] || worst.ratio < res[s.id].ratio)) {
        res[s.id] = {ratio: Math.round(worst.ratio * 100) / 100, bg: 'rgb(' + worst.bg.map(Math.round).join(',') + ')'};
      }
    }
    return res;
  }, {shots, colors: Object.fromEntries(A.cands.map((c) => [c.id, c.color])), cell: A.cell});
}"""


def thresholds() -> dict:
    return json.loads(THRESHOLDS.read_text(encoding="utf-8"))


def source(t: dict, primary: str, copy: bool, columns: bool, visuals: bool) -> str:
    """The in-page script for one view, with its options filled in."""
    opts = {"thresholds": t, "primary": primary or "", "copy": copy, "columns": columns, "visuals": visuals,
            "cues": True, "overlays": True, "small_dark": True}
    return JS.read_text(encoding="utf-8").replace("__OPTS__", json.dumps(opts))


def pixel_code(cands: list[dict], t: dict) -> str:
    keep = [{"id": c["id"], "lines": c["lines"][:3], "color": c["color"]} for c in cands if c.get("lines")]
    return PIXEL_CODE.replace("__ARGS__", json.dumps({"cands": keep, "cell": t["text_over_image"]["cell"]}))


def primary_action(brief_text: str) -> str:
    """The primary action a brief names ("Primary action: Book a pickup"), or ""."""
    return _brief_line(brief_text, r"primary action")[:80]


def design_context(brief_text: str) -> str:
    """The playbook context a brief names ("Design context: marketing-landing-general"), or ""."""
    found = _brief_line(brief_text, r"design context")
    m = re.match(r"[a-z0-9]+(?:-[a-z0-9]+)*", found.lower())
    return m.group(0) if m else ""


def _brief_line(brief_text: str, label: str) -> str:
    m = re.search(rf"^[\s>*_#-]*{label}\s*[*_]*\s*[:\-\u2013\u2014]\s*(.+)$", brief_text or "", re.I | re.M)
    if not m:
        return ""
    return m.group(1).strip().strip("*_ ").strip(".\"'\u201c\u201d`").strip()


def _tokens(text: str) -> list[list[str]]:
    """Sentences of lowercase words; a word run never crosses a sentence."""
    out = []
    for sentence in re.split(r"[.!?;:\u2014\u2013|()\[\]]+", text.lower()):
        words = re.findall(r"[a-z0-9]+(?:['\u2019][a-z]+)?", sentence)
        if words:
            out.append(words)
    return out


def repeated_copy(copy: list[dict], t: dict) -> list[dict]:
    """Word runs shared by several sections: min_words or more words in min_sections sections, or
    long_words or more in long_sections; a run needs min_content_words words that are not stopwords.
    Overlapping runs merge into one phrase."""
    r = t["repeated_copy"]
    n = r["min_words"]

    def grams(k: int) -> tuple[dict, dict]:
        found: dict[tuple, set] = {}
        first: dict[tuple, tuple] = {}
        for si, sec in enumerate(copy):
            for bi, block in enumerate(sec.get("blocks") or []):
                for ti, words in enumerate(_tokens(block)):
                    for i in range(len(words) - k + 1):
                        g = tuple(words[i:i + k])
                        if sum(w not in STOPWORDS for w in g) < r["min_content_words"]:
                            continue
                        found.setdefault(g, set()).add(si)
                        first.setdefault(g, (si, bi, ti, i))
        return found, first

    short, first = grams(n)
    keep = {g: s for g, s in short.items() if len(s) >= r["min_sections"]}
    for g, s in grams(r["long_words"])[0].items():
        if len(s) >= r["long_sections"]:
            for i in range(len(g) - n + 1):
                sub = g[i:i + n]
                if sub in short:
                    keep[sub] = short[sub]
    # Runs that follow each other where they first occur merge into one phrase.
    phrases: list[dict] = []
    for g in sorted(keep, key=lambda x: first[x]):
        si, bi, ti, i = first[g]
        last = phrases[-1] if phrases else None
        if last and last["at"] == (si, bi, ti) and i <= last["end"]:
            extra = i + n - last["end"]
            if extra > 0:
                last["words"] += list(g[n - extra:])
                last["end"] += extra
            last["secs"] |= keep[g]
            continue
        phrases.append({"words": list(g), "at": (si, bi, ti), "end": i + n, "secs": set(keep[g])})
    return [{"phrase": " ".join(p["words"]), "sections": [copy[s]["name"] for s in sorted(p["secs"])]} for p in phrases]


def judge(vp: str, raw: dict, t: dict, pixels: dict | None = None) -> tuple[list, list]:
    """(problems, passes) as (check, line) for one view. vp is desktop, mobile or desktop-dark."""
    problems: list[tuple[str, str]] = []
    passes: list[tuple[str, str]] = []
    width = (raw.get("viewport") or [0, 0])[0]
    base_vp = vp.split("-")[0]
    nav = raw.get("nav") or {}
    if base_vp == t["nav_fit"]["viewport"] and nav.get("found") and vp == base_vp:
        rows = " / ".join(", ".join(f'"{x}"' for x in row) for row in nav.get("rows") or [])
        extra = []
        if nav.get("wrapped"):
            extra.append("link text broken over two lines: " + ", ".join(f'"{x}"' for x in nav["wrapped"]))
        if nav.get("overflow"):
            extra.append("past the screen edge: " + ", ".join(f'"{x}"' for x in nav["overflow"]))
        if nav["lines"] > t["nav_fit"]["max_lines"] or extra:
            problems.append(("nav-fit", f"main navigation `{nav['sel']}` does not fit on one line at {width} px: "
                             f"{nav['lines']} lines ({rows})" + ("; " + "; ".join(extra) if extra else "")
                             + f"; header {nav.get('header_height')} px tall (page check: nav-fit)"))
        else:
            passes.append(("nav-fit", f"main navigation fits on one line at {width} px ({rows}) (page check: nav-fit)"))
    act = raw.get("action")
    if act and base_vp == t["first_screen_action"]["viewport"] and vp == base_vp:
        first = act.get("first")
        screen = t["first_screen_action"]["screen_height"]
        if not first:
            problems.append(("first-screen-action", f'no visible control carries the primary action "{act["label"]}" '
                             f"at {width} px (page check: first-screen-action)"))
        elif first["bottom"] > screen:
            problems.append(("first-screen-action", f'primary action "{act["label"]}" first appears at {first["top"]}-'
                             f'{first["bottom"]} px (`{first["sel"]}` "{first["text"]}", in {first["section"] or "?"}), '
                             f"below the first screen ({width}x{screen}: it ends at {screen} px) (page check: first-screen-action)"))
        else:
            passes.append(("first-screen-action", f'primary action "{act["label"]}" is inside the first screen at {width} px: '
                           f'`{first["sel"]}` "{first["text"]}" at {first["top"]}-{first["bottom"]} px (page check: first-screen-action)'))
    if base_vp == t["empty_column"]["viewport"] and vp == base_vp and raw.get("columns") is not None:
        for c in raw.get("columns") or []:
            problems.append(("empty-column", f'empty column {c["width"]} px wide ({round(c["share"] * 100)}% of the '
                             f'{raw["frame"][1] - raw["frame"][0]} px content width), on the {c["side"]}, {c["height"]} px tall beside '
                             f'"{c["beside"]}" in {c["section"]} (from {c["top"]} px) (page check: empty-column)'))
        if not raw.get("columns"):
            passes.append(("empty-column", f"no empty column wider than {round(t['empty_column']['min_share'] * 100)}% of the content "
                           f"width over {t['empty_column']['min_height']} px or more (page check: empty-column)"))
    cues = raw.get("cues") or {}
    if cues:
        if cues.get("without_count"):
            els = "; ".join(f'`{x["sel"]}` "{x["text"]}"' + (f" in {x['section']}" if x.get("section") else "")
                            for x in cues.get("without", [])[:12])
            problems.append(("signifier", f"{cues['without_count']} of {cues['checked']} interactive elements show no visible "
                             f"cue (no border, fill, shadow, underline or icon; colour alone): {els} (page check: signifier)"))
        elif cues.get("checked"):
            passes.append(("signifier", f"all {cues['checked']} interactive elements outside the header and footer navigation "
                           "show a visible cue (border, fill, shadow, underline or icon) (page check: signifier)"))
    ok = []
    for c in raw.get("overlays") or []:
        px = (pixels or {}).get(str(c["id"])) or (pixels or {}).get(c["id"])
        if not px:
            continue
        line = (f'`{c["sel"]}` "{c["text"]}" ({c["size"]}px/{c["weight"]}, over {c["kind"]}{", in " + c["section"] if c.get("section") else ""}): '
                f'{px["ratio"]}:1 at the worst {t["text_over_image"]["cell"]} px region behind its letters, measured from the '
                f'screenshot (behind it {px["bg"]}; the declared colours give {c["declared"]}:1; needs {c["needs"]}:1)')
        if px["ratio"] < c["needs"]:
            problems.append(("text-over-image", "text over an image, gradient or translucent layer fails contrast: " + line
                             + " (page check: text-over-image)"))
        else:
            ok.append((px["ratio"] / c["needs"], c, px))
    if ok:
        _, c, px = min(ok, key=lambda x: x[0])
        passes.append(("text-over-image", f"{len(ok)} text element(s) over an image, gradient or translucent layer pass contrast "
                       f"measured from the pixels behind their letters; closest: `{c['sel']}` \"{c['text'][:40]}\" "
                       f"{px['ratio']}:1 (needs {c['needs']}:1) (page check: text-over-image)"))
    small = raw.get("small_dark") or []
    if small:
        # One problem per view: the instances of one problem are grouped (examples, sizes, sections).
        where = "in the dark colour scheme" if vp.endswith("-dark") else "as light text on a dark background"
        sizes = sorted({c["size"] for c in small})
        sections = list(dict.fromkeys(c["section"] for c in small if c.get("section")))
        examples = "; ".join(f'`{c["sel"]}` "{c["text"]}" {c["size"]} px, {c["words"]} words, {c["color"]} on {c["background"]}'
                             for c in small[:3])
        problems.append(("dark-small-text", f'{len(small)} block(s) of running text under {t["dark_small_text"]["max_px"]} px '
                         f'{where} (sizes {", ".join(str(s) + " px" for s in sizes)}'
                         + (f'; in {", ".join(sections)}' if sections else "") + f"), e.g. {examples} (page check: dark-small-text)"))
    return problems, passes


def copy_problems(raw_desktop: dict, t: dict) -> tuple[list, list]:
    found = repeated_copy(raw_desktop.get("copy") or [], t)
    r = t["repeated_copy"]
    if not found:
        return [], [("repeated-copy", f"no word run of {r['min_words']}+ words repeated in {r['min_sections']}+ sections "
                     f"(or {r['long_words']}+ words in {r['long_sections']}+), prose only (page check: repeated-copy)")]
    lines = "; ".join(f'"{p["phrase"]}" in {", ".join(p["sections"])}' for p in found[:8])
    return [("repeated-copy", f"the same words repeat across sections ({len(found)} phrase(s)): {lines} "
             "(page check: repeated-copy)")], []


def info_lines(views: dict[str, dict], dark_captured: bool, dark_offered: bool) -> list[str]:
    """The page-check facts that are neither pass nor fail: pictures per section, cues used, dark pass."""
    lines: list[str] = []
    desk = views.get("desktop") or next(iter(views.values()), {})
    vis = desk.get("visuals") or {}
    if vis:
        lines.append("Pictures by section (desktop; img, svg, canvas, video and CSS background images; icons under "
                     "48 px left out; share = part of the section's area; a product mock-up built from page elements, "
                     "such as a sample report card or a table, is not counted here: judge it from the screenshots):")
        for s in vis.get("sections", []):
            kinds = ", ".join(f"{i['kind']} {i['size'][0]}x{i['size'][1]}" + (f' "{i["name"]}"' if i.get("name") else "")
                              + (" (aria-hidden)" if i.get("decorative") else "") for i in s.get("items", [])[:4])
            lines.append(f"- {s['name']}{' (page chrome)' if s.get('chrome') else ''}: {s['count']} picture(s), "
                         f"{round(s['share'] * 100)}% of the section" + (f": {kinds}" if kinds else ""))
        shares = [f"{vp} {round((v.get('visuals') or {}).get('first_screen_share', 0) * 100)}%" for vp, v in views.items()
                  if v.get("visuals") and not vp.endswith("-dark")]
        lines.append("First screen covered by pictures: " + ", ".join(shares))
        lines.append("Sections with no picture: " + (", ".join(vis.get("none") or []) or "none"))
    cues = desk.get("cues") or {}
    if cues:
        by = ", ".join(f"{k} {v}" for k, v in sorted((cues.get("by_cue") or {}).items()))
        lines.append(f"Interactive elements checked for a visible cue: {cues.get('checked', 0)} ({by or 'none'}); links in a "
                     f"header or footer navigation bar, known by their place: {cues.get('nav_links', 0)}")
    over = sum(len(v.get("overlays") or []) for v in views.values())
    lines.append(f"Text over images, gradients or translucent layers measured from pixels: {over} text element(s) over all views")
    if dark_captured:
        lines.append("Dark colour scheme: the page offers one; captured as view desktop-dark (prefers-color-scheme: dark).")
    else:
        lines.append("Dark colour scheme: " + ("offered but not captured" if dark_offered else "not offered by the page") + ".")
    return lines


def context_md(context_id: str) -> str:
    """review/context.md: the playbook context the page is designed for (queue #37 playbook)."""
    data = json.loads(PLAYBOOK.read_text(encoding="utf-8"))
    c = next((x for x in data.get("contexts", []) if x.get("id") == context_id), None)
    if not c:
        known = ", ".join(x.get("id", "?") for x in data.get("contexts", []))
        return (f"# Design context: {context_id} (not in the playbook)\n\nThe brief names design context "
                f"{context_id!r}, which configs/design/knowledge/context-playbook.json does not hold (known: {known}). "
                "Put the context check under not_checked.\n")
    lines = [
        f"# Design context: {c.get('name')} ({c.get('id')})", "",
        "From the design context playbook (configs/design/knowledge/context-playbook.json; evidence ids E### point to "
        "its evidence file). Check the rendered page against it: each avoid-list item you can see on the page, and each "
        "trust signal the page needs but lacks, is a finding with check \"context\" that names the item and its "
        "evidence ids. Whether a section needs a picture is not set by this context (not by audience or page type): "
        "the section's purpose decides.",
        "",
        f"- Users: {c.get('users', '')}",
        f"- Page: {c.get('page', '')}; device: {c.get('device', '')}",
        f"- Density: {c.get('density', '')}",
        "", "## Avoid", "",
    ]
    lines += [f"- {a}" for a in c.get("avoid") or []] or ["- (none listed)"]
    lines += ["", "## Trust signals the page needs", ""]
    lines += [f"- {s}" for s in c.get("trust_signals") or []] or ["- (none listed)"]
    return "\n".join(lines) + "\n"
