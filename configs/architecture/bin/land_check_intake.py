#!/usr/bin/env python3
"""Prepare land-check cases for arch_land_check (System architecture, queue #23, 2026-10-04).

Runs on the host, because the temper worker cannot see Architecture's proof folders or the branch
worktrees. For each case it builds

  <workspaces>/land-check/<case>/        code/ proof/ request.md rubric.md scratch/
  <workspaces>/land-check-grade/<case>/  expected.json, and selfcheck/ drafts for the grader's own test

The first folder is all a land-check run sees: a git clone of the checked head (with master at the
check as `master`), copies of only the proof inputs that existed at check time (sha256-verified
against the recorded check), the request and the method. Answers (the recorded check, landed.json,
rebase questions) never go there; expected.json lives in the second folder.

  land_check_intake.py --case L2       one real case
  land_check_intake.py --seed s1       one seeded case, built on a copy of its real case
  land_check_intake.py --stretch x1    a stretch case (recorded, not scored)
  land_check_intake.py --all           every case
  land_check_intake.py --leak-check    confirm no answer reached a case folder

The cases file (--cases, or $LAND_CHECK_CASES) stays outside this repo: it names private proof
folders and Architecture's own findings. It lists proofs_root, never_copy, switch, and the real,
seeded and stretch cases.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
UPLOAD_PACK = "git -c uploadpack.allowAnySHA1InWant=true upload-pack"
TEST_NAME = re.compile(r"(?<![\w/.])(test_[a-z0-9_]+)\b(?!\.py)(?!/)")
TICKED_TEST = re.compile(r"`(test_[a-z0-9_]+)(?:\[[^`\]]*\])?`")
HEX = re.compile(r"\b[0-9a-f]{7,40}\b")
LEAK_WORDS = ("architecture-check", "landed.json", "rebase-question")


# ---------------------------------------------------------------- small helpers

def run(cmd: list[str], cwd: Path | None = None, stdin: str | None = None, env: dict | None = None) -> str:
    done = subprocess.run(cmd, cwd=cwd, input=stdin, capture_output=True, text=True,
                          env={**os.environ, **(env or {})})
    if done.returncode:
        raise SystemExit(f"{' '.join(cmd)} failed ({done.returncode}): {done.stderr.strip()[:800]}")
    return done.stdout


def git(code: Path, *args: str, stdin: str | None = None, env: dict | None = None) -> str:
    return run(["git", "-C", str(code), *args], stdin=stdin, env=env).strip()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def digest_of(path: Path) -> str:
    """A file's sha256, or a batch folder's: the sha256 of its MANIFEST.sha256."""
    return sha256_file(path / "MANIFEST.sha256") if path.is_dir() else sha256_file(path)


def when(stamp: str) -> dt.datetime:
    return dt.datetime.fromisoformat(stamp)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")


def is_answer(rel: str, never: list[str]) -> bool:
    return any(word in rel for word in never)


# ---------------------------------------------------------------- the code folder

def commits_named_in(proof: Path, repo: Path, before: dt.datetime, skip: set[str]) -> list[str]:
    """Commits named anywhere in the proof copies, made no later than the check: fetched as
    refs/evidence/<sha> so the facts step can compare evidence heads with the branch."""
    tokens: set[str] = set()
    for path in proof.rglob("*"):
        if path.is_file() and path.stat().st_size < 50_000_000:
            tokens.update(HEX.findall(path.read_text(errors="replace")))
    if not tokens:
        return []
    out = run(["git", "-C", str(repo), "cat-file", "--batch-check=%(objectname) %(objecttype)"],
              stdin="\n".join(sorted(tokens)) + "\n")
    found = sorted({line.split()[0] for line in out.splitlines() if line.endswith(" commit")} - skip)
    if not found:
        return []
    keep = []
    for line in git(repo, "log", "--no-walk=unsorted", "--format=%H %ct", *found).splitlines():
        sha, stamp = line.split()
        if dt.datetime.fromtimestamp(int(stamp), dt.UTC) <= before:
            keep.append(sha)
    return keep


def build_code(code: Path, repo: Path, branch: str, head: str, master: str, extra: list[str]) -> None:
    if code.exists():
        shutil.rmtree(code)
    code.mkdir(parents=True)
    run(["git", "init", "-q", "-b", "intake-unborn", str(code)])
    specs = [f"{head}:refs/heads/{branch}", f"{master}:refs/heads/master"]
    specs += [f"{sha}:refs/evidence/{sha}" for sha in extra]
    git(code, "fetch", "-q", "--no-tags", "--upload-pack", UPLOAD_PACK, str(repo), *specs)
    git(code, "checkout", "-q", branch)
    git(code, "config", "user.name", "land-check intake")
    git(code, "config", "user.email", "land-check@localhost")


# ---------------------------------------------------------------- the proof folder

def copy_inputs(cfg: dict, root: Path, proof: Path, check_time: dt.datetime, never: list[str]):
    """Copy only the inputs that existed at check time. Returns (inputs, dropped)."""
    if proof.exists():
        shutil.rmtree(proof)
    proof.mkdir(parents=True)
    inputs, dropped = [], []
    for item in cfg["inputs"]:
        src = Path(item["path"]) if item["path"].startswith("/") else root / item["path"]
        rel = item.get("dest") or item["path"]
        recorded = item.get("digest")
        if is_answer(rel, never):
            dropped.append({"path": f"proof/{rel}", "reason": "an answer file; never copied"})
            continue
        if not src.exists():
            dropped.append({"path": f"proof/{rel}", "reason": "missing on disk"})
            continue
        now = digest_of(src)
        if recorded and not now.startswith(recorded.lower()):
            dropped.append({"path": f"proof/{rel}", "reason": f"changed after the check: recorded sha256 {recorded}, now {now[:16]}"})
            continue
        if not recorded:
            mtime = dt.datetime.fromtimestamp(src.stat().st_mtime, dt.UTC)
            if mtime > check_time:
                dropped.append({"path": f"proof/{rel}", "reason": "no digest recorded and written after the check"})
                continue
        dest = proof / rel
        if src.is_dir():
            notes = []
            manifest = (src / "MANIFEST.sha256").read_text().splitlines()
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src / "MANIFEST.sha256", dest / "MANIFEST.sha256")
            for line in manifest:
                if not line.strip():
                    continue
                want, name = line.split(None, 1)
                name = name.lstrip("*").strip()
                if is_answer(name, never):
                    notes.append(f"{name}: an answer file; not copied")
                    continue
                if not (src / name).is_file() or sha256_file(src / name) != want:
                    notes.append(f"{name}: does not match its manifest line; not copied")
                    continue
                (dest / name).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src / name, dest / name)
            inputs.append({"path": f"proof/{rel}", "kind": "batch", "digest": recorded,
                           "note": "; ".join(notes) or "every manifest file copied and verified"})
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            inputs.append({"path": f"proof/{rel}", "kind": "file", "digest": recorded,
                           "note": "digest verified" if recorded else "no digest recorded; kept because it was written before the check"})
    return inputs, dropped


# ---------------------------------------------------------------- claimed bindings

def bindings_from(rule: dict, proof: Path) -> tuple[list[dict], str]:
    path = proof / rule["file"]
    if not path.is_file():
        return [], f"proof/{rule['file']} was not copied, so no bindings could be read from it"
    source = f"proof/{rule['file']}"
    kind, out = rule["kind"], []
    if kind == "json_mentions":
        data = json.loads(path.read_text())

        def walk(node, where):
            if isinstance(node, dict):
                for k, v in node.items():
                    yield from walk(v, where + [str(k)])
            elif isinstance(node, list):
                for i, v in enumerate(node):
                    yield from walk(v, where + [str(i)])
            elif isinstance(node, str):
                yield "/".join(where), node

        for key in rule["keys"]:
            for where, text in walk(data.get(key), [key]):
                tests = list(dict.fromkeys(TEST_NAME.findall(text)))
                if tests:
                    out.append({"id": where, "claim": text[:300], "tests": tests, "source": source})
    elif kind == "md_mentions":
        lines = path.read_text().splitlines()
        blocks, start = [], 0
        for i, line in enumerate(lines + [""]):
            new_block = (not line.strip() or line.lstrip().startswith(("#", "|"))
                         or re.match(r"^\s{0,2}([-*]|\d+\.)\s", line))
            if new_block and i > start:
                blocks.append((start, lines[start:i]))
                start = i
            if not line.strip():
                start = i + 1
        for first, block in blocks:
            text = " ".join(part.strip() for part in block)
            tests = list(dict.fromkeys(TICKED_TEST.findall(text)))
            if tests:
                out.append({"id": f"{rule['file']}:{first + 1}", "claim": text[:300], "tests": tests, "source": source})
    elif kind == "checklist":
        data = json.loads(path.read_text())
        for n, item in enumerate(data.get(rule["list"], []), 1):
            tests = item.get(rule["tests"]) or {}
            tests = list(tests.keys()) if isinstance(tests, dict) else list(tests)
            if tests:
                out.append({"id": f"{rule['list']} {n}", "claim": str(item.get(rule["claim"]))[:300],
                            "tests": tests, "source": source})
    elif kind == "md_table":
        text = path.read_text()
        part = text.split(rule["section"], 1)[1] if rule["section"] in text else ""
        part = part.split("\n## ", 1)[0]
        for line in part.splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if not line.startswith("|") or len(cells) < 2 or set(cells[0]) <= {"-", ":", " "}:
                continue
            tests = list(dict.fromkeys(TICKED_TEST.findall(line)))
            if tests:
                out.append({"id": cells[0][:80], "claim": " | ".join(cells)[:300], "tests": tests, "source": source})
    else:
        raise SystemExit(f"unknown bindings_from kind {kind}")
    return out, f"read from {source} ({kind})"


# ---------------------------------------------------------------- request.md

def write_request(folder: Path, req: dict) -> None:
    lines = [
        f"# Land check request: {req['gate']}",
        "",
        f"May the branch `{req['branch']}` land on master now, as it is? {req['what']}.",
        "",
        f"- Gate: {req['gate']}",
        f"- Branch: {req['branch']} (checked out in code/)",
        f"- Head: {req['head']}",
        f"- Master at the check: {req['master_at_check']} (the `master` ref in code/)",
        "- Base: the merge-base of the head and master at the check",
        f"- Check time: {req['check_time']}",
        f"- Switch: {req['switch']['env']} in {req['switch']['module']}; landed switched off, it must stay off by default",
        "",
        "## Evidence the branch offers (copies in proof/)",
        "",
    ]
    lines += [f"- {path}" for path in req["evidence"]] or ["- (none)"]
    lines += ["", "## Proof inputs (copied only if they existed at the check, digest-verified)", ""]
    for item in req["inputs"]:
        digest = f"sha256 {item['digest']}" if item["digest"] else "no digest recorded"
        lines.append(f"- {item['path']} ({item['kind']}, {digest}): {item['note']}")
    if req["dropped_inputs"]:
        lines += ["", "Not copied:"]
        lines += [f"- {d['path']}: {d['reason']}" for d in req["dropped_inputs"]]
    lines += ["", "## Bindings the branch claims, with their named tests", "",
              f"({req['bindings_note']})", ""]
    for b in req["bindings"]:
        lines.append(f"- {b['id']}: {b['claim']}")
        lines.append(f"  tests: {', '.join(b['tests'])}")
    lines += ["", "## Machine-readable (arch_land_facts reads this block)", "", "```json",
              json.dumps(req, indent=1, ensure_ascii=False), "```", ""]
    (folder / "request.md").write_text("\n".join(lines))


def read_request(folder: Path) -> dict:
    text = (folder / "request.md").read_text()
    return json.loads(text.split("```json", 1)[1].split("```", 1)[0])


# ---------------------------------------------------------------- expected.json

def expected_items(rec: dict, asks: dict) -> list[dict]:
    items = []
    for f in rec.get("findings", []):
        fid = f.get("id")
        text = " ".join(str(f[k]) for k in ("severity", "result", "what", "fix", "evidence") if f.get(k))
        ask = bool(f.get("fix")) or not str(f.get("result", "pass")).startswith("pass")
        items.append({"key": f"finding:{fid}", "kind": "finding", "text": f"{fid}: {text}", "ask": ask})
    for i, s in enumerate(rec.get("nits_not_blocking", [])):
        items.append({"key": f"nit:{i}", "kind": "nit", "text": str(s), "ask": False})
    for i, s in enumerate(rec.get("landing_conditions", [])):
        items.append({"key": f"landing:{i}", "kind": "landing", "text": str(s), "ask": False})
    bind = rec.get("bindings_for_later_tasks") or []
    if isinstance(bind, dict):
        for task, entries in bind.items():
            for i, s in enumerate(entries):
                items.append({"key": f"binding:{task}:{i}", "kind": "binding", "text": f"[{task}] {s}", "ask": True})
    else:
        for i, s in enumerate(bind):
            items.append({"key": f"binding:{i}", "kind": "binding", "text": str(s), "ask": True})
    for i, s in enumerate(rec.get("follow_ups_for_the_temper_chat", [])):
        items.append({"key": f"follow_up:{i}", "kind": "follow_up", "text": str(s), "ask": True})
    for i, s in enumerate(rec.get("residual_risks", [])):
        items.append({"key": f"residual:{i}", "kind": "residual", "text": str(s), "ask": False})
    by_key = {it["key"]: it for it in items}
    for key in asks.get("true", []):
        by_key[key]["ask"] = True
    for key in asks.get("false", []):
        by_key[key]["ask"] = False
    for dup, into in asks.get("merge", {}).items():
        by_key[into]["text"] += f" || the same point, also written as: {by_key[dup]['text']}"
        by_key[into]["also"] = dup
        items.remove(by_key[dup])
    return items


def draft_from_items(items: list[dict], mechanical: dict, land: bool, label: str) -> dict:
    """A draft.json (schema 1) holding exactly the given expected items: the grader's self-check."""
    draft = {"schema_version": 1, "check": f"grader self-check: {label}", "by": label, "land": land,
             "decision": "Land." if land else "Do not land.", "branch": dict(mechanical),
             "mechanical": {"passed": True, "failed_checks": []}, "findings": [], "verified": [],
             "nits_not_blocking": [], "landing_conditions": [], "bindings_for_later_tasks": [],
             "follow_ups": [], "residual_risks": [], "not_covered": []}
    section = {"nit": "nits_not_blocking", "landing": "landing_conditions",
               "binding": "bindings_for_later_tasks", "follow_up": "follow_ups", "residual": "residual_risks"}
    for n, it in enumerate(items, 1):
        if it["kind"] == "finding" and it["ask"]:
            draft["findings"].append({"id": f"D{n}", "severity": "follow-up", "place": "", "risk": it["text"],
                                      "why_here": "", "fix": "", "evidence": ""})
        elif it["kind"] == "finding":
            draft["verified"].append(it["text"])
        elif it["kind"] in section:
            draft[section[it["kind"]]].append(it["text"])
    return draft


