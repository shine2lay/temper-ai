#!/usr/bin/env python3
"""The design research step's script stages (Design queue #38; docs/design-files.md). No model.

Every design workflow (homepage, logo, app screens, marketing) runs these stages first. They read the
product's source pack and design files (copied into the run by the host: design_files.py pack), decide
whether the product's design is defined, partial or none, and when it is not defined, check and assemble
the research the research agents write:

  inventory         defined | partial | none, the parts to research, research/TASK.md for the agents
  check             users.json (every claim sourced with a quote found at its source, or an assumption)
                    and the category pick; problems go back to the researcher
  next              loop control for check and assemble
  capture           first screens and measured facts of 6-10 category sites (playwright-mcp)
  assemble          direction.json checked against the playbook, research.json, RESEARCH.md and the
                    one-page research board (PNG; text 16 px or more, WCAG contrast measured)
  gate              the research gate: Design confirms or corrects the users and picks a direction
                    (decided_by design, owner for his own words, fixture-test in fixture runs)
  decision          research/FOR_DESIGN.md and research/fixed.json for the design stages: the chosen
                    direction with its five audience targets, and the approved parts as fixed constraints
  logo_brief        a logo brief completed from research (context, meaning, competitor marks, a fixed palette)
  save              after a final approval: design-files-out/ (DESIGN.md, tokens.json, registry-update.json)
                    with approved_by from the final gate's decided_by; the host applies it
  fixture           $0 stand-ins for the research agents (fixture runs only)

State and stage receipts live in research/state.json: a resumed run never repeats a finished stage.
"""
from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import os
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import design_axes as axes  # noqa: E402
import design_files as df  # noqa: E402
import research_contracts as rc  # noqa: E402

VERSION = 1
PLAYBOOK_DIR = HERE.parent / "knowledge"
FIXTURES = HERE.parent / "fixtures" / "research"
FIXTURE_HOST = "fixture.invalid"
JOBS = ("homepage", "logo", "app_screen", "marketing")
MIN_CAPTURED = 4
WEB_TIMEOUT = 45
# Stages that only record what earlier files say (no model, nothing slow). A fork or a rerun that
# changes their inputs runs them again before anything that reads them, so they work it out again;
# the earlier receipt is kept under "superseded" (and an earlier gate answer as its own file).
# Every other stage refuses changed inputs: there they mean a reused workspace.
REDERIVED = ("gate", "decision", "logo_brief")
BLOCKED = re.compile(r"(access denied|verify you are human|are you a robot|captcha|enable javascript|just a moment|"
                     r"request blocked|forbidden)", re.I)
BOARD_INK, BOARD_MUTED, BOARD_PAPER, BOARD_PANEL, BOARD_LINE = "#1B1B1F", "#45464F", "#FFFFFF", "#F3F3F6", "#C9CAD3"
ROLE_ORDER = ("dominant", "accent", "ink", "surface", "on_dominant", "on_accent")


def now() -> str:
    return dt.datetime.now(dt.UTC).isoformat(timespec="seconds")


def load(path: Path) -> Any:
    return json.loads(Path(path).read_text())


def save(path: Path, value: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)