# ---------------------------------------------------------------- building cases

def paths(args, case: str) -> tuple[Path, Path]:
    return Path(args.workspaces) / "land-check" / case, Path(args.workspaces) / "land-check-grade" / case


def open_for_runs(*dirs: Path) -> None:
    """Temper runs execute in a per-run container as another user (temperai) than the one who builds
    the case: the folders a run writes into must be writable by it. code/ and proof/ stay read-only."""
    for d in dirs:
        if d.is_dir():
            d.chmod(0o777)


def build_folder(args, cases: dict, case: str, cfg: dict, check_time: dt.datetime, gate: str) -> dict:
    folder, _ = paths(args, case)
    if folder.exists():
        shutil.rmtree(folder)
    (folder / "scratch").mkdir(parents=True)
    root = Path(cases["proofs_root"])
    inputs, dropped = copy_inputs(cfg, root, folder / "proof", check_time, cases["never_copy"])
    extra = commits_named_in(folder / "proof", Path(args.repo), check_time, {cfg["head"], cfg["master_at_check"]})
    build_code(folder / "code", Path(args.repo), cfg["branch"], cfg["head"], cfg["master_at_check"], extra)
    shutil.copy2(HERE / "land_check_rubric.md", folder / "rubric.md")
    copied = {i["path"] for i in inputs}
    evidence = []
    for e in cfg["evidence"]:
        p = f"proof/{e}"
        if p in copied or any(p.startswith(c + "/") for c in copied):
            evidence.append(p)
    bindings, note = bindings_from(cfg["bindings_from"], folder / "proof")
    req = {"case": case, "gate": gate, "branch": cfg["branch"], "head": cfg["head"],
           "master_at_check": cfg["master_at_check"], "check_time": check_time.isoformat(),
           "what": cfg["what"], "switch": cases["switch"], "inputs": inputs, "dropped_inputs": dropped,
           "evidence": evidence, "evidence_commits": extra, "bindings": bindings, "bindings_note": note}
    write_request(folder, req)
    return req