def write(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def digest(value: Any) -> str:
    import hashlib
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def file_digest(path: Path) -> str:
    return df.sha256(path) if Path(path).is_file() else ""


def _homepage():
    import design_homepage_v2 as hp  # the browser helpers (playwright-mcp) live there
    return hp


# ---------------------------------------------------------------- the job


class Job:
    def __init__(self, workspace: str, fixture: bool = False):
        self.root = Path(workspace).resolve()
        self.fixture = fixture
        self.dir = self.root / "research"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.dir / "state.json"
        self.state = load(self.state_path) if self.state_path.exists() else {
            "version": VERSION, "created_at": now(), "fixture": fixture, "stages": {}, "checks": {}}
        if self.state.get("fixture") != fixture:
            raise ValueError("this workspace's research belongs to a fixture run" if self.state.get("fixture")
                             else "this workspace's research belongs to a real run")

    def commit(self) -> None:
        save(self.state_path, self.state)

    def receipt(self, stage: str, fingerprint: str, output: dict) -> dict:
        self.state["stages"][stage] = {"fingerprint": fingerprint, "completed_at": now(), "output": output}
        self.commit()
        return output

    def cached(self, stage: str, fingerprint: str) -> dict | None:
        receipt = self.state["stages"].get(stage)
        if not receipt:
            return None
        if receipt["fingerprint"] == fingerprint:
            return {**receipt["output"], "reused": True}
        if stage not in REDERIVED:
            raise ValueError(f"saved {stage} inputs changed; use a fresh workspace rather than silently repeating work")
        kept = {"stage": stage, "superseded_at": now(), **receipt}
        superseded = self.state.setdefault("superseded", [])
        if stage == "gate" and (self.dir / "gate.json").exists():  # an earlier answer stays on record
            old = self.dir / f"gate-superseded-{sum(s['stage'] == 'gate' for s in superseded) + 1}.json"
            shutil.copyfile(self.dir / "gate.json", old)
            kept["record"] = f"research/{old.name}"
        superseded.append(kept)
        del self.state["stages"][stage]
        self.commit()
        return None

    # -- shared facts

    @property
    def inv(self) -> dict:
        path = self.dir / "inventory.json"
        if not path.exists():
            raise ValueError("research/inventory.json missing: the inventory stage runs first")
        return load(path)

    def playbook(self) -> dict:
        return rc.load_playbook(self.dir / "playbook" / "context-playbook.json")

    def deciders(self) -> tuple[str, ...]:
        return (rc.FIXTURE_DECIDER,) if self.inv["fixture_registry"] else rc.REAL_DECIDERS

    def captured(self) -> list[str]:
        path = self.dir / "category" / "capture.json"
        if not path.exists():
            return []
        return [s["id"] for s in load(path)["sites"] if s.get("usable")]

    # -- inventory

    def inventory(self, raw: str) -> dict:
        req = json.loads(raw) if raw.strip() else {}
        if not isinstance(req, dict):
            raise ValueError("research_json is an object")
        allowed = {"job", "audience", "gate", "force", "taste_md", "directions"}
        if set(req) - allowed:
            raise ValueError(f"research_json has unknown keys {sorted(set(req) - allowed)}")
        job = req.get("job")
        if job not in JOBS:
            raise ValueError(f"research_json.job is one of {', '.join(JOBS)}")
        gate = req.get("gate", "on")
        if gate not in ("on", "off"):
            raise ValueError("research_json.gate is on or off")
        count = req.get("directions", 3)
        if count not in (2, 3):
            raise ValueError("research_json.directions is 2 or 3")
        audience = req.get("audience", "")
        if not isinstance(audience, str) or len(audience) > 300:
            raise ValueError("research_json.audience is text (300 characters at most)")
        manifest = df.verify_pack(self.root)
        fixture_registry = bool(manifest.get("fixture"))
        if self.fixture and not fixture_registry:
            raise ValueError("a fixture run takes a pack from the fixture registry")
        files = df.read_files(self.root / "design-files")
        if files and files.get("product") not in (None, manifest["product"]):
            raise ValueError("the design files belong to another product")
        fp = digest({"req": req, "pack": manifest, "files": file_digest(self.root / "design-files" / "DESIGN.md"),
                     "tokens": file_digest(self.root / "design-files" / "tokens.json")})
        cached = self.cached("inventory", fp)
        if cached:
            return cached
        inv = df.inventory(manifest.get("registry_entry"), files, job, audience=audience, force=req.get("force"),
                           fixture=fixture_registry)
        research = inv["research"]
        agent = research["users"] != "none" or research["category"]
        ran = bool(research["any"])
        # Playbook and taste are copied into the run: agents read only the workspace, and a later playbook
        # change cannot alter a run in progress.
        pb = self.dir / "playbook"
        pb.mkdir(parents=True, exist_ok=True)
        for name in ("context-playbook.json", "context-playbook.md"):
            shutil.copyfile(PLAYBOOK_DIR / name, pb / name)
        taste = req.get("taste_md") or ""
        if not taste and (self.root / "homepage" / "TASTE.md").is_file():
            taste = (self.root / "homepage" / "TASTE.md").read_text()
        write(self.dir / "TASTE.md", taste or "# Taste\n\nNo taste entries were passed to this run.\n")
        record = {**inv, "product": manifest["product"], "name": manifest["name"], "fixture_registry": fixture_registry,
                  "gate": "on" if ran and gate == "on" else "off", "gate_requested": gate, "directions": count,
                  "agent": agent, "pack_files": sorted(manifest.get("files", {})),
                  "current_state": sorted(manifest.get("current_state", {})),
                  "design_files": sorted(manifest.get("design_files", {})), "recorded_at": now()}
        save(self.dir / "inventory.json", record)
        write(self.dir / "TASK.md", self.task_md(record, files))
        yn = lambda v: "yes" if v else "no"  # noqa: E731 - conditions compare strings
        return self.receipt("inventory", fp, {
            "status": inv["status"], "product": manifest["product"], "job": job, "missing": inv["missing"],
            "fixed": inv["fixed"], "research_users": research["users"], "research_category": yn(research["category"]),
            "research_direction": yn(research["direction"]), "research_agent": yn(agent), "research_any": yn(ran),
            "gate": record["gate"], "inventory_path": "research/inventory.json", "task_path": "research/TASK.md"})

    def task_md(self, inv: dict, files: dict | None) -> str:
        """What the research agents must produce for this job (no answers, only the job and the rules)."""
        r = inv["research"]
        lines = [f"# Research task — {inv['name']} ({inv['job']})", "",
                 f"Design files: {inv['status']}. Approved parts (fixed constraints): {', '.join(inv['fixed']) or 'none'}. "
                 f"Parts to research: {', '.join(inv['missing']) or 'none'}.", ""]
        lines += ["## Sources in this workspace",
                  "- source/docs/: the product's own material (README, docs, notes). Read every file.",
                  "- source/current-state/: what the product looks like today (CSS, screens): the current state "
                  "to learn from, not rules." if inv["current_state"] else "- source/current-state/: none.",
                  "- design-files/: the product's design files (DESIGN.md, tokens.json); approved parts are fixed."
                  if inv["design_files"] else "- design-files/: none yet.",
                  "- research/playbook/context-playbook.md and .json: what people like and trust, by context, with evidence ids.",
                  "- research/TASTE.md: the owner's taste (a bias, kept apart from the evidence).", ""]
        lines += ["## Researcher (research/users.json" + (", research/category/pick.json" if r["category"] else "") + ")"]
        if r["users"] == "full":
            lines += ["Write research/users.json: the product (name, what, for_whom, value, meaning, claims) and its user "
                      "groups (1-6; exactly one primary; roles primary, secondary or buyer) with their jobs, expertise, how "
                      "often they use it, devices, setting, stakes and access needs."]
        elif r["users"] == "audience":
            lines += [f"The approved users profile does not cover this job's audience: \"{inv['audience']['text']}\". Write "
                      "research/users.json with the audience-only fields: groups for that audience only and their claims "
                      "(no product block). The visual system stays as approved."]
        else:
            lines += ["The users profile is approved: do not write research/users.json."]
        if r["users"] != "none":
            lines += ["",
                      "Claims (the claims list, ids c1, c2, ...): every statement about the product or its users is a claim with",
                      "a topic and a status:",
                      "- sourced: source {file: \"source/docs/<file>\", quote} or {url: \"https://...\", quote}. The quote is",
                      "  copied exactly from that file or page (12+ characters); the check re-opens every source.",
                      "- assumption: no source supports it; say why in note. Assumptions are fine, unsourced facts are not.",
                      "- rejected: a statement in the sources you do not believe (no evidence behind it); note says why.",
                      "- superseded: an older statement a newer source contradicts; superseded_by names the newer sourced",
                      "  claim and note says why. Check dates: newer, better evidence wins.",
                      f"A note is one or two plain sentences, at most {rc.NOTE_MAX} characters.",
                      "Lengths: a claim's text 5-400 characters, its quote 12-400; a group's summary 10-400; each product",
                      "field 2-500; each assumption at most 300.",
                      "Use web research (search, open pages) for the product's category and its users where the pack is",
                      "thin; quote pages exactly. Each group lists the ids of its claims. assumptions lists up to 12 things",
                      "to confirm with real users."]
        if r["category"]:
            lines += ["",
                      "Category pick (research/category/pick.json): {category, sites: 6-10 of {id (slug), name, url (https home",
                      "page), kind leader|competitor|adjacent, why}}. At least 4 are leaders or close competitors of this",
                      "product. Pick public pages that open without a login, a consent wall or a bot check; the capture",
                      "stage needs at least 4 of them to load."]
        if r["direction"]:
            fixed = [p for p in inv["fixed"] if p in ("colour", "type")]
            lines += ["", "## Director (research/direction.json)",
                      "Read research/USERS.md, research/category/CATEGORY.md and its screenshots, the playbook and the taste file.",
                      "1. contexts: the playbook contexts this product and job fit, each {id, role page|product|audience, why}."
                      + (" Exactly one has role page (the kind of page this job makes)." if inv["job"] in ("homepage", "app_screen", "marketing") else ""),
                      f"2. candidates: {inv['directions']} direction candidates D1..D{inv['directions']}, each {{id, name, context "
                      "(a chosen context id), family (copied exactly from that context's styles.preferred or styles.acceptable), "
                      "why (why it suits these users, citing evidence ids), axes {density low|medium|high, type_scale "
                      "compact|medium|large, colour_energy low|medium|high, motion low|medium|high, copy_tone "
                      "expert|neutral|friendly}, principles (2-6), do (2-8), dont (2-8), follow (1-8 category conventions "
                      "to keep), differentiate (1-6 ways to stand out), evidence (2+ playbook ids), palette, type}. "
                      "Candidates differ in direction, not in wording.",
                      "   Lengths: a context's why 10-400 characters; a candidate's name 2-60 and why 10-600; palette and "
                      "type 5-300; every list line at most 300; recommended.reason 10-600; taste.note at most 600.",
                      "3. recommended {id, reason}; taste {ids (T ids used), note}: taste is a bias kept apart from evidence;",
                      "   assumptions (things to confirm).",
                      "4. category: {expect: 3-12 {text, sites (2+ captured ids)}, stand_out: 2-8 {text, why}, marks: "
                      "{site, family geometric|letterform|pictorial|emblem|wordmark|none, description}"
                      + (" for every captured site" if inv["job"] == "logo" else "") + "}.",
                      "The five axes in numbers (the concept check measures them):"]
            lines += [f"- {k}: " + "; ".join(f"{lvl} = {txt}" for lvl, txt in axes.TARGETS[k].items()) for k in axes.LEVELS]
            if fixed:
                lines += [f"Approved and fixed: {', '.join(fixed)}. Set palette and/or type to \"fixed\" in every candidate "
                          "for those parts and design around them."]
        lines += ["", "## Problems from the last check", "None yet."]
        return "\n".join(lines) + "\n"

    def set_problems(self, who: str, problems: list[str]) -> None:
        path = self.dir / "TASK.md"
        text = path.read_text()
        head = text.split("## Problems from the last check")[0]
        body = (f"For the {who}: fix these and write the file again.\n" + "\n".join(f"- {p}" for p in problems)
                if problems else "None.")
        write(path, head + "## Problems from the last check\n" + body + "\n")

    # -- fixture stand-ins

    def fixture_stage(self, phase: str) -> dict:
        if not self.fixture:
            raise ValueError("fixture stand-ins run only in fixture runs")
        inv = self.inv
        src = FIXTURES / inv["product"]
        fp = digest({"phase": phase, "src": [file_digest(p) for p in sorted(src.glob("*.json"))]})
        cached = self.cached(f"fixture-{phase}", fp)
        if cached:
            return cached
        wrote = []
        if phase == "users":
            if inv["research"]["users"] != "none":
                shutil.copyfile(src / "users.json", self.dir / "users.json")
                wrote.append("research/users.json")
            if inv["research"]["category"]:
                (self.dir / "category").mkdir(exist_ok=True)
                shutil.copyfile(src / "pick.json", self.dir / "category" / "pick.json")
                wrote.append("research/category/pick.json")
        elif phase == "direction":
            if inv["research"]["direction"]:
                shutil.copyfile(src / "direction.json", self.dir / "direction.json")
                wrote.append("research/direction.json")
        else:
            raise ValueError("fixture phase is users or direction")
        return self.receipt(f"fixture-{phase}", fp, {"status": "completed", "wrote": wrote, "fixture": True})

    # -- check (researcher's files)

    def check(self, phase: str) -> dict:
        if phase not in ("draft", "final"):
            raise ValueError("phase is draft or final")
        inv = self.inv
        r = inv["research"]
        if not inv["agent"]:
            return {"status": "completed", "phase": phase, "verdict": "ok", "skipped": True,
                    "why": "no users or category research needed"}
        users_path, pick_path = self.dir / "users.json", self.dir / "category" / "pick.json"
        # The rules are part of the fingerprint: a verdict holds only for the checks that made it,
        # so a fixed check re-judges the same files on resume instead of replaying the old verdict.
        fp = digest({"phase": phase, "users": file_digest(users_path), "pick": file_digest(pick_path),
                     "rules": file_digest(Path(rc.__file__))})
        attempt = self.state["checks"].get(f"check-{phase}", 0)
        key = f"check-{phase}-{attempt}"
        prior = self.state["stages"].get(key)
        if prior and prior["fingerprint"] == fp:
            return {**prior["output"], "reused": True}
        if prior:
            attempt += 1
            key = f"check-{phase}-{attempt}"
        self.state["checks"][f"check-{phase}"] = attempt
        problems: list[str] = []
        users = None
        if r["users"] != "none":
            if not users_path.is_file():
                problems.append("research/users.json is missing")
            else:
                try:
                    users = load(users_path)
                except json.JSONDecodeError as exc:
                    problems.append(f"research/users.json is not JSON: {exc}")
            if users is not None:
                web = self.fetch_pages(rc.claim_urls(users)) if isinstance(users, dict) else {}
                problems += rc.check_users(users, self.root, web=web, audience_only=r["users"] == "audience")
        if r["category"]:
            if not pick_path.is_file():
                problems.append("research/category/pick.json is missing")
            else:
                try:
                    pick = load(pick_path)
                    problems += rc.check_category_pick(pick)
                    if not self.fixture and any(urllib.parse.urlparse(s.get("url", "")).hostname == FIXTURE_HOST
                                                for s in pick.get("sites", []) if isinstance(s, dict)):
                        problems.append("fixture sites are for fixture runs only")
                except json.JSONDecodeError as exc:
                    problems.append(f"research/category/pick.json is not JSON: {exc}")
        verdict = "ok" if not problems else "retry"
        result = {"phase": phase, "attempt": attempt, "verdict": verdict, "problems": problems, "checked_at": now()}
        save(self.dir / "check.json", result)
        save(self.dir / f"check-{phase}-{attempt}.json", result)
        self.set_problems("researcher", problems)
        if verdict == "ok" and users is not None:
            write(self.dir / "USERS.md", rc.users_md(users, title=f"Users — {inv['name']}"))
        elif verdict == "ok":
            write(self.dir / "USERS.md", self.approved_users_md())
        stats = {}
        if isinstance(users, dict) and isinstance(users.get("claims"), list):
            for c in users["claims"]:
                if isinstance(c, dict):
                    stats[c.get("status", "?")] = stats.get(c.get("status", "?"), 0) + 1
        return self.receipt(key, fp, {"status": "completed", "phase": phase, "attempt": attempt, "verdict": verdict,
                                      "problems": len(problems), "claims": stats, "check_path": "research/check.json"})

    def approved_users_md(self) -> str:
        files = df.read_files(self.root / "design-files")
        body = (files or {}).get("design", {}).get("sections", {}).get("Users", "") if files else ""
        return f"# Users — {self.inv['name']} (approved design files)\n\n{body.strip() or 'No approved users profile.'}\n"

    def fetch_pages(self, urls: list[str]) -> dict[str, str | None]:
        """Open each cited page once (browser first, plain HTTP as a fallback) and keep its text for re-checks."""
        cache_dir = self.dir / "web"
        index_path = cache_dir / "index.json"
        index = load(index_path) if index_path.exists() else {}
        todo = [u for u in urls if u not in index]
        for url in todo:
            text = None
            if urllib.parse.urlparse(url).scheme == "https":
                text = self.page_text_browser(url) or self.page_text_http(url)
            name = digest(url)[:16] + ".txt"
            if text is not None:
                write(cache_dir / name, text)
            index[url] = {"file": name if text is not None else None, "fetched_at": now(), "chars": len(text or "")}
            save(index_path, index)
        out: dict[str, str | None] = {}
        for url in urls:
            entry = index.get(url) or {}
            out[url] = (cache_dir / entry["file"]).read_text() if entry.get("file") else None
        return out

    @staticmethod
    def page_text_browser(url: str) -> str | None:
        hp = _homepage()
        code = (f"async (page) => {{ await page.goto({json.dumps(url)}, {{waitUntil: 'domcontentloaded', timeout: 30000}}); "
                "await page.waitForTimeout(1500); return await page.evaluate(() => document.body ? "
                "document.body.innerText.slice(0, 600000) : ''); }")
        try:
            text = hp.h2p.browser_run(hp.BROWSER, [code], timeout=WEB_TIMEOUT)[0]
        except Exception:  # noqa: BLE001 - an unreachable page is recorded as not opened
            return None
        return text if isinstance(text, str) and len(text) >= 200 else None

    @staticmethod
    def page_text_http(url: str) -> str | None:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (research check; temper design)"})
        try:
            with urllib.request.urlopen(req, timeout=WEB_TIMEOUT) as resp:
                body = resp.read(4_000_000).decode(resp.headers.get_content_charset() or "utf-8", "replace")
        except Exception:  # noqa: BLE001
            return None
        if "html" in body[:2000].lower():
            body = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", body)
            body = html.unescape(re.sub(r"(?s)<[^>]+>", " ", body))
        return body if len(body) >= 200 else None

    # -- loop control

    def next(self, kind: str) -> dict:
        if kind not in ("check", "assemble"):
            raise ValueError("next is for check or assemble")
        path = self.dir / ("check.json" if kind == "check" else "assemble.json")
        if not path.exists():
            return {"status": "completed", "verdict": "ok", "skipped": True}
        last = load(path)
        verdict = "retry" if last.get("phase") == "final" and last.get("verdict") == "retry" else "ok"
        return {"status": "completed", "verdict": verdict, "attempt": last.get("attempt"),
                "problems": len(last.get("problems", []))}

    # -- category capture

    def capture(self) -> dict:
        inv = self.inv
        if not inv["research"]["category"]:
            return {"status": "completed", "skipped": True, "why": "no category scan needed"}
        pick_path = self.dir / "category" / "pick.json"
        pick = load(pick_path)
        fp = digest({"pick": pick})
        cached = self.cached("capture", fp)
        if cached:
            return cached
        out = self.dir / "category" / "shots"
        out.mkdir(parents=True, exist_ok=True)
        jobs = []
        for s in pick["sites"]:
            host = urllib.parse.urlparse(s["url"]).hostname
            if host == FIXTURE_HOST:
                if not self.fixture:
                    raise ValueError("fixture sites are for fixture runs only")
                page = Path(urllib.parse.urlparse(s["url"]).path).name
                if not (out / "site").is_dir():
                    shutil.copytree(_homepage().FIXTURE_SITE, out / "site")
                jobs.append({"name": s["id"], "path": f"site/{page}", "external": False})
            else:
                jobs.append({"name": s["id"], "url": s["url"], "external": True})
        results = {r["name"]: r for r in measure_pages(out, jobs)}
        sites = []
        for s in pick["sites"]:
            r = results.get(s["id"], {"ok": False, "error": "not measured"})
            item = {**s, "ok": bool(r.get("ok")), "usable": False}
            if r.get("ok"):
                facts = r["facts"]
                text = facts.get("text", "")
                blocked = facts.get("first_words", 0) < 12 or bool(BLOCKED.search(text[:3000]))
                item.update({"usable": not blocked, "blocked": blocked, "shot": f"research/category/shots/{s['id']}-first.png",
                             "levels": {k: v["level"] for k, v in axes.levels(facts).items()},
                             "why": {k: v["why"] for k, v in axes.levels(facts).items()},
                             "facts": axes.summary(facts)})
            else:
                item["error"] = r.get("error")
            sites.append(item)
        usable = [s for s in sites if s["usable"]]
        save(self.dir / "category" / "capture.json", {"category": pick["category"], "captured_at": now(), "sites": sites})
        lines = [f"# Category scan — {pick['category']}", "",
                 "First screens at 1440x900 with the five axes measured (density, type scale, colour energy, motion, "
                 "copy tone). Open the PNGs: look at what every site does (conventions users expect) and what none does.", ""]
        for s in sites:
            if s["usable"]:
                lines.append(f"## {s['id']} — {s['name']} ({s['kind']})")
                lines.append(f"{s['url']} · {s['shot']}")
                lines += [f"- {k}: {s['levels'][k]} ({s['why'][k]})" for k in axes.LEVELS]
                lines.append("")
            else:
                lines.append(f"## {s['id']} — not usable ({'blocked or empty page' if s.get('ok') else s.get('error')})")
                lines.append("")
        write(self.dir / "category" / "CATEGORY.md", "\n".join(lines))
        if len(usable) < MIN_CAPTURED:
            raise ValueError(f"only {len(usable)} category sites could be captured (need {MIN_CAPTURED}); "
                             "see research/category/capture.json")
        return self.receipt("capture", fp, {"status": "completed", "captured": len(usable), "picked": len(sites),
                                            "capture_path": "research/category/capture.json"})

    # -- assemble

    def assemble(self, phase: str) -> dict:
        if phase not in ("draft", "final"):
            raise ValueError("phase is draft or final")
        inv = self.inv
        r = inv["research"]
        if not r["direction"]:
            return {"status": "completed", "phase": phase, "verdict": "ok", "skipped": True,
                    "why": "the direction is approved; nothing to assemble"}
        dpath = self.dir / "direction.json"
        fp = digest({"phase": phase, "direction": file_digest(dpath), "users": file_digest(self.dir / "users.json"),
                     "capture": file_digest(self.dir / "category" / "capture.json"),
                     "rules": file_digest(Path(rc.__file__))})
        attempt = self.state["checks"].get(f"assemble-{phase}", 0)
        key = f"assemble-{phase}-{attempt}"
        prior = self.state["stages"].get(key)
        if prior and prior["fingerprint"] == fp:
            return {**prior["output"], "reused": True}
        if prior:
            attempt += 1
            key = f"assemble-{phase}-{attempt}"
        self.state["checks"][f"assemble-{phase}"] = attempt
        playbook = self.playbook()
        problems: list[str] = []
        direction = None
        if not dpath.is_file():
            problems.append("research/direction.json is missing")
        else:
            try:
                direction = load(dpath)
            except json.JSONDecodeError as exc:
                problems.append(f"research/direction.json is not JSON: {exc}")
        fixed = [p for p in inv["fixed"] if p in ("colour", "type")]
        if direction is not None:
            problems += rc.check_direction(direction, playbook, job=inv["job"], fixed=fixed, expect_count=inv["directions"])
            if r["category"]:
                problems += [f"category: {p}" for p in rc.check_category_read(direction.get("category") if isinstance(direction, dict) else None,
                                                                             self.captured(), marks_needed=inv["job"] == "logo")]
        research = None
        board = None
        if not problems:
            research = self.research_doc(inv, direction, playbook)
            problems += rc.check_research(research, playbook)
        if not problems:
            save(self.dir / "research.json", research)
            write(self.dir / "RESEARCH.md", research_md(research))
            board = self.board(research)
            if board["problems"]:
                raise ValueError("the research board fails its own check: " + "; ".join(board["problems"][:5]))
        verdict = "ok" if not problems else "retry"
        result = {"phase": phase, "attempt": attempt, "verdict": verdict, "problems": problems, "checked_at": now(),
                  "board": board}
        save(self.dir / "assemble.json", result)
        save(self.dir / f"assemble-{phase}-{attempt}.json", result)
        self.set_problems("director", problems)
        output = {"status": "completed", "phase": phase, "attempt": attempt, "verdict": verdict, "problems": len(problems),
                  "assemble_path": "research/assemble.json"}
        if verdict == "ok":
            output.update({"research_path": "research/RESEARCH.md", "board": "research/board/board.png",
                           "recommended": research["recommended"]["id"],
                           "questions": [{"id": "research", "question": (
                               "Confirm or correct the users and pick a direction: {decided_by (design; owner only for his own "
                               "words, with notes and source), direction (D1..), users confirm|correct, corrections (with "
                               "correct), reasons}. Read research/RESEARCH.md and the board first."),
                               "options": [f"{d['id']}: {d['name']} ({d['family']})" for d in research["directions"]]}]})
        return self.receipt(key, fp, output)

    def research_doc(self, inv: dict, direction: dict, playbook: dict) -> dict:
        users = load(self.dir / "users.json") if (self.dir / "users.json").is_file() else {"approved": True}
        capture = load(self.dir / "category" / "capture.json") if (self.dir / "category" / "capture.json").exists() else None
        sites = [{k: s.get(k) for k in ("id", "name", "url", "kind", "why", "shot", "levels")}
                 for s in (capture or {}).get("sites", []) if s.get("usable")]
        cat = direction.get("category") or {}
        create = ["DESIGN.md", "tokens.json"] + (["logo/"] if "logo" in inv["missing"] else [])
        return {"version": rc.VERSION, "product": inv["product"], "name": inv["name"], "job": inv["job"],
                "inventory": {k: inv[k] for k in ("status", "needed", "approved", "missing", "fixed", "forced", "audience")},
                "users": users, "contexts": rc.playbook_recommendations(playbook, direction["contexts"]),
                "category": {"name": (capture or {}).get("category"), "sites": sites, "expect": cat.get("expect", []),
                             "stand_out": cat.get("stand_out", []), "marks": cat.get("marks", [])},
                "directions": direction["candidates"], "recommended": direction["recommended"],
                "taste": direction.get("taste", {}),
                "assumptions": list(users.get("assumptions", []) if isinstance(users, dict) else []) + list(direction.get("assumptions", [])),
                "files_to_create": create, "fixed": inv["fixed"], "assembled_at": now()}

    def board(self, research: dict) -> dict:
        bdir = self.dir / "board"
        bdir.mkdir(parents=True, exist_ok=True)
        for s in research["category"]["sites"]:
            src = self.root / s["shot"]
            if src.is_file():
                (bdir / "shots").mkdir(exist_ok=True)
                shutil.copyfile(src, bdir / "shots" / Path(s["shot"]).name)
        write(bdir / "index.html", board_html(research))
        hp = _homepage()
        shots = hp.browser_jobs(bdir, bdir, [{"name": "board", "path": "index.html", "width": 1600, "height": 1000,
                                              "maxHeight": 6000, "freeze": True}])
        check = run_page_check(bdir, "index.html")
        problems = []
        if not shots or not shots[0].get("ok"):
            problems.append(f"the board did not render: {(shots or [{}])[0].get('error')}")
        if check.get("min_px", 0) < 16:
            problems.append(f"board text below 16 px ({check.get('min_px')} px: {check.get('small', [])[:3]})")
        if check.get("min_contrast", 0) < 4.5:
            problems.append(f"board text contrast below 4.5:1 ({check.get('min_contrast')}: {check.get('low', [])[:3]})")
        result = {"png": "research/board/board.png", "height": (shots or [{}])[0].get("height"),
                  "min_px": check.get("min_px"), "min_contrast": check.get("min_contrast"),
                  "text_elements": check.get("count"), "problems": problems}
        save(bdir / "check.json", result)
        return result

    # -- gate and decision

    def gate(self, raw: str) -> dict:
        inv = self.inv
        if inv["gate"] != "on":
            raise ValueError("the research gate is off for this run")
        ids = ([d["id"] for d in load(self.dir / "research.json")["directions"]] if inv["research"]["direction"]
               else ["keep"])
        answer = rc.gate_answer(raw, ids, self.deciders())
        seen = self.gate_inputs()
        fp = digest({"answer": answer, "answered": seen})  # the same answer to new research is a new answer
        cached = self.cached("gate", fp)
        if cached:
            return cached
        record = {**answer, "gate": "research", "gated": True, "answered": seen, "recorded_at": now()}
        save(self.dir / "gate.json", record)
        return self.receipt("gate", fp, {"status": "completed", "decided_by": answer["decided_by"],
                                         "direction": answer["direction"], "users": answer["users"]})

    def gate_inputs(self) -> dict:
        """What a research gate answer was given to: the research and the users profile, by sha256."""
        return {"research_sha256": file_digest(self.dir / "research.json"),
                "users_sha256": file_digest(self.dir / "USERS.md")}

    def decision(self) -> dict:
        inv = self.inv
        gate_path = self.dir / "gate.json"
        gate = load(gate_path) if gate_path.exists() else None
        if inv["gate"] == "on" and gate is None:
            raise ValueError("the research gate is on but has no answer")
        if gate is not None and gate.get("answered") not in (None, self.gate_inputs()):  # older records lack it
            raise ValueError("the research gate was answered before the research or users changed; answer it again")
        research = load(self.dir / "research.json") if inv["research"]["direction"] else None
        fp = digest({"gate": gate, "research": file_digest(self.dir / "research.json"),
                     "users": file_digest(self.dir / "USERS.md"), "inv": inv["status"]})
        cached = self.cached("decision", fp)
        if cached:
            return cached
        files = df.read_files(self.root / "design-files")
        chosen = None
        if research:
            pick = gate["direction"] if gate else research["recommended"]["id"]
            chosen = next(d for d in research["directions"] if d["id"] == pick)
        decision = {"status": inv["status"], "researched": bool(inv["research"]["any"]), "gated": bool(gate),
                    "decided_by": gate["decided_by"] if gate else None,
                    "direction": chosen["id"] if chosen else ("approved" if "direction" in inv["fixed"] else None),
                    "reasons": gate["reasons"] if gate else (research["recommended"]["reason"] if research else None),
                    "users": gate["users"] if gate else None, "corrections": gate.get("corrections", []) if gate else [],
                    "recorded_at": now()}
        if research and not gate:
            decision["note"] = "research gate off: the research's recommended direction, not a decision"
        fixed = fixed_constraints(inv, files, chosen)
        save(self.dir / "decision.json", decision)
        save(self.dir / "fixed.json", fixed)
        write(self.dir / "FOR_DESIGN.md", for_design_md(inv, files, research, chosen, decision, fixed,
                                                        (self.dir / "USERS.md").read_text() if (self.dir / "USERS.md").exists() else ""))
        return self.receipt("decision", fp, {"status": "completed", "design_status": inv["status"],
                                             "direction": decision["direction"], "decided_by": decision["decided_by"],
                                             "gated": decision["gated"], "for_design": "research/FOR_DESIGN.md",
                                             "fixed_parts": fixed["parts"]})

    # -- logo brief

    def logo_brief(self, raw: str) -> dict:
        brief = json.loads(raw) if raw.strip() else {}
        if not isinstance(brief, dict):
            raise ValueError("brief_json is an object")
        inv = self.inv
        if inv["job"] != "logo":
            raise ValueError("logo_brief is for logo jobs")
        if "logo" in inv["approved"]:  # stop before the paid logo stages, not at the save
            raise ValueError('the product\'s logo is approved and fixed; to replace it, run with "force": ["logo"]')
        decision = load(self.dir / "decision.json")
        fixed = load(self.dir / "fixed.json")
        fp = digest({"brief": brief, "decision": decision, "fixed": fixed,
                     "research": file_digest(self.dir / "research.json")})
        cached = self.cached("logo_brief", fp)
        if cached:
            return cached
        research = load(self.dir / "research.json") if (self.dir / "research.json").exists() else None
        out = dict(brief)
        if research:
            chosen = next(d for d in research["directions"] if d["id"] == decision["direction"])
            users = research["users"] if isinstance(research["users"], dict) else {}
            product = users.get("product") or {}
            # A logo stands for the product, so its context is the product's (role product),
            # not the page's; without one, the chosen direction's.
            out["context"] = next((x["id"] for x in research.get("contexts", []) if x.get("role") == "product"),
                                  chosen["context"])
            out["meaning"] = product.get("meaning", "")[:600]
            out.setdefault("audience", product.get("for_whom", "")[:400])
            rdir = self.dir / "logo-research"
            rdir.mkdir(parents=True, exist_ok=True)
            files = {}
            for s in research["category"]["sites"][:12]:
                src = self.root / s["shot"]
                if src.is_file():
                    shutil.copyfile(src, rdir / f"{s['id']}.png")
                    files[f"{s['id']}.png"] = df.sha256(rdir / f"{s['id']}.png")
            marks = research["category"].get("marks", [])
            lines = ["# Category marks (research step)", "",
                     f"Context: {out['context']}. Direction {chosen['id']}: {chosen['name']} ({chosen['family']}, "
                     f"context {chosen['context']}).",
                     f"Meaning: {product.get('meaning', '')}", "", "| Site | Mark family | What it looks like |", "|---|---|---|"]
            lines += [f"| {m['site']} | {m['family']} | {m['description']} |" for m in marks]
            fams: dict[str, int] = {}
            for m in marks:
                fams[m["family"]] = fams.get(m["family"], 0) + 1
            lines += ["", "Families in the category: " + ", ".join(f"{k} {v}" for k, v in sorted(fams.items())) +
                      ". A mark that stands out avoids the crowded family unless the meaning calls for it."]
            write(rdir / "comparison.md", "\n".join(lines) + "\n")
            files["comparison.md"] = df.sha256(rdir / "comparison.md")
            out["research"] = {"dir": str(rdir), "files": files}
        elif (self.dir / "category" / "capture.json").is_file():
            # Partial: users and direction are approved (no director ran), but the category was
            # captured. Context comes from the approved direction; the shots are pinned as they are.
            cap = load(self.dir / "category" / "capture.json")
            design_md = self.root / "design-files" / "DESIGN.md"
            text = design_md.read_text(encoding="utf-8") if design_md.is_file() else ""
            m = re.search(r"playbook contexts?: ([a-z0-9, -]+)", text)
            ids = [x.strip() for x in m.group(1).split(",") if x.strip()] if m else []
            ctx = next((x for x in ids if not x.startswith("marketing-")), ids[0] if ids else None)
            if ctx:
                out["context"] = ctx
            rdir = self.dir / "logo-research"
            rdir.mkdir(parents=True, exist_ok=True)
            files = {}
            rows = []
            for s in cap["sites"][:12]:
                src = self.root / s.get("shot", "")
                if s.get("usable") and src.is_file():
                    shutil.copyfile(src, rdir / f"{s['id']}.png")
                    files[f"{s['id']}.png"] = df.sha256(rdir / f"{s['id']}.png")
                    rows.append(f"| {s['name']} | {s['kind']} | {s['id']}.png |")
            lines = ["# Category first screens (research step)", "",
                     f"Context: {ctx or 'not recorded'} (from the approved direction in DESIGN.md).",
                     "The direction is approved, so no director described the marks: look at each shot.", "",
                     "| Site | Kind | Shot |", "|---|---|---|", *rows]
            write(rdir / "comparison.md", "\n".join(lines) + "\n")
            files["comparison.md"] = df.sha256(rdir / "comparison.md")
            out["research"] = {"dir": str(rdir), "files": files}
        if fixed.get("palette"):
            out["fixed_palette"] = fixed["palette"]
        # Check the merged brief here, so a missing or short brief_json fails at this step with
        # the contract's own message instead of later in the logo workflow.
        import logo_contracts
        logo_contracts.brief_contract(out, "fixture" if out.get("fictional") is True else "real")
        save(self.dir / "logo-brief.json", out)
        return self.receipt("logo_brief", fp, {"status": "completed", "brief": json.dumps(out, ensure_ascii=False),
                                               "context": out.get("context"), "fixed_palette": bool(out.get("fixed_palette")),
                                               "marks": len((research or {}).get("category", {}).get("marks", []))})

    # -- save design files after a final approval

    def save_files(self) -> dict:
        """After the workflow's final gate approves: the product's design files in design-files-out/ and
        registry-update.json (docs/design-files.md, Saving); the host's design_files.py apply files them."""
        if self.inv["job"] == "logo":
            return self.save_logo_files()
        return self.save_homepage_files()

    def final_decider(self, by: str) -> str:
        allowed = (rc.FIXTURE_DECIDER,) if self.inv["fixture_registry"] else rc.REAL_DECIDERS
        if by not in allowed:
            raise ValueError(f"the final gate was decided by {by}; this registry accepts {' or '.join(allowed)}")
        return by

    def save_homepage_files(self) -> dict:
        """Colour and type from the chosen concept, the other token parts from the built page's CSS."""
        packet = self.root / "homepage"
        final_path = packet / "final.json"
        if not final_path.exists():
            raise ValueError("no final approval yet (homepage/final.json)")
        final = load(final_path)
        if final.get("verdict") != "approve":
            raise ValueError("the final gate did not approve")
        by = self.final_decider(final["decided_by"])
        direction = load(packet / "direction.json")
        spec = load(packet / "concepts" / "concepts.json")
        concept = next(c for c in spec["concepts"] if c["id"] == direction["concept"])
        fp = digest({"final": final, "direction": direction, "concept": concept,
                     "research": file_digest(self.dir / "research.json"), "site": site_css_digest(packet / "site")})
        cached = self.cached("save", fp)
        if cached:
            return cached
        said = {"words": final.get("notes", ""), "source": final.get("source", "")} if by == "owner" \
            else {"reasons": final.get("reasons", "")}
        return self.receipt("save", fp, self.write_design_files(
            by, said, tokens_from_run(concept, packet / "site"), f"Built as concept {concept['id']}: {concept['name']}."))

    def save_logo_files(self) -> dict:
        """The approved logo (its exports and BRAND.md), the palette chosen with it, and the research's users and
        direction. An approved palette stays as it was, and the logo may use only its colours."""
        inv = self.inv
        packet = self.root / "logo"
        manifest = load(packet / "manifest.json") if (packet / "manifest.json").is_file() else {}
        state = load(packet / "state.json") if (packet / "state.json").is_file() else {}
        final = state.get("final_approval") or {}
        if not final or not (manifest.get("final_approved") or {}).get("approved"):
            raise ValueError("no final approval yet (logo/manifest.json)")
        if final.get("decision") != "approve":
            raise ValueError("the final gate did not approve")
        by = self.final_decider(final["decided_by"])
        if "logo" in inv["approved"]:
            raise ValueError('the product\'s logo is approved and fixed; to replace it, run with "force": ["logo"]')
        exports = [e for e in manifest.get("exports", []) if e.get("kind") in ("svg", "png")]
        if not exports:
            raise ValueError("the approved logo lists no exports (logo/manifest.json)")
        logo_tokens = load(packet / "tokens.json")
        concept = (load(packet / "selected.json").get("concept") or {}) if (packet / "selected.json").is_file() else {}
        fp = digest({"final": final, "artifact": manifest.get("artifact_hash"), "exports": exports, "tokens": logo_tokens,
                     "research": file_digest(self.dir / "research.json")})
        cached = self.cached("save", fp)
        if cached:
            return cached
        files: dict[str, Path] = {}
        for e in exports:
            src = (self.root / str(e.get("path", ""))).resolve()
            if not src.is_relative_to(packet.resolve()) or not src.is_file():
                raise ValueError(f"logo export {e.get('path')} is missing")
            if e.get("sha256") and file_digest(src) != e["sha256"]:
                raise ValueError(f"logo export {e['path']} changed after the final gate")
            base = re.sub(r"[^a-z0-9]+", "-", str(e.get("board") or src.stem).lower()).strip("-")[:60] or "logo"
            name, n = f"logo/{base}.{e['kind']}", 2
            while name in files:
                name, n = f"logo/{base}-{n}.{e['kind']}", n + 1
            files[name] = src
        if (packet / "BRAND.md").is_file():
            files["logo/BRAND.md"] = packet / "BRAND.md"
        palette = {role: str(v).upper() for role, v in (logo_tokens.get("sRGB") or {}).items() if df.HEX.match(str(v))}
        new_tokens: dict[str, dict] = {}
        if "colour" in inv["approved"]:
            approved = {h.upper() for h in df.token_hexes((df.read_files(self.root / "design-files") or {}).get("tokens"),
                                                          ("colour",))}
            outside = sorted(set(palette.values()) - approved)
            if outside:
                raise ValueError("the logo uses colours outside the approved palette: " + ", ".join(outside))
        elif palette:
            new_tokens["colour"] = {"$type": "color", **{role.replace("_", "-"): df.color_token(
                hexv, f"{role.replace('_', ' ')} (chosen with the logo)") for role, hexv in palette.items()}}
        lines = ["Files: " + ", ".join(files)]
        if concept.get("name"):
            lines.append(f"Mark: {concept['name']} ({concept.get('family', 'mark')}). "
                         + " ".join(str(concept.get("idea", "")).split())[:300])
        font = logo_tokens.get("font") or {}
        if font.get("family"):
            lines.append(f"Wordmark font: {font['family']} {font.get('weight', '')}".rstrip()
                         + (f" ({font['licence']})." if font.get("licence") else "."))
        if logo_tokens.get("clear_space_unit"):
            lines.append(f"Clear space: {logo_tokens['clear_space_unit']}.")
        sizes = [f"symbol {logo_tokens['minimum_symbol_px']} px" if logo_tokens.get("minimum_symbol_px") else "",
                 f"lockup {logo_tokens['proposed_minimum_lockup_px']} px" if logo_tokens.get("proposed_minimum_lockup_px") else ""]
        if any(sizes):
            lines.append("Smallest sizes: " + ", ".join(s for s in sizes if s) + ".")
        if "logo/BRAND.md" in files:
            lines.append("Variants, use and limits: logo/BRAND.md.")
        lines.append("Publishing the logo or putting it in a live product needs its own approval.")
        said = {"words": final.get("reason", ""), "source": final.get("source", "")} if by == "owner" \
            else {"reasons": final.get("reason", "")}
        built = f"Built as logo concept {concept.get('id', '?')}: {concept.get('name', 'the approved logo')}."
        return self.receipt("save", fp, self.write_design_files(by, said, new_tokens, built,
                                                                logo={"files": files, "lines": lines}))

    def write_design_files(self, by: str, said: dict, new_tokens: dict[str, dict], built: str,
                           logo: dict | None = None) -> dict:
        """design-files-out/: parts the product had approved are copied unchanged; every part this run made is
        approved by the final gate's decided_by on today's date. The files pass their own check first.

        said: the final gate's reasons, or the owner's words with their source. built: what the direction was
        built as. logo: {files: {name in the folder: source path}, lines: the Logo section} when this run made
        the product's logo (it replaces an earlier one; apply keeps that under .history/)."""
        inv = self.inv
        date = dt.datetime.now(dt.UTC).astimezone().date().isoformat()
        files = df.read_files(self.root / "design-files")
        research = load(self.dir / "research.json") if (self.dir / "research.json").exists() else None
        decision = load(self.dir / "decision.json")
        out = self.root / "design-files-out"
        if out.exists():
            shutil.rmtree(out)
        out.mkdir(parents=True)
        approval = {"approved_by": by, "date": date}
        if by == "owner":
            approval.update({"words": said.get("words", ""), "source": said.get("source", "")})
        else:
            approval["reasons"] = (f"final gate of the {inv['job']} run: {' '.join(str(said.get('reasons', '')).split())}")[:400]
        old_tokens = (files or {}).get("tokens") or {}
        # The run remakes only what it researched or designed: users and direction from the research, token
        # parts from new_tokens, the logo. Every other part approved before the run stays exactly as it was,
        # including parts this job does not use (a logo run keeps an approved type scale).
        # An approved part is replaced only when Design or the owner forced it to be researched again.
        prior = {p: st for p, st in ((files or {}).get("parts") or {}).items() if st and st.get("status") == "approved"}
        open_parts = {p for p in df.PARTS if p not in prior or p in (inv.get("forced") or [])}
        remade = {p for p in df.TOKEN_PARTS if p in new_tokens} & open_parts
        if research and isinstance(research["users"], dict) and research["users"].get("groups"):
            remade |= {"users"} & open_parts
        if research:
            remade |= {"direction"} & open_parts
        if logo:
            remade |= {"logo"} & open_parts
        kept = {p: {"status": "approved", "approved_by": st["approved_by"], "date": st["date"]}
                for p, st in prior.items() if p not in remade}
        tokens: dict[str, Any] = {"$description": f"{inv['name']} design tokens (DTCG 2025.10), saved by the research "
                                                  f"step after the final gate of a {inv['job']} run.",
                                  "$extensions": {df.EXT: {"product": inv["product"], "format": df.FORMAT}}}
        status: dict[str, dict] = {}
        parts_update: dict[str, dict] = {}
        for part in df.TOKEN_PARTS:
            if part in kept:
                tokens[part] = old_tokens[part]  # approved parts are copied unchanged
                status[part] = kept[part]
            elif part in remade:
                st = {"status": "approved", **{k: approval[k] for k in ("approved_by", "date")}}
                tokens[part] = df.token_group(part, new_tokens[part], st)
                status[part] = st
                parts_update[part] = st
        save(out / "tokens.json", tokens)
        raw: dict[str, str] = {}
        sections = (files or {}).get("design", {}).get("sections", {}) if files else {}
        for part, title in df.TITLES.items():
            if part in kept and title in sections:
                raw[title] = sections[title].strip("\n")
                status[part] = kept[part]
        users_lines, direction_lines = [], []
        if "users" in remade:
            users_lines = users_section(research["users"], decision)
            st = {"status": "approved", "approved_by": by, "date": date}
            status["users"], parts_update["users"] = st, st
        if "direction" in remade:
            chosen = next(d for d in research["directions"] if d["id"] == decision["direction"])
            direction_lines = direction_section(chosen, research, built)
            st = {"status": "approved", "approved_by": by, "date": date}
            status["direction"], parts_update["direction"] = st, st
        logo_lines: list[str] = []
        if logo:
            for name, src in logo["files"].items():
                (out / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(src, out / name)
            logo_lines = list(logo["lines"])
            st = {"status": "approved", "approved_by": by, "date": date}
            status["logo"], parts_update["logo"] = st, st
        elif "logo" in kept and (self.root / "design-files" / "logo").is_dir():
            shutil.copytree(self.root / "design-files" / "logo", out / "logo")
        for part in ("logo", "library"):
            status.setdefault(part, None)
        approvals = []
        old_approvals = (files or {}).get("design", {}).get("approvals", {}) if files else {}
        for part in df.PARTS:
            st = status.get(part)
            if not st or st.get("status") != "approved":
                continue
            if part in kept:
                approvals.append({"part": part, **old_approvals[part]})
            else:
                approvals.append({"part": part, **approval})
        model = {"name": inv["name"], "product": inv["product"], "updated": date,
                 "intro": (f"Saved by the research step after the final gate of a {inv['job']} run "
                           f"(decided_by {by}). Approved parts were copied unchanged."),
                 "status": status, "users_lines": users_lines, "direction_lines": direction_lines,
                 "logo_lines": logo_lines, "approvals": approvals, "raw": raw}
        write(out / "DESIGN.md", df.render_design_md(model))
        found = df.read_files(out)
        if found is None or found["problems"]:
            raise ValueError("the saved design files fail their check: " + "; ".join((found or {"problems": ["none"]})["problems"][:6]))
        save(out / "registry-update.json", {"product": inv["product"], "parts": parts_update, "from_run": self.root.name,
                                            "decided_by": by, "saved_at": now()})
        return {"status": "completed", "saved": "design-files-out", "approved_by": by, "parts": sorted(parts_update),
                "kept": sorted(kept)}


# ---------------------------------------------------------------- browser measures


PAGE_CHECK = r"""async (page) => {
  const A = __ARGS__;
  await page.setViewportSize({width: 1600, height: 1000});
  await page.goto(A.url, {waitUntil: 'networkidle', timeout: 20000});
  return await page.evaluate(() => {
    const parse = (c) => { const m = c.match(/rgba?\(([^)]+)\)/); if (!m) return null;
      const p = m[1].split(/[ ,\/]+/).filter(Boolean).map(Number); return {r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1}; };
    const lum = (c) => { const f = (v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); };
      return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b); };
    const bg = (el) => { for (let e = el; e; e = e.parentElement) { const c = parse(getComputedStyle(e).backgroundColor);
      if (c && c.a > 0.95) return c; } return {r: 255, g: 255, b: 255, a: 1}; };
    let minPx = 999, minC = 99, count = 0; const small = [], low = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const seen = new Set();
    while (walker.nextNode()) {
      const t = walker.currentNode; if (!t.textContent.trim()) continue;
      const el = t.parentElement; if (seen.has(el)) continue; seen.add(el);
      const cs = getComputedStyle(el); if (cs.visibility === 'hidden' || cs.display === 'none') continue;
      const px = parseFloat(cs.fontSize); const fg = parse(cs.color); const b = bg(el);
      const l1 = lum(fg), l2 = lum(b); const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
      count++; if (px < minPx) minPx = px; if (ratio < minC) minC = ratio;
      if (px < 16) small.push(t.textContent.trim().slice(0, 40) + ' ' + px);
      if (ratio < 4.5) low.push(t.textContent.trim().slice(0, 40) + ' ' + ratio.toFixed(2));
    }
    return {min_px: minPx, min_contrast: Math.round(minC * 100) / 100, count, small, low};
  });
}"""


def run_page_check(root: Path, page: str) -> dict:
    hp = _homepage()
    host = hp.SERVE_HOST or urllib.parse.urlparse(hp.BROWSER).hostname or "playwright-mcp"
    base, srv = hp.h2p.serve(root, root, host)
    try:
        return hp.h2p.browser_run(hp.BROWSER, [PAGE_CHECK.replace("__ARGS__", json.dumps({"url": f"{base}/{page}"}))])[0]
    finally:
        srv.shutdown()


def measure_pages(root: Path, jobs: list[dict], timeout: float = 120) -> list[dict]:
    """The five-axis facts of pages (local paths under root, or outside URLs), one browser session per page.

    First screens land in root/<name>-first.png."""
    hp = _homepage()
    host = hp.SERVE_HOST or urllib.parse.urlparse(hp.BROWSER).hostname or "playwright-mcp"
    base, srv = hp.h2p.serve(root, root, host)
    try:
        results = []
        for job in jobs:
            j = dict(job)
            if not j.get("external"):
                j["url"] = base + "/" + j["path"].lstrip("/")
            try:
                results += hp.h2p.browser_run(hp.BROWSER, [axes.measure_code(base, [j])], timeout=timeout)[0]
            except Exception as exc:  # noqa: BLE001 - a failed page is recorded, never fatal on its own
                results.append({"name": j["name"], "ok": False, "error": f"{exc.__class__.__name__}: {str(exc)[:200]}"})
        return results
    finally:
        srv.shutdown()


# ---------------------------------------------------------------- documents


def esc(text: Any) -> str:
    return html.escape(str(text), quote=True)


def research_md(r: dict) -> str:
    users = r["users"] if isinstance(r["users"], dict) else {}
    product = users.get("product") or {}
    out = [f"# Research — {r['name']} ({r['job']})", "",
           f"Design files: {r['inventory']['status']}; fixed: {', '.join(r['fixed']) or 'none'}; "
           f"to research: {', '.join(r['inventory']['missing']) or 'none'}.", ""]
    if product:
        out += ["## The product", f"- What: {product.get('what')}", f"- For whom: {product.get('for_whom')}",
                f"- Value: {product.get('value')}", f"- Meaning: {product.get('meaning')}", ""]
    if users.get("claims"):
        out += [rc.users_md(users, title="Users").replace("# Users", "## Users", 1), ""]
    out += ["## Context fit (playbook)"]
    for c in r["contexts"]:
        rec = c["recommendations"]
        out += [f"### {c['id']} — {c['name']} (role {c['role']})", f"Why: {c['why']}",
                f"- Styles preferred: {'; '.join(rec['styles'].get('preferred', []))}",
                f"- Styles acceptable: {'; '.join(rec['styles'].get('acceptable', [])) or 'none'}"]
        for k in ("density", "depth", "motion", "colour", "type", "imagery"):
            out.append(f"- {k.capitalize()}: {rec.get(k)}")
        out += [f"- Avoid: {'; '.join(rec.get('avoid', []))}", f"- Trust signals: {'; '.join(rec.get('trust_signals', []))}",
                f"- Evidence: {', '.join(rec.get('evidence', []))} (confidence {rec.get('confidence', '?')})", ""]
    cat = r["category"]
    if cat.get("sites"):
        out += [f"## Category scan — {cat.get('name')}", "", "| Site | Kind | Density | Type | Colour | Motion | Tone |",
                "|---|---|---|---|---|---|---|"]
        out += [f"| {s['name']} ({s['url']}) | {s['kind']} | " + " | ".join(s["levels"][k] for k in axes.LEVELS) + " |"
                for s in cat["sites"]]
        out += ["", "Users will expect (follow):"] + [f"- {e['text']} ({', '.join(e['sites'])})" for e in cat["expect"]]
        out += ["", "Where to stand out:"] + [f"- {s['text']} — {s['why']}" for s in cat["stand_out"]]
        if cat.get("marks"):
            out += ["", "Marks:"] + [f"- {m['site']}: {m['family']} — {m['description']}" for m in cat["marks"]]
        out.append("")
    out += ["## Direction candidates"]
    for d in r["directions"]:
        out += [f"### {d['id']} — {d['name']}", f"Context {d['context']}; family \"{d['family']}\".", f"Why: {d['why']}",
                "Axes: " + ", ".join(f"{k} {d['axes'][k]}" for k in axes.LEVELS),
                f"Palette: {d['palette']}. Type: {d['type']}.",
                "Principles: " + "; ".join(d["principles"]), "Do: " + "; ".join(d["do"]), "Don't: " + "; ".join(d["dont"]),
                "Follow: " + "; ".join(d["follow"]), "Differentiate: " + "; ".join(d["differentiate"]),
                "Evidence: " + ", ".join(d["evidence"]), ""]
    out += [f"## Recommendation: {r['recommended']['id']}", r["recommended"]["reason"], ""]
    taste = r.get("taste") or {}
    out += ["## Owner's taste (a bias, kept apart from the evidence)",
            f"{taste.get('note', 'none')} ({', '.join(taste.get('ids', [])) or 'no ids'})", ""]
    out += ["## Assumptions to confirm"] + [f"- {a}" for a in r["assumptions"]] + [""]
    out += ["## Design files to create", ", ".join(r["files_to_create"]) + " (draft until the final gate approves them)", ""]
    return "\n".join(out)


def board_html(r: dict) -> str:
    users = r["users"] if isinstance(r["users"], dict) else {}
    product = users.get("product") or {}
    groups = users.get("groups", [])
    claims = {c["id"]: c for c in users.get("claims", []) if isinstance(c, dict)}
    primary = next((g for g in groups if g.get("role") == "primary"), groups[0] if groups else None)
    facts = [claims[c]["text"] for c in (primary or {}).get("claims", []) if claims.get(c, {}).get("status") == "sourced"][:6]
    css = f"""
*{{box-sizing:border-box}}body{{margin:0;background:{BOARD_PAPER};color:{BOARD_INK};font:18px/1.45 system-ui,sans-serif}}
main{{width:1600px;padding:48px 56px}}h1{{font-size:40px;line-height:1.15;margin:0 0 6px}}h2{{font-size:24px;margin:0 0 12px}}
h3{{font-size:20px;margin:0 0 8px}}p,li{{font-size:18px;margin:0 0 6px}}.muted{{color:{BOARD_MUTED}}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:28px;margin-top:28px}}.panel{{background:{BOARD_PANEL};border:1px solid {BOARD_LINE};border-radius:12px;padding:22px 24px}}
.dirs{{display:grid;grid-template-columns:repeat({max(1, len(r['directions']))},1fr);gap:20px;margin-top:28px}}
.dir{{border:2px solid {BOARD_LINE};border-radius:12px;padding:20px}}.dir.rec{{border-color:{BOARD_INK}}}
.axes{{display:grid;grid-template-columns:auto 1fr;gap:2px 12px;margin:10px 0}}.shots{{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;margin-top:12px}}
.shots figure{{margin:0}}.shots img{{width:100%;border:1px solid {BOARD_LINE};border-radius:6px}}.shots figcaption{{font-size:16px}}
ul{{padding-left:22px;margin:6px 0}}.tag{{display:inline-block;border:1px solid {BOARD_INK};border-radius:999px;padding:2px 12px;font-size:16px;margin:0 6px 6px 0}}
"""
    parts = [f"<!doctype html><html lang='en'><head><meta charset='utf-8'><title>Research board — {esc(r['name'])}</title>"
             f"<style>{css}</style></head><body><main>",
             f"<h1>Research — {esc(r['name'])}</h1>",
             f"<p class='muted'>{esc(r['job'])} · design files {esc(r['inventory']['status'])} · fixed: "
             f"{esc(', '.join(r['fixed']) or 'none')} · recommended {esc(r['recommended']['id'])}</p>",
             "<div class='grid'><section class='panel'><h2>Who it is for</h2>"]
    if product:
        parts.append(f"<p><strong>{esc(product.get('what'))}</strong></p><p>{esc(product.get('value'))}</p>")
    if primary:
        parts.append(f"<h3>{esc(primary['name'])} (primary)</h3><p>{esc(primary['summary'])}</p>")
        parts.append("<ul>" + "".join(f"<li>{esc(f)}</li>" for f in facts) + "</ul>")
    others = [g for g in groups if g is not primary]
    if others:
        parts.append("<p class='muted'>Also: " + esc("; ".join(f"{g['name']} ({g['role']})" for g in others)) + "</p>")
    parts.append("</section><section class='panel'><h2>Context fit</h2>")
    for c in r["contexts"]:
        rec = c["recommendations"]
        parts.append(f"<h3>{esc(c['name'])} <span class='muted'>({esc(c['id'])}, {esc(c['role'])})</span></h3>"
                     f"<p>{esc(c['why'])}</p><p class='muted'>Density: {esc(rec.get('density'))}</p>"
                     f"<p class='muted'>Avoid: {esc('; '.join(rec.get('avoid', [])[:3]))}</p>"
                     f"<p class='muted'>Evidence {esc(', '.join(rec.get('evidence', [])[:6]))}</p>")
    parts.append("</section></div>")
    cat = r["category"]
    if cat.get("sites"):
        parts.append(f"<section class='panel' style='margin-top:28px'><h2>Category: {esc(cat.get('name'))}</h2><div class='shots'>")
        for s in cat["sites"][:10]:
            parts.append(f"<figure><img src='shots/{esc(Path(s['shot']).name)}' alt='{esc(s['name'])} first screen'>"
                         f"<figcaption>{esc(s['name'])}</figcaption></figure>")
        parts.append("</div><div class='grid'><div><h3>Users will expect</h3><ul>" +
                     "".join(f"<li>{esc(e['text'])}</li>" for e in cat["expect"][:6]) + "</ul></div><div><h3>Stand out by</h3><ul>" +
                     "".join(f"<li>{esc(s['text'])}</li>" for s in cat["stand_out"][:5]) + "</ul></div></div></section>")
    parts.append("<div class='dirs'>")
    for d in r["directions"]:
        rec = " rec" if d["id"] == r["recommended"]["id"] else ""
        parts.append(f"<section class='dir{rec}'><h2>{esc(d['id'])} · {esc(d['name'])}</h2>"
                     f"<p><span class='tag'>{esc(d['family'])}</span><span class='tag'>{esc(d['context'])}</span></p>"
                     f"<p>{esc(d['why'])}</p><div class='axes'>" +
                     "".join(f"<span class='muted'>{esc(k.replace('_', ' '))}</span><strong>{esc(d['axes'][k])}</strong>" for k in axes.LEVELS) +
                     f"</div><p><strong>Palette:</strong> {esc(d['palette'])}</p><p><strong>Type:</strong> {esc(d['type'])}</p>"
                     "<ul>" + "".join(f"<li>{esc(p)}</li>" for p in d["principles"][:4]) + "</ul>"
                     f"<p class='muted'>Don't: {esc('; '.join(d['dont'][:3]))}</p></section>")
    parts.append("</div>")
    parts.append(f"<section class='panel' style='margin-top:28px'><h2>Recommended: {esc(r['recommended']['id'])}</h2>"
                 f"<p>{esc(r['recommended']['reason'])}</p>")
    if r["assumptions"]:
        parts.append("<h3>Assumptions to confirm</h3><ul>" + "".join(f"<li>{esc(a)}</li>" for a in r["assumptions"][:6]) + "</ul>")
    taste = r.get("taste") or {}
    if taste.get("note"):
        parts.append(f"<p class='muted'>Owner's taste (a bias, not evidence): {esc(taste['note'])}</p>")
    parts.append("</section></main></body></html>")
    return "\n".join(parts)


def fixed_constraints(inv: dict, files: dict | None, chosen: dict | None) -> dict:
    tokens = (files or {}).get("tokens") or {}
    palette = None
    colours: list[str] = []
    if "colour" in inv["fixed"]:
        group = tokens.get("colour", {})
        palette = {name: tok["$value"]["hex"].upper() for name, tok, in
                   ((k, v) for k, v in group.items() if not k.startswith("$") and isinstance(v, dict) and isinstance(v.get("$value"), dict))}
        colours = sorted({h.upper() for h in df.token_hexes(tokens)})
    fonts = df.token_fonts(tokens) if "type" in inv["fixed"] else []
    axes_target = dict(chosen["axes"]) if chosen else approved_axes(files)
    return {"status": inv["status"], "parts": inv["fixed"], "palette": palette, "colours": colours, "fonts": fonts,
            "axes": axes_target, "direction": chosen["id"] if chosen else None,
            "tokens_file": "design-files/tokens.json" if tokens else None}


AXES_LINE = re.compile(r"^Axes: (.+)$", re.M)


def approved_axes(files: dict | None) -> dict | None:
    """The five axes an approved Direction section records ('Axes: density high, type_scale compact, ...')."""
    body = (files or {}).get("design", {}).get("sections", {}).get("Direction", "") if files else ""
    m = AXES_LINE.search(body or "")
    if not m:
        return None
    got = {}
    for item in m.group(1).split(","):
        bits = item.strip().split()
        if len(bits) == 2 and bits[0] in axes.LEVELS and bits[1] in axes.LEVELS[bits[0]]:
            got[bits[0]] = bits[1]
    return got if set(got) == set(axes.LEVELS) else None


def for_design_md(inv: dict, files: dict | None, research: dict | None, chosen: dict | None, decision: dict,
                  fixed: dict, users_md_text: str) -> str:
    out = [f"# For design — {inv['name']} ({inv['job']})", "",
           "Read this before writing copy or drawing. It is what the research step decided (or what the approved "
           "design files say). Follow it; do not restyle approved parts.", "",
           f"Design files: {inv['status']}. Fixed (approved): {', '.join(inv['fixed']) or 'none'}."]
    if decision.get("researched"):
        out.append(f"Research ran; direction {decision['direction']} "
                   + (f"chosen at the research gate (decided_by {decision['decided_by']})." if decision["gated"]
                      else "recommended (research gate off)."))
    out.append("")
    out += ["## Who this is for", users_md_text.split("\n", 1)[1].strip() if users_md_text else "See design-files/DESIGN.md.", ""]
    if decision.get("corrections"):
        out += ["## Corrections from the research gate (they win over the profile above)"] + [f"- {c}" for c in decision["corrections"]] + [""]
    if chosen:
        out += [f"## Direction {chosen['id']}: {chosen['name']}", f"Family: {chosen['family']} (playbook context {chosen['context']}).",
                f"Why: {chosen['why']}", "Principles:"] + [f"- {p}" for p in chosen["principles"]]
        out += ["Do:"] + [f"- {p}" for p in chosen["do"]] + ["Don't:"] + [f"- {p}" for p in chosen["dont"]]
        out += ["Keep these category conventions:"] + [f"- {p}" for p in chosen["follow"]]
        out += ["Stand out by:"] + [f"- {p}" for p in chosen["differentiate"]]
        out += [f"Palette idea: {chosen['palette']}", f"Type idea: {chosen['type']}", ""]
        ctx = next((c for c in research["contexts"] if c["id"] == chosen["context"]), None)
        page_ctx = next((c for c in research["contexts"] if c["role"] == "page"), None)
        for c in [x for x in (page_ctx, ctx) if x] if page_ctx is not ctx else [ctx]:
            rec = c["recommendations"]
            out += [f"## Playbook: {c['name']} ({c['id']})"] + [f"- {k}: {rec.get(k)}" for k in ("density", "depth", "motion", "colour", "type", "imagery")]
            out += [f"- avoid: {'; '.join(rec.get('avoid', []))}", f"- trust signals: {'; '.join(rec.get('trust_signals', []))}", ""]
    elif files:
        body = files["design"]["sections"].get("Direction", "")
        out += ["## Direction (approved)", body.strip(), ""]
    if fixed.get("axes"):
        out += ["## Five audience targets (measured on every concept; a concept must hit at least 4 of 5)"]
        out += [f"- {k}: {fixed['axes'][k]} — {axes.TARGETS[k][fixed['axes'][k]]}" for k in axes.LEVELS] + [""]
    if fixed.get("palette"):
        out += ["## Fixed palette (approved; use these exact hex values for every palette role, and no other colours)"]
        out += [f"- {k}: {v}" for k, v in fixed["palette"].items()] + [""]
        limits = text_limits(fixed["palette"])
        if limits:
            out += ["Text on these approved colours (WCAG 1.4.3: 4.5:1, or 3:1 for large text; axe checks the page):"]
            out += limits + [""]
    if fixed.get("fonts"):
        out += ["## Fixed type (approved; use exactly these families)"] + [f"- {f}" for f in fixed["fonts"]] + [""]
    if files and "logo" in inv["fixed"]:
        out += ["## Logo (approved)", "Use the files in design-files/logo/ as they are; see design-files/DESIGN.md (Logo).", ""]
    return "\n".join(out)


def contrast(a: str, b: str) -> float:
    """WCAG 2.2 contrast ratio of two #RRGGBB colours, rounded to 2 places."""
    def lum(h: str) -> float:
        rgb = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]
    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return round((hi + 0.05) / (lo + 0.05), 2)


def text_limits(palette: dict) -> list[str]:
    """One line per approved colour that no other approved colour reaches 4.5:1 on: there only large
    text (3:1) or no text, because approved colours are fixed and cannot be darkened for contrast."""
    colours = sorted({str(v).upper() for v in palette.values()})
    lines = []
    for role, value in palette.items():
        bg = str(value).upper()
        others = [c for c in colours if c != bg]
        if not others:
            continue
        best = max(others, key=lambda c: contrast(c, bg))
        ratio = contrast(best, bg)
        if ratio < 4.5:
            use = ("only large text on it (24 px, or 19 px bold)" if ratio >= 3 else "no text on it")
            lines.append(f"- {role} {bg}: no approved colour reaches 4.5:1 on it (best {best}, {ratio}:1): {use}")
    return lines


def users_section(users: dict, decision: dict) -> list[str]:
    claims = {c["id"]: c for c in users.get("claims", [])}
    lines = []
    for g in users.get("groups", []):
        lines += [f"### {g['name']}"]
        if g.get("aliases"):
            lines.append("Also called: " + ", ".join(g["aliases"]))
        lines.append(f"Role: {g['role']}. {g['summary']}")
        for cid in g.get("claims", []):
            c = claims.get(cid)
            if c and c.get("status") in ("sourced", "assumption"):
                lines.append(f"- {c['text']} [{rc.source_label(c)}]")
        lines.append("")
    if decision.get("corrections"):
        lines += ["Corrections from the research gate:"] + [f"- {c}" for c in decision["corrections"]]
    return lines


def direction_section(chosen: dict, research: dict, built: str) -> list[str]:
    ctxs = ", ".join(c["id"] for c in research["contexts"])
    return [f"Name: {chosen['name']} ({chosen['id']}); family: {chosen['family']}; playbook contexts: {ctxs}.",
            "Axes: " + ", ".join(f"{k} {chosen['axes'][k]}" for k in axes.LEVELS),
            f"Why: {chosen['why']}", built,
            "Principles:"] + [f"- {p}" for p in chosen["principles"]] + \
           ["Do:"] + [f"- {p}" for p in chosen["do"]] + ["Don't:"] + [f"- {p}" for p in chosen["dont"]] + \
           ["Evidence: " + ", ".join(chosen["evidence"])]


CSS_VAR = re.compile(r"--([A-Za-z0-9_-]+)\s*:\s*([^;}{]+)[;}]")


def site_css_text(site: Path) -> str:
    texts = []
    for p in sorted(Path(site).glob("*.css")) + sorted(Path(site).glob("*.html")):
        texts.append(p.read_text(errors="replace"))
    return "\n".join(texts)


def site_css_digest(site: Path) -> str:
    return digest(site_css_text(site)) if Path(site).exists() else ""


def _dim(value: str) -> dict | None:
    m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)(px|rem)\s*", value)
    return {"value": float(m.group(1)) if "." in m.group(1) else int(m.group(1)), "unit": m.group(2)} if m else None