def make_real(args, cases: dict, case: str) -> None:
    cfg = cases["real"][case]
    rec = json.loads((Path(cases["proofs_root"]) / cfg["check"]).read_text())
    check_time = when(rec["written"])
    req = build_folder(args, cases, case, cfg, check_time, case)
    items = expected_items(rec, cfg["asks"])
    _, grade = paths(args, case)
    if grade.exists():
        shutil.rmtree(grade)
    expected = {"case": case, "kind": "real", "source_check": cfg["check"], "written": rec["written"],
                "land": bool(rec["land"]), "failed_check": None, "mechanical": cfg["expected_mechanical"],
                "items": items, "asks": sum(1 for it in items if it["ask"]),
                "invented_must_fix": cfg["invented_must_fix"]}
    write_json(grade / "expected.json", expected)
    self_draft = draft_from_items(items, cfg["expected_mechanical"], bool(rec["land"]), f"{case} recorded check")
    write_json(grade / "selfcheck" / "self" / "draft.json", self_draft)
    asks = sorted((it for it in items if it["ask"]), key=lambda it: it["key"])
    drop = {it["key"] for it in asks[1::2]}
    kept = [it for it in items if it["key"] not in drop]
    degraded = draft_from_items(kept, cfg["expected_mechanical"], False, f"{case} degraded copy")
    inv = cfg["invented_must_fix"]
    degraded["findings"].append({"id": "D99", "severity": "must-fix", "place": inv["place"], "risk": inv["what"],
                                 "why_here": inv["what"], "fix": inv["fix"], "evidence": "the diff"})
    write_json(grade / "selfcheck" / "degraded" / "draft.json", degraded)
    folder, _ = paths(args, case)
    open_for_runs(folder, folder / "scratch", grade, grade / "selfcheck", grade / "selfcheck" / "self",
                  grade / "selfcheck" / "degraded")
    print(f"{case}: {len(req['inputs'])} inputs, {len(req['dropped_inputs'])} dropped, "
          f"{len(req['evidence'])} evidence, {len(req['bindings'])} bindings, "
          f"{len(req['evidence_commits'])} evidence commits, asks {expected['asks']} "
          f"(degraded keeps {expected['asks'] - len(drop)})")