def tokens_from_run(concept: dict, site: Path) -> dict[str, dict]:
    """Token groups from the chosen concept (colour, type) and the built page's CSS custom properties."""
    out: dict[str, dict] = {}
    palette = concept.get("palette") or {}
    colour = {}
    for role in ROLE_ORDER:
        hexv = str(palette.get(role, ""))
        if df.HEX.match(hexv):
            colour[role.replace("_", "-")] = df.color_token(hexv.upper(), f"{role.replace('_', ' ')} (concept {concept['id']})")
    if colour:
        out["colour"] = {"$type": "color", **colour}
    fonts = concept.get("fonts") or {}
    typ: dict[str, Any] = {}
    for role in ("display", "text"):
        face = fonts.get(role) or {}
        if face.get("family"):
            typ[f"{role}-family"] = {"$type": "fontFamily", "$value": face["family"]}
            for w in face.get("weights", [])[:4]:
                if isinstance(w, int):
                    typ[f"{role}-weight-{w}"] = {"$type": "fontWeight", "$value": w}
    if typ:
        out["type"] = typ
    spacing, radius, motion, elevation = {}, {}, {}, {}
    for name, value in CSS_VAR.findall(site_css_text(site)) if Path(site).exists() else []:
        key = re.sub(r"[^a-z0-9-]", "-", name.lower()).strip("-")[:40]
        v = value.strip()
        if re.search(r"space|gap|pad|gutter|margin", key) and _dim(v):
            spacing.setdefault(key, {"$value": _dim(v)})
        elif re.search(r"radius|round", key) and _dim(v):
            radius.setdefault(key, {"$value": _dim(v)})
        elif re.search(r"dur|speed|motion|time", key) and re.fullmatch(r"\d+(?:\.\d+)?(ms|s)", v):
            num = float(v[:-2] if v.endswith("ms") else v[:-1])
            motion.setdefault(key, {"$type": "duration", "$value": {"value": int(num) if num.is_integer() else num,
                                                                    "unit": "ms" if v.endswith("ms") else "s"}})
        elif re.search(r"ease", key) and (m := re.fullmatch(r"cubic-bezier\(([^)]+)\)", v)):
            nums = [float(x) for x in m.group(1).split(",")]
            if len(nums) == 4 and 0 <= nums[0] <= 1 and 0 <= nums[2] <= 1:
                motion.setdefault(key, {"$type": "cubicBezier", "$value": nums})
        elif re.search(r"shadow|elev", key):
            layer = _shadow(v)
            if layer:
                elevation.setdefault(key, {"$type": "shadow", "$value": layer})
    defaults = {"spacing": {f"space-{i}": {"$value": {"value": v, "unit": "px"}} for i, v in enumerate((4, 8, 12, 16, 24, 32, 48, 64), 1)},
                "radius": {"radius-small": {"$value": {"value": 4, "unit": "px"}}, "radius-large": {"$value": {"value": 12, "unit": "px"}}},
                "motion": {"duration-short": {"$type": "duration", "$value": {"value": 150, "unit": "ms"}},
                           "duration-medium": {"$type": "duration", "$value": {"value": 300, "unit": "ms"}}},
                "elevation": {"shadow-1": {"$type": "shadow", "$value": {"color": df.color_token("#000000")["$value"] | {"alpha": 0.12},
                                                                         "offsetX": {"value": 0, "unit": "px"}, "offsetY": {"value": 2, "unit": "px"},
                                                                         "blur": {"value": 8, "unit": "px"}, "spread": {"value": 0, "unit": "px"}}}}}
    for part, found in (("spacing", spacing), ("radius", radius), ("motion", motion), ("elevation", elevation)):
        if found:
            out[part] = ({"$type": "dimension"} if part in ("spacing", "radius") else {}) | dict(list(found.items())[:16])
        else:
            group = defaults[part]
            out[part] = ({"$type": "dimension"} if part in ("spacing", "radius") else {}) | group
            out[part]["$description"] = "Not found in the built page's CSS: the department's default scale."
    return out