def amend_head(code: Path, change) -> tuple[str, str, str, str]:
    """Apply change(code) to the working tree and amend the head commit, keeping its message,
    author and dates. Returns (old head, old tree, new head, new tree)."""
    old_head, old_tree = git(code, "rev-parse", "HEAD"), git(code, "rev-parse", "HEAD^{tree}")
    stamp = git(code, "log", "-1", "--format=%cI", "HEAD")
    name = git(code, "log", "-1", "--format=%cn", "HEAD")
    mail = git(code, "log", "-1", "--format=%ce", "HEAD")
    change(code)
    git(code, "add", "-A")
    git(code, "commit", "-q", "--amend", "--no-edit",
        env={"GIT_COMMITTER_DATE": stamp, "GIT_COMMITTER_NAME": name, "GIT_COMMITTER_EMAIL": mail})
    return old_head, old_tree, git(code, "rev-parse", "HEAD"), git(code, "rev-parse", "HEAD^{tree}")


def rewrite_evidence(folder: Path, req: dict, old: tuple[str, str], new: tuple[str, str], drop_test: str | None) -> None:
    """The evidence was re-run on the amended head: rename the head and tree everywhere, drop a
    removed test from per-test lists, and record the new digests."""
    proof = folder / "proof"
    changed = []
    for path in sorted(proof.rglob("*.json")):
        text = path.read_text()
        new_text = text.replace(old[0], new[0]).replace(old[1], new[1])
        if drop_test and '"tests"' in new_text:
            data = json.loads(new_text)
            if isinstance(data.get("tests"), list):
                before = len(data["tests"])
                data["tests"] = [t for t in data["tests"] if not str(t.get("test", "")).endswith("::" + drop_test)]
                gone = before - len(data["tests"])
                if gone and isinstance(data.get("counts"), dict) and "passed" in data["counts"]:
                    data["counts"]["passed"] -= gone
                    if isinstance(data.get("pytest_summary"), str):
                        data["pytest_summary"] = re.sub(r"^\d+ passed", f"{data['counts']['passed']} passed",
                                                        data["pytest_summary"])
                new_text = json.dumps(data, indent=1, ensure_ascii=False) + "\n"
        if new_text != text:
            path.write_text(new_text)
            changed.append(path)
    b15 = proof / "T4T5" / "evidence" / "b15-check.json"
    if b15.is_file():
        data = json.loads(b15.read_text())
        for record in data.get("records", []):
            target = proof / "T4T5" / record.get("file", "")
            if target.is_file() and target != b15:
                record["sha256"] = sha256_file(target)
        b15.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    for item in req["inputs"]:
        target = folder / item["path"]
        if item["kind"] == "file" and item["digest"] and target.is_file():
            item["digest"] = sha256_file(target)