def _shadow(v: str) -> dict | None:
    m = re.fullmatch(r"\s*(-?\d+(?:\.\d+)?)px\s+(-?\d+(?:\.\d+)?)px\s+(\d+(?:\.\d+)?)px(?:\s+(-?\d+(?:\.\d+)?)px)?\s+(#[0-9A-Fa-f]{6}|rgba?\([^)]+\))\s*", v)
    if not m:
        return None
    col = m.group(5)
    if col.startswith("#"):
        color = df.color_token(col.upper())["$value"]
    else:
        nums = [float(x) for x in re.split(r"[ ,/]+", col[col.index("(") + 1:-1].strip()) if x]
        if len(nums) < 3:
            return None
        hexv = "#" + "".join(f"{int(max(0, min(255, n))):02X}" for n in nums[:3])
        color = df.color_token(hexv)["$value"] | ({"alpha": nums[3]} if len(nums) > 3 and 0 <= nums[3] <= 1 else {})
    px = lambda s: {"value": float(s) if "." in s else int(s), "unit": "px"}  # noqa: E731
    return {"color": color, "offsetX": px(m.group(1)), "offsetY": px(m.group(2)), "blur": px(m.group(3)),
            "spread": px(m.group(4) or "0")}


# ---------------------------------------------------------------- command line

STAGES = ("inventory", "fixture", "check", "next", "capture", "assemble", "gate", "decision", "logo_brief", "save")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("stage", choices=STAGES)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--fixture", action="store_true")
    parser.add_argument("--phase", default="draft")
    parser.add_argument("--browser", default=None)
    parser.add_argument("--serve-host", default=None)
    args = parser.parse_args()
    if args.browser or args.serve_host:
        hp = _homepage()
        hp.BROWSER = args.browser or hp.BROWSER
        hp.SERVE_HOST = args.serve_host or hp.SERVE_HOST
    raw = os.environ.get("RESEARCH_DATA", "")
    started = time.monotonic()
    try:
        job = Job(args.workspace, args.fixture)
        methods = {"inventory": lambda: job.inventory(raw), "fixture": lambda: job.fixture_stage(args.phase),
                   "check": lambda: job.check(args.phase), "next": lambda: job.next(args.phase),
                   "capture": job.capture, "assemble": lambda: job.assemble(args.phase), "gate": lambda: job.gate(raw),
                   "decision": job.decision, "logo_brief": lambda: job.logo_brief(raw), "save": job.save_files}
        result = methods[args.stage]()
    except (ValueError, RuntimeError, KeyError, OSError) as exc:
        raise SystemExit(f"research {args.stage}: {exc}") from None
    result["seconds"] = round(time.monotonic() - started, 3)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