def make_seed(args, cases: dict, seed: str) -> None:
    cfg = cases["seeded"][seed]
    src_case = cfg["from"]
    src, src_grade = paths(args, src_case)
    if not (src / "request.md").is_file():
        make_real(args, cases, src_case)
    folder, grade = paths(args, seed)
    for path in (folder, grade):
        if path.exists():
            shutil.rmtree(path)
    shutil.copytree(src, folder, symlinks=True)
    for leftover in ("draft.json", "draft.md"):
        (folder / leftover).unlink(missing_ok=True)
    shutil.rmtree(folder / "scratch")
    (folder / "scratch").mkdir()
    req = read_request(folder)
    req["case"] = seed
    code = folder / "code"
    kind = cfg["seed"]
    if kind == "input_changed":
        path = folder / "proof" / cfg["file"]
        data = json.loads(path.read_text())
        data["rerun_note"] = "re-run 2026-10-04 13:02 after one flaky full-suite test"
        parts = data.get("batches", {}).get("run-003", {}).get("parts", {})
        if "full-sqlite" in parts:
            parts["full-sqlite"]["passed"] = parts["full-sqlite"].get("passed", 0) - 1
        path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    elif kind == "dirty_tree":
        with open(code / cfg["file"], "a") as f:
            f.write("\n# Experiment: log every wait's id here while chasing a slow resume.\n")
    elif kind == "master_overlap":
        master = git(code, "rev-parse", "master")
        old = run(["git", "-C", str(code), "show", f"master:{cfg['file']}"])
        blob = git(code, "hash-object", "-w", "--stdin",
                   stdin=old + "\n# A waiting step is named in its log line (see the step's own record).\n")
        index = folder / "scratch" / ".seed-index"
        env = {"GIT_INDEX_FILE": str(index)}
        git(code, "read-tree", "master", env=env)
        git(code, "update-index", "--cacheinfo", f"100644,{blob},{cfg['file']}", env=env)
        tree = git(code, "write-tree", env=env)
        index.unlink()
        stamp = (when(req["check_time"]) - dt.timedelta(minutes=40)).isoformat()
        new = git(code, "commit-tree", tree, "-p", master, "-m",
                  "Stage executor: name the waiting step in its log line",
                  env={"GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp})
        git(code, "update-ref", "refs/heads/master", new)
        req["master_at_check"] = new
    elif kind == "test_removed":
        def cut(c: Path) -> None:
            path = c / cfg["file"]
            lines = path.read_text().splitlines(keepends=True)
            start = next(i for i, line in enumerate(lines) if line.startswith(f"def {cfg['test']}("))
            while start > 0 and lines[start - 1].startswith("@"):
                start -= 1
            end = start + 1
            while end < len(lines) and not re.match(r"^(def |class |@|async def )", lines[end]):
                end += 1
            path.write_text("".join(lines[:start] + lines[end:]))
        old_head, old_tree, new_head, new_tree = amend_head(code, cut)
        rewrite_evidence(folder, req, (old_head, old_tree), (new_head, new_tree), cfg["test"])
        req["head"] = new_head
    elif kind == "switch_on":
        def flip(c: Path) -> None:
            path = c / cfg["file"]
            text = path.read_text()
            assert 'os.environ.get(SWITCH_ENV, "")' in text
            path.write_text(text.replace('os.environ.get(SWITCH_ENV, "")', 'os.environ.get(SWITCH_ENV, "1")'))
        old_head, old_tree, new_head, new_tree = amend_head(code, flip)
        rewrite_evidence(folder, req, (old_head, old_tree), (new_head, new_tree), None)
        req["head"] = new_head
    elif kind == "evidence_other_head":
        path = folder / "proof" / cfg["file"]
        data = json.loads(path.read_text())
        data["tested_tree"]["commit"] = cfg["other"]
        data["tested_tree"]["tree"] = git(code, "rev-parse", f"{cfg['other']}^{{tree}}")
        path.write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
        for item in req["inputs"]:
            if item["path"] == f"proof/{cfg['file']}":
                item["digest"] = sha256_file(path)
    else:
        raise SystemExit(f"unknown seed {kind}")
    req["gate"] = seed
    write_request(folder, req)
    src_expected = json.loads((src_grade / "expected.json").read_text())
    items = [dict(it, ask=False) for it in src_expected["items"]]
    items.append({"key": f"seeded:{cfg['expect_failed']}", "kind": "seeded", "text": cfg["what"], "ask": False})
    write_json(grade / "expected.json", {
        "case": seed, "kind": "seeded", "from": src_case, "seed": kind, "land": False,
        "failed_check": cfg["expect_failed"], "mechanical": {}, "items": items, "asks": 0})
    open_for_runs(folder, folder / "scratch", grade)
    print(f"{seed} (from {src_case}, {kind}): expect land false on {cfg['expect_failed']}")


def make_stretch(args, cases: dict, name: str) -> None:
    cfg = dict(cases["stretch"][name])
    base = cases["real"][cfg["from"]]
    cfg.update({"branch": base["branch"], "master_at_check": base["master_at_check"],
                "what": base["what"] + " (the first head, before its last commit)",
                "bindings_from": base["bindings_from"]})
    req = build_folder(args, cases, name, cfg, when(cfg["written"]), name)
    _, grade = paths(args, name)
    if grade.exists():
        shutil.rmtree(grade)
    write_json(grade / "expected.json", {
        "case": name, "kind": "stretch", "from": cfg["from"], "land": None, "failed_check": None,
        "mechanical": {}, "question": cfg["question"], "asks": 0,
        "items": [{"key": "stretch:C1", "kind": "stretch", "text": cfg["question"], "ask": False}]})
    folder, _ = paths(args, name)
    open_for_runs(folder, folder / "scratch", grade)
    print(f"{name}: stretch on {cfg['head'][:8]}, {len(req['inputs'])} inputs, {len(req['evidence'])} evidence")


def leak_check(args, cases: dict) -> int:
    """Fail on any answer file outside code/, on any sentence of a recorded check found in a case's
    proof or request, and on refs other than the branch, master and evidence commits. Mentions of
    the answer files' names (procedure text such as "lands after architecture-check.json says
    land true") are listed for a person to read, not failed."""
    root = Path(args.workspaces) / "land-check"
    bad, mentions, fixtures = [], [], 0
    snippets: dict[str, list[str]] = {}
    for name, cfg in cases["real"].items():
        rec = json.loads((Path(cases["proofs_root"]) / cfg["check"]).read_text())
        texts = [rec.get("decision", "")]
        texts += [it["text"].split(": ", 1)[-1] for it in expected_items(rec, {"true": [], "false": [], "merge": {}})]
        snippets[name] = [t[:60] for t in texts if len(t) >= 60]
    source = {**{n: n for n in cases["real"]}, **{n: c["from"] for n, c in cases["seeded"].items()},
              **{n: c["from"] for n, c in cases["stretch"].items()}}
    for path in root.rglob("*"):
        rel = str(path.relative_to(root))
        if not path.is_file() or "/code/.git/" in f"/{rel}":
            continue
        if "/code/" in f"/{rel}":
            fixtures += path.name == "expected.json"
            continue
        if path.name == "expected.json" or any(word in path.name for word in LEAK_WORDS):
            bad.append(f"answer-like file: {rel}")
            continue
        text = path.read_text(errors="replace")
        for word in LEAK_WORDS:
            if word in text:
                mentions.append(f"{rel} mentions {word}")
        for snip in snippets.get(source.get(rel.split("/", 1)[0], ""), []):
            if snip in text:
                bad.append(f"{rel} quotes the recorded check: {snip!r}")
    for case in sorted(p.name for p in root.iterdir() if p.is_dir()):
        refs = git(root / case / "code", "for-each-ref", "--format=%(refname)").splitlines()
        odd = [r for r in refs if not r.startswith(("refs/heads/", "refs/evidence/"))]
        if odd:
            bad.append(f"{case}: unexpected refs {odd}")
    if mentions:
        print("Names of answer files mentioned (read by hand: procedure text, not answers):")
        print("\n".join(f"  {m}" for m in sorted(set(mentions))))
    print(f"code/ folders hold {fixtures} of temper's own test fixtures named expected.json (part of the checked code)")
    print("\n".join(bad) if bad else f"leak check: clean ({root})")
    return 1 if bad else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case")
    ap.add_argument("--seed")
    ap.add_argument("--stretch")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--leak-check", action="store_true")
    ap.add_argument("--workspaces", default=str(Path.home() / "temper-ai" / "workspaces"))
    ap.add_argument("--repo", default=str(Path.home() / "temper-ai"))
    ap.add_argument("--cases", default=os.environ.get("LAND_CHECK_CASES"),
                    help="cases file, kept outside the repo (default: $LAND_CHECK_CASES)")
    args = ap.parse_args()
    if not args.cases:
        ap.error("no cases file: pass --cases or set LAND_CHECK_CASES")
    cases = json.loads(Path(args.cases).read_text())
    if args.leak_check:
        return leak_check(args, cases)
    if args.case:
        make_real(args, cases, args.case)
    if args.seed:
        make_seed(args, cases, args.seed)
    if args.stretch:
        make_stretch(args, cases, args.stretch)
    if args.all:
        for case in cases["real"]:
            make_real(args, cases, case)
        for seed in cases["seeded"]:
            make_seed(args, cases, seed)
        for name in cases["stretch"]:
            make_stretch(args, cases, name)
        return leak_check(args, cases)
    return 0


if __name__ == "__main__":
    sys.exit(main())
