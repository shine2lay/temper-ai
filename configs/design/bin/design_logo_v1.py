#!/usr/bin/env python3
"""Design-owned logo workflow artifact stages; paid work stays in Temper LLM nodes.

Fingerprinted append-only receipts, saved native identities and explicit human
boundaries. Real and fictional entries share no approval bypass. Stdlib only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import time
import uuid
from pathlib import Path

import design_homepage_v1 as h
import logo_contracts as c
import logo_size_check as size_check
import penpot_homepage_source as p
import penpot_logo_source as source


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".writing")
    tmp.write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    tmp.replace(path)


def load(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


FIXTURE_FAMILIES = ("geometric", "letterform", "pictorial", "emblem", "geometric", "emblem")
PNG = b"\x89PNG\r\n\x1a\n"
COLD_VIEWS = ("32", "128", "header")
COLD_METHOD = ("Caption-free first readings: each symbol alone on its paper colour, exported from its own native "
               "Penpot file at 32 px (glance) and 128 px (close), under neutral labels in a seeded shuffled order. "
               "The reader sees no caption, brief, name or idea. Same-name check: a second reader compares the "
               "symbol at 32 px beside the live wordmark with the research screen's same-name marks.")


def fixture_exploration(brief):
    """Model-free contract fixture, NEVER a real brand or generation substitute."""
    c.brief_contract(brief, "fixture")
    concepts = []
    for i in range(6):
        shape = {"kind": "rect", "name": "Fixture only", "x": 12 + i * 3, "y": 18,
                 "w": 70 - i * 6, "h": 60 + i * 2, "r": i * 2}
        if i == 1:
            shape = {"kind": "ellipse", "name": "Fixture only", "x": 20, "y": 12, "w": 60, "h": 76}
        if i == 2:
            shape = {"kind": "path", "name": "Fixture cubic", "commands": [["M", 12, 30], ["C", 28, 6, 72, 6, 88, 30], ["L", 76, 84], ["L", 24, 84], ["Z"]]}
        if i == 3:
            # Real counter: inner subpath wound the other way leaves a hole (nonzero fill).
            shape = {"kind": "path", "name": "Fixture ring", "commands": [
                ["M", 10, 10], ["L", 90, 10], ["L", 90, 90], ["L", 10, 90], ["Z"],
                ["M", 35, 35], ["L", 35, 65], ["L", 65, 65], ["L", 65, 35], ["Z"]]}
        symbol = [shape]
        if i == 2:
            # Two-tone colour mark: an accent-toned part, drawn in one colour in monochrome.
            symbol.append({"kind": "ellipse", "name": "Fixture accent", "x": 40, "y": 40, "w": 20, "h": 20, "tone": c.ACCENT_TONE})
        concepts.append({"id": "fixture-" + str(i), "name": brief["product"] + " test " + str(i),
            "family": FIXTURE_FAMILIES[i],
            "idea": "Fictional contract geometry, not generated artwork or aesthetic evidence.",
            "ownable_detail": "Fixture only; exercises the board's whole-word text fitting with a long enough description.",
            "generic_risk": "Fixture only; plain test shape.",
            "source_ids": [brief["sources"][0]["id"]], "tradeoff": "Fixture only; no uniqueness or design claim.",
            "symbol": symbol, "minimum_symbol_px": 24, "wordmark_weight": "600"})
    return {"product": brief["product"], "concepts": concepts}


def fixture_revision(brief, draft):
    c.brief_contract(brief, "fixture")
    return {"product": brief["product"], "concepts": draft["concepts"], "revisions": []}


def fixture_first_reads(cold, ident, with_id=False):
    """Model-free stand-in comparisons that quote every saved reading, as the contract demands."""
    rows = [{"reading": r["reading"], "size": r["size"], "fits_idea": i == 0,
             "note": "Fixture comparison only; not evidence about any mark."} for i, r in enumerate(cold[ident]["readings"])]
    marks = [{"mark": m, "note": "Fixture flag only; not evidence."} for m in cold[ident]["close"]]
    if with_id:
        return [{"id": ident, **r} for r in rows], [{"id": ident, **m} for m in marks]
    return rows, marks


def fixture_palette(brief, cold=None):
    """cold: saved cold read of the sketches; without it the rows have the earlier shape."""
    c.brief_contract(brief, "fixture")
    palette = {"ink": "#142E34", "paper": "#FFFFFF", "accent": "#277F88", "accent_on": "#FFFFFF", "muted": "#52616A", "surface": "#F1F4F2"}
    rows = []
    for i in range(3):
        row = {"id": "fixture-" + str(i), "palette": palette, "rationale": "Fictional fixture only."}
        if cold is not None:
            row["first_reads"], row["name_marks"] = fixture_first_reads(cold, row["id"])
        rows.append(row)
    return {"product": brief["product"], "shortlist": rows,
            "recommendation": "fixture-2", "recommendation_reason": "Fixture only; exercises editable cubic geometry."}


class Job:
    def __init__(self, workspace, run_id, mode):
        uuid.UUID(run_id)
        # replay: a real brief's saved symbols re-checked (size + cold read) with no gates,
        # budget answers, refinement or packet; it can never approve anything.
        # trial: a fictional brief run with the real (paid) agents, for testing a candidate
        # workflow; its gates are fictional (decided_by fixture-test), like a fixture's.
        if mode not in ("real", "fixture", "replay", "trial"):
            raise ValueError("explicit mode required")
        # RunRequest.workspace_path must name an existing mounted host folder.
        # Empty context otherwise creates per-script temporary artifacts that
        # disappear between nodes; refuse before login, save or paid generation.
        if (not str(workspace).strip() or not Path(workspace).is_absolute()
                or not Path(workspace).is_dir()):
            raise ValueError("explicit existing absolute persistent workspace required")
        self.root = Path(workspace).resolve() / "logo"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_path = self.root / "state.json"
        self.run_id, self.mode = run_id, mode
        self.fictional = mode in ("fixture", "trial")
        self.state = load(self.state_path) if self.state_path.exists() else {"run_id": run_id, "mode": mode, "receipts": {}, "files": {}, "round": 0}
        if (self.state["run_id"], self.state["mode"]) != (run_id, mode):
            raise ValueError("workspace belongs to another run/mode")

    def commit(self):
        save(self.state_path, self.state)

    def receipt(self, stage, fingerprint, output, artifacts):
        row = {"fingerprint": fingerprint, "output": output, "at": h.now(),
               "artifacts": {str(Path(a).relative_to(self.root)): sha(a) for a in artifacts}}
        old = self.state["receipts"].get(stage)
        if old and old != row:
            raise ValueError("completed stage receipt is immutable")
        self.state["receipts"][stage] = row
        self.commit()
        return output

    def cached(self, stage, fingerprint):
        old = self.state["receipts"].get(stage)
        if old:
            if old["fingerprint"] != fingerprint:
                raise ValueError("saved stage input changed; no duplicate/changed-input resume")
            for path, expected in old["artifacts"].items():
                if sha(self.root / path) != expected:
                    raise ValueError("saved stage artifact changed/missing")
            return old["output"]
        return None

    def brief(self, raw):
        b = c.brief_contract(json.loads(raw), {"replay": "real", "trial": "fixture"}.get(self.mode, self.mode))
        fingerprint = c.digest({"brief": b, "mode": self.mode, "schema": c.VERSION})
        cached = self.cached("brief", fingerprint)
        if cached:
            return cached
        self.state["brief_hash"] = c.digest(b)
        save(self.root / "brief.json", b)
        (self.root / "schema.txt").write_text(c.SCHEMA)
        research = self.research(b)
        save(self.root / "bounds.json", {"estimate_usd": c.FULL_ESTIMATE, "stage_reserves_usd": c.CAPS,
             "refinement_max": 2, "review_max": 3, "roughs": 6, "shortlist": 3,
             "native_budget_policy_usd": c.FULL_ESTIMATE,
             "note": "Estimate/reservations, not a per-Claude-CLI hard cap. Native policy checks between calls; an in-flight call can overshoot. Every retry counts. No automatic retry of a failed generation stage."})
        client = h.Penpot()
        client.login()
        h.assets(client, self.root / "assets")
        out = {"status": "completed", "brief_hash": self.state["brief_hash"], "run_id": self.run_id,
               "product": b["product"], "schema": "logo/schema.txt", "estimate_usd": c.FULL_ESTIMATE}
        out["research_files"] = len(research)
        return self.receipt("brief", fingerprint, out, [self.root / "brief.json", self.root / "schema.txt", self.root / "assets/licenses.json", *research])

    def research(self, b):
        """Copy the pinned research screen into the run; every byte must match its hash."""
        if "research" not in b:
            return []
        folder = Path(b["research"]["dir"])
        if not folder.is_dir() or folder.resolve() != folder:
            raise ValueError("research folder missing or not a real path")
        copies = []
        for name, expected in sorted(b["research"]["files"].items()):
            path = folder / name
            if path.is_symlink() or not path.is_file() or path.stat().st_size > 3_000_000:
                raise ValueError("research file missing, linked or oversized")
            data = path.read_bytes()
            if hashlib.sha256(data).hexdigest() != expected:
                raise ValueError("research file does not match its pinned hash")
            if name.endswith(".png") and not data.startswith(PNG):
                raise ValueError("research image is not a PNG")
            if name.endswith(".md"):
                data.decode("utf-8")
            target = self.root / "research" / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
            copies.append(target)
        images = ["logo/research/" + n for n in sorted(b["research"]["files"]) if n.endswith(".png")]
        lines = ["# Research screen for this run", "",
                 "Copied from the pinned research folder; hashes verified at the brief stage.",
                 "References only: never copy, trace or reuse these marks.", "",
                 "Research images (open each with Read):", *("- " + i for i in images), ""]
        for row in b.get("prior_rounds", []):
            answer, _, by = c.prior_answer(row)
            lines += ["## Earlier round the direction gate rejected (run " + row["run_id"] + ", decided by " + by + ")", "",
                      "Answer: " + answer, "",
                      "Rejected directions (do not repeat their ideas or look):",
                      *("- " + r["name"] + ": " + r["idea"] for r in row["rejected"]),
                      "Boards of that round: " + ", ".join("logo/research/" + e for e in row["evidence"]), ""]
        lines += ["## Dated comparison notes", "", (self.root / "research" / "comparison.md").read_text()]
        (self.root / "comparison.md").write_text("\n".join(lines))
        return [*copies, self.root / "comparison.md"]

    def only(self, *modes):
        if ("real" if self.mode == "trial" else self.mode) not in modes:
            raise ValueError("stage not allowed in this mode")

    def size_report(self, name, concepts):
        """Model-free size check of saved symbols; the honest minimum the packet may claim."""
        report = size_check.check(concepts)
        path = self.root / (name + ".size.json")
        save(path, report)
        return report, path

    def cold_prepare(self, phase, concepts, palettes=None):
        """Caption-free boards for the cold read, in a native file of their own.

        Neutral labels (S1..) in a seeded shuffled order; the label map stays in state.
        Copies go to logo/coldread-<phase>/ and the agents' context to logo/coldread-context.json.
        """
        order = list(range(len(concepts)))
        random.Random(c.digest({"run": self.run_id, "phase": phase})).shuffle(order)
        shown = [concepts[i] for i in order]
        labels = ["S" + str(i + 1) for i in range(len(shown))]
        state, exports = self.native_file("coldread-" + phase,
            lambda canvas: canvas.coldread_boards(shown, labels, palettes), kinds=("png",))
        facts = source.measurements(state, palettes or {})
        if facts["violations"]:
            raise ValueError("cold-read boards measured layout failed; source retained")
        folder = self.root / ("coldread-" + phase)
        folder.mkdir(parents=True, exist_ok=True)
        views = {}
        for receipt in exports:
            label, view = receipt["board"].split(" ")
            name = {"glance": "32", "close": "128", "header": "header"}[view]
            target = folder / f"{label}-{name}.png"
            shutil.copyfile(self.root.parent / receipt["path"], target)
            views.setdefault(label, {})[name] = str(target.relative_to(self.root.parent))
        brief = load(self.root / "brief.json")
        marks = ["logo/research/" + m for m in brief.get("research", {}).get("same_name", [])]
        # Two contexts: the cold reader's lists only its images (no mark names, header or
        # wordmark), the name checker's only the header lockups and the same-name marks.
        cold_context = {"labels": labels, "glance_32": [views[s]["32"] for s in labels],
                        "close_128": [views[s]["128"] for s in labels], "output": "logo/coldread.json"}
        names_context = {"labels": labels, "header_32": [views[s]["header"] for s in labels],
                         "same_name": marks, "output": "logo/names.json"}
        for stale in ("coldread.json", "names.json"):
            (self.root / stale).unlink(missing_ok=True)
        save(self.root / "coldread-context.json", cold_context)
        save(self.root / "names-context.json", names_context)
        save(self.root / ("coldread-" + phase + ".context.json"),
             {"phase": phase, "method": COLD_METHOD, "cold_read": cold_context, "name_check": names_context})
        save(self.root / ("coldread-" + phase + ".measurements.json"), facts)
        self.state.setdefault("cold", {})[phase] = {"labels": dict(zip(labels, [v["id"] for v in shown], strict=True)),
                                                  "marks": [m.rsplit("/", 1)[1] for m in marks]}
        # The latest prepared phase; adopting it twice with the same files returns the saved receipt.
        self.state["cold_phase"] = phase
        self.commit()
        return [self.root / ("coldread-" + phase + ".context.json"), self.root / ("coldread-" + phase + ".source.json"),
                *(self.root.parent / p for row in views.values() for p in row.values())]

    def adopt_cold_read(self):
        """Validate the cold read and name check of the latest prepared phase; map labels back to ids."""
        phase = self.state.get("cold_phase")
        if not phase:
            raise ValueError("no cold-read boards are waiting")
        info = self.state["cold"][phase]
        labels, marks = list(info["labels"]), info["marks"]
        if self.mode == "fixture":
            reads = {"readings": [{"label": s, "glance_32": [f"fixture reading {s} {n}" for n in "abc"],
                                   "close_128": [f"fixture close reading {s} {n}" for n in "abc"]} for s in labels]}
            names = {"resemblance": [{"label": s, "mark": m, "close": i == 0 and j == 0,
                                      "why": "Fixture flag only; not a resemblance finding."}
                                     for i, s in enumerate(labels) for j, m in enumerate(marks)]}
        else:
            reads = load(self.root / "coldread.json")
            names = load(self.root / "names.json") if marks else {"resemblance": []}
        reads = c.readings_contract(reads, labels)
        names = c.names_contract(names, labels, marks)
        label = "coldread-" + phase
        fingerprint = c.digest({"readings": reads, "names": names, "labels": info})
        if result := self.cached(label, fingerprint):
            return result
        symbols = {}
        for row in reads["readings"]:
            ident = info["labels"][row["label"]]
            symbols[ident] = {"label": row["label"],
                "readings": [{"size": "32", "reading": r} for r in row["glance_32"]] +
                            [{"size": "128", "reading": r} for r in row["close_128"]],
                "resemblance": [r for r in names["resemblance"] if r["label"] == row["label"]],
                "close": [r["mark"] for r in names["resemblance"] if r["label"] == row["label"] and r["close"]]}
        path = self.root / (label + ".saved.json")
        save(path, {"phase": phase, "method": COLD_METHOD, "fictional_test": self.fictional,
                    "same_name_marks": marks, "symbols": symbols,
                    "limits": "Readings of one model at one time: first impressions to compare with the idea, not "
                              "user research, recognition rates or a trademark search."})
        return self.receipt(label, fingerprint, {"status": "completed", "phase": phase, "saved": "logo/" + path.name,
            "symbols": len(symbols), "close_flags": sum(len(v["close"]) for v in symbols.values())}, [path])

    def cold(self, phase):
        """Saved cold read of a phase as the contracts take it: {id: {readings, close}}."""
        saved = load(self.root / ("coldread-" + phase + ".saved.json"))
        return {i: {"readings": v["readings"], "close": v["close"]} for i, v in saved["symbols"].items()}

    def adopt_replay(self, raw):
        """Replay mode: re-check saved symbols of a real run (size check + cold-read boards)."""
        self.only("replay")
        b = load(self.root / "brief.json")
        v = json.loads(raw)
        c.keys(v, ("concepts", "source"), ("palettes",))
        if not isinstance(v["concepts"], list) or not 1 <= len(v["concepts"]) <= 12:
            raise ValueError("replay needs one to twelve saved concepts")
        concepts = [c.concept_contract(row, b) for row in v["concepts"]]
        if len({row["id"] for row in concepts}) != len(concepts):
            raise ValueError("replay concept ids must be distinct")
        palettes = {k: c.palette_contract(p) for k, p in v.get("palettes", {}).items()}
        if not set(palettes) <= {row["id"] for row in concepts}:
            raise ValueError("replay palette for an unknown concept")
        v = {"concepts": concepts, "palettes": palettes, "source": c.text(v["source"], 300)}
        fingerprint = c.digest(v)
        if result := self.cached("replay", fingerprint):
            return result
        save(self.root / "replay.saved.json", v)
        report, size_path = self.size_report("replay", concepts)
        artifacts = self.cold_prepare("replay", concepts, palettes)
        return self.receipt("replay", fingerprint, {"status": "completed", "symbols": len(concepts),
            "size": "logo/" + size_path.name, "context": "logo/coldread-context.json",
            "minimum_px": {r["id"]: r["claim_px"] for r in report["symbols"]}},
            [self.root / "replay.saved.json", size_path, *artifacts])

    def budget(self, raw, stage):
        self.only("real", "fixture")
        if self.mode == "fixture":
            c.brief_contract(load(self.root / "brief.json"), "fixture")
            return {"status": "completed", "model_calls": 0, "fictional_test": True}
        reservation = c.budget_contract(json.loads(raw), c.INITIAL_RESERVE if stage == "initial" else c.REFINE_RESERVE)
        if stage != "initial" and self.state["round"] >= c.EXTRA_ROUND:
            raise ValueError("refinement rounds exhausted, the extra round included")
        if stage != "initial" and self.state["round"] >= c.PLANNED_ROUNDS:
            # Past the planned rounds only when the last final gate asked for it: it recorded
            # revise with a note, and this fresh reservation names that note.
            path = self.final_record(self.state["round"])
            if not path.is_file():
                raise ValueError("two refinement rounds exhausted; the final gate asked for no extra round")
            record = load(path)
            note = c.extra_round_contract(record, reservation, run_id=self.run_id,
                brief_hash=self.state["brief_hash"], artifact_hash=self.state["final_artifact_hash"])
            self.state["extra_round"] = {"round": c.EXTRA_ROUND, "note": note, "decided_by": c.decided_by(record),
                                         "final_record": path.name, "recorded_at": h.now()}
            self.commit()
        label = "budget-initial" if stage == "initial" else f'budget-r{self.state["round"] + 1:02}'
        path = self.root / (label + ".json")
        save(path, {**reservation, "recorded_at": h.now()})
        return {"status": "completed", "budget_receipt": "logo/" + path.name, "round": self.state["round"] + 1}

    def native_file(self, label, build, kinds=("png", "svg")):
        """Recover only same known empty file or exact fully saved checkpoint.

        Ambiguous partial native saves fail closed, retaining UUID/objects; never
        create another file or merge/overwrite foreign state.
        """
        client = h.Penpot()
        client.login()
        pending_path = self.root / (label + ".pending.json")
        name = load(self.root / "brief.json")["product"] + " / logo v1 / " + label + " / " + self.run_id[:8]
        if pending_path.exists():
            pending = load(pending_path)
            file = client.get(pending["state"]["file_id"])
            if file["name"] != name:
                raise ValueError("pending file name/ownership changed")
            objects = file["data"]["pages-index"][pending["state"]["page_id"]]["objects"]
            if set(objects) == {p.ROOT} and file["revn"] == 0:
                file = client.update(file["id"], pending["changes"])
            else:
                source.source_checks(file, pending["state"])
            state = pending["state"]
        else:
            identity_path = self.root / (label + ".identity.json")
            file = (h.recover_empty_pending(client, identity_path, name) if identity_path.exists()
                    else client.create(name))
            # Persist identity even if local construction or network save fails.
            empty = {"file_id": file["id"], "page_id": file["data"]["pages"][0], "name": name}
            save(identity_path, empty)
            canvas = source.LogoCanvas(file, self.root / "assets", load(self.root / "brief.json")["product"])
            build(canvas)
            state = canvas.state()
            save(pending_path, {"state": state, "changes": canvas.changes, "created_at": h.now()})
            file = client.update(file["id"], canvas.changes)
        checked = source.source_checks(file, state)
        # New session, fresh login and get-file: persistence, not save-only proof.
        fresh = h.Penpot()
        fresh.login()
        reopened = source.source_checks(fresh.get(state["file_id"]), state)
        save(self.root / (label + ".source.json"), state)
        save(self.root / (label + ".reopen.json"), {"saved": checked, "fresh": reopened, "fresh_login": True, "at": h.now()})
        exports = []
        for i, board in enumerate(state["boards"]):
            for kind in kinds:
                path = self.root / "exports" / f"{label}-{i:02}.{kind}"
                receipt = fresh.export(state, board, kind, path)
                receipt["path"] = str(path.relative_to(self.root.parent))
                receipt.update({"board": board["name"], "kind": kind, "width": board["width"], "height": board["height"]})
                if kind == "svg":
                    receipt["safe_svg"] = c.safe_svg(path.read_bytes())
                exports.append(receipt)
        save(self.root / (label + ".exports.json"), exports)
        self.state["files"][label] = {"file_id": state["file_id"], "page_id": state["page_id"],
            "team_id": state["team_id"], "revn": reopened["revn"], "exports": exports,
            "url": f'{fresh.base}/#/workspace?team-id={state["team_id"]}&file-id={state["file_id"]}&page-id={state["page_id"]}'}
        self.commit()
        return state, exports

    def adopt_exploration(self):
        self.only("real", "fixture")
        b = load(self.root / "brief.json")
        v = fixture_exploration(b) if self.mode == "fixture" else load(self.root / "exploration.json")
        v = c.exploration_contract(v, b)
        fingerprint = c.digest(v)
        if result := self.cached("exploration", fingerprint):
            return result
        save(self.root / "exploration.saved.json", v)
        state, exports = self.native_file("roughs", lambda canvas: canvas.rough_board(v["concepts"]))
        facts = source.measurements(state, {})
        if facts["violations"]:
            raise ValueError("rough-board measured layout failed; preserve source identity")
        save(self.root / "roughs.measurements.json", facts)
        report, size_path = self.size_report("roughs", v["concepts"])
        out = {"status": "completed", "monochrome": exports[0]["path"], "product": b["product"], "concepts": [r["id"] for r in v["concepts"]],
               "size": "logo/" + size_path.name, "minimum_px": {r["id"]: r["claim_px"] for r in report["symbols"]}}
        return self.receipt("exploration", fingerprint, out, [self.root / "exploration.saved.json", self.root / "roughs.source.json", self.root / "roughs.exports.json", size_path])

    def adopt_revision(self):
        """Second explorer pass: it has seen its own render and redrawn what failed."""
        self.only("real", "fixture")
        b, draft = load(self.root / "brief.json"), load(self.root / "exploration.saved.json")
        v = fixture_revision(b, draft) if self.mode == "fixture" else load(self.root / "exploration-revised.json")
        v = c.revision_contract(v, b, draft)
        fingerprint = c.digest({"draft": c.digest(draft), "revision": v})
        if result := self.cached("revision", fingerprint):
            return result
        save(self.root / "sketches.saved.json", v)
        state, exports = self.native_file("sketches", lambda canvas: canvas.rough_board(v["concepts"], "sketches revised after seeing the render"))
        facts = source.measurements(state, {})
        if facts["violations"]:
            raise ValueError("revised sketch board measured layout failed; preserve source identity")
        save(self.root / "sketches.measurements.json", facts)
        report, size_path = self.size_report("sketches", v["concepts"])
        cold = self.cold_prepare("sketches", v["concepts"])
        out = {"status": "completed", "monochrome": exports[0]["path"], "revised": [r["id"] for r in v["revisions"]],
               "size": "logo/" + size_path.name, "minimum_px": {r["id"]: r["claim_px"] for r in report["symbols"]},
               "coldread_context": "logo/coldread-context.json"}
        return self.receipt("revision", fingerprint, out, [self.root / "sketches.saved.json", self.root / "sketches.source.json", self.root / "sketches.exports.json", size_path, *cold])

    def concepts(self):
        return load(self.root / "sketches.saved.json")["concepts"]

    def adopt_palette(self):
        self.only("real", "fixture")
        b, concepts = load(self.root / "brief.json"), self.concepts()
        cold = self.cold("sketches")
        sizes = {r["id"]: r for r in load(self.root / "sketches.size.json")["symbols"]}
        v = fixture_palette(b, cold) if self.mode == "fixture" else load(self.root / "palette.json")
        v = c.shortlist_contract(v, b, concepts, cold)
        c.fixed_palette_check(v, b)
        fingerprint = c.digest({"exploration": c.digest(concepts), "palette": v, "cold": cold, "size": c.digest(sizes)})
        if result := self.cached("shortlist", fingerprint):
            return result
        save(self.root / "palette.saved.json", v)
        def build(canvas):
            canvas.comparison_board(concepts, v["shortlist"])
            for i, row in enumerate(v["shortlist"]):
                concept = next(o for o in concepts if o["id"] == row["id"])
                canvas.actual_sizes_board(concept, row["palette"], origin=2300 + i * 900, size=sizes[row["id"]])
            canvas.contract_board()
        state, exports = self.native_file("directions", build)
        palettes = {r["id"]: r["palette"] for r in v["shortlist"]}
        facts = source.measurements(state, palettes)
        # Contract board is deliberately defective; never count it as design QA.
        actual = [v for v in facts["violations"] if v["board"] != "Aster / contract board"]
        if actual:
            raise ValueError("shortlist measured layout/contrast failed; source retained")
        save(self.root / "directions.measurements.json", facts)
        artifacts = [self.root / "palette.saved.json", self.root / "directions.source.json", self.root / "directions.exports.json"]
        self.state["direction_artifact_hash"] = c.digest({str(a.name): sha(a) for a in artifacts})
        self.commit()
        out = {"status": "completed", "contact_sheet": exports[0]["path"], "previews": [r["path"] for r in exports if r["kind"] == "png"],
               "recommendation": v["recommendation"], "artifact_hash": self.state["direction_artifact_hash"], "run_id": self.run_id,
               "brief_hash": self.state["brief_hash"], "choices": [r["id"] for r in v["shortlist"]]}
        return self.receipt("shortlist", fingerprint, out, artifacts)

    def adopt_critic(self):
        self.only("real", "fixture")
        b = load(self.root / "brief.json")
        round_number = self.state["round"]
        ids = ({self.state["direction"]["decision"]} if round_number else
               {r["id"] for r in load(self.root / "palette.saved.json")["shortlist"]})
        cold = self.cold(f"r{round_number:02}" if round_number else "sketches")
        if self.mode == "fixture":
            reads, marks = [], []
            for ident in sorted(ids):
                rows, flags = fixture_first_reads(cold, ident, with_id=True)
                reads += rows
                marks += flags
            v = {"product": b["product"], "observations": [], "recommendation": self.state.get("direction", {}).get("decision", "fixture-2"),
                 "recommendation_reason": "Fictional contract fixture; no aesthetic evaluation.",
                 "limitations": "No model call; this is not critic evidence.", "first_reads": reads, "name_marks": marks}
        else:
            v = load(self.root / "critic.json")
        v = c.critique_contract(v, b, ids, cold)
        label = f"critic-r{round_number:02}"
        fingerprint = c.digest({"critique": v, "round": round_number, "source": self.state["files"]["directions" if not round_number else f"selected-r{round_number:02}"]["file_id"]})
        if result := self.cached(label, fingerprint):
            return result
        path = self.root / (label + ".json")
        save(path, v)
        return self.receipt(label, fingerprint, {"status": "completed", "review": "logo/" + path.name,
            "round": round_number, "advisory_only": True, "aesthetic_scores": False}, [path])

    def direction(self, raw, gate_only):
        self.only("real", "fixture")
        rows = load(self.root / "palette.saved.json")["shortlist"]
        decision = c.approval_contract(json.loads(raw), kind="direction", run_id=self.run_id,
            brief_hash=self.state["brief_hash"], artifact_hash=self.state["direction_artifact_hash"],
            choices={r["id"] for r in rows} | {c.EXPLORE_AGAIN}, gate_only=gate_only, fictional=self.fictional)
        fingerprint = c.digest(decision)
        if result := self.cached("direction", fingerprint):
            return result
        record = self.root / "gate-direction.json"
        save(record, {**decision, "recorded_at": h.now(), "fictional_test": self.fictional})
        not_final = {"approved": False, "decided_by": None}
        if decision["decision"] == c.EXPLORE_AGAIN:
            # None of the three: this run ends; the next run carries the rejection.
            self.state["explore_again"] = decision
            save(self.root / "explore-again.json", {"run_id": self.run_id, "brief_hash": self.state["brief_hash"],
                "answer": decision["note"], "decided_by": decision["decided_by"], "fictional_test": self.fictional,
                "rejected": [{"id": v["id"], "name": v["name"], "idea": v["idea"]}
                             for v in self.concepts() if v["id"] in {r["id"] for r in rows}],
                "evidence": ["exports/sketches-00.png", "exports/directions-00.png"], "recorded_at": h.now()})
            return self.receipt("direction", fingerprint, {"status": "completed", "selected": c.EXPLORE_AGAIN,
                "outcome": "explore_again", "decided_by": decision["decided_by"],
                "direction_approved": {"approved": False, "decided_by": decision["decided_by"]}, "final_approved": not_final},
                [record, self.root / "explore-again.json"])
        self.state["direction"] = decision
        concept = next(v for v in self.concepts() if v["id"] == decision["decision"])
        palette = next(v["palette"] for v in rows if v["id"] == decision["decision"])
        save(self.root / "selected.json", {"concept": concept, "palette": palette})
        return self.receipt("direction", fingerprint, {"status": "completed", "selected": decision["decision"],
            "outcome": "selected", "decided_by": decision["decided_by"],
            "direction_approved": {"approved": True, "decided_by": decision["decided_by"]}, "final_approved": not_final},
            [record])

    def final_record(self, round_number):
        """The final gate's saved answer for a round: gate-final-rNN.json, or a legacy owner-final-rNN.json."""
        path = self.root / f"gate-final-r{round_number:02}.json"
        legacy = self.root / f"owner-final-r{round_number:02}.json"
        return legacy if not path.is_file() and legacy.is_file() else path

    def direction_flag(self):
        """direction_approved with who decided, from a new or legacy saved direction."""
        d = self.state.get("direction") or {}
        return {"approved": bool(d), "decided_by": c.decided_by(d) if d else None}

    def round_cap(self):
        extra = self.state.get("extra_round") or {}
        return c.EXTRA_ROUND if extra.get("round") == c.EXTRA_ROUND else c.PLANNED_ROUNDS

    def fixture_extra_round(self):
        """Fixture twin of the extra round (real mode records it at the refine budget gate).

        Only a fictional round-2 final answer of this run, revise with a note, about the current
        artwork, opens round 3; the fixture workflow has no budget gate to carry it.
        """
        path = self.final_record(c.PLANNED_ROUNDS)
        if self.mode != "fixture" or self.state["round"] != c.PLANNED_ROUNDS or self.state.get("extra_round") or not path.is_file():
            return
        record = load(path)
        if (record.get("fictional_test") is not True or c.decided_by(record) != c.FIXTURE_DECIDER
                or record.get("decision") != "revise" or not str(c.gate_note(record) or "").strip()
                or record.get("run_id") != self.run_id or record.get("brief_hash") != self.state["brief_hash"]
                or record.get("artifact_hash") != self.state.get("final_artifact_hash")):
            return
        self.state["extra_round"] = {"round": c.EXTRA_ROUND, "note": c.gate_note(record), "decided_by": c.FIXTURE_DECIDER,
                                     "final_record": path.name, "recorded_at": h.now(), "fictional_test": True}
        self.commit()

    def prepare_refine(self):
        self.only("real", "fixture")
        if not self.state.get("direction"):
            raise ValueError("no selected direction")
        self.fixture_extra_round()
        if self.state["round"] >= self.round_cap():
            raise ValueError("two refinement rounds exhausted" + (" with the extra round" if self.round_cap() > c.PLANNED_ROUNDS else ""))
        next_round = self.state["round"] + 1
        if next_round == c.EXTRA_ROUND:
            feedback = c.gate_note(self.state["extra_round"])
        else:
            # The final gate's note, else the direction gate's note, else its reasons (legacy owner_note read too).
            feedback = c.gate_note(self.state.get("final_feedback", {}))
            if feedback is None:
                feedback = c.gate_note(self.state["direction"])
            if feedback is None:
                feedback = self.state["direction"]["reason"]
        # The current schema (e.g. optional accent-toned parts) goes to its own file, so the
        # brief stage's pinned schema.txt receipt stays intact for resume checks.
        (self.root / "schema-refine.txt").write_text(c.SCHEMA)
        context = {"product": load(self.root / "brief.json")["product"], "round": next_round,
                   "schema": "logo/schema-refine.txt", "schema_digest": c.digest(c.SCHEMA),
                   "selected": load(self.root / "selected.json"), "note": feedback,
                   "critic": f'logo/critic-r{self.state["round"]:02}.json', "output": "logo/refined.json",
                   "pngs": [r["path"] for r in self.state["files"]["directions" if next_round == 1 else f'selected-r{self.state["round"]:02}']["exports"] if r["kind"] == "png"]}
        # Measured size and caption-free first readings of the artwork being refined.
        previous = "sketches" if next_round == 1 else f'selected-r{self.state["round"]:02}'
        evidence = {"size_check": previous + ".size.json",
                    "cold_read": "coldread-" + ("sketches" if next_round == 1 else f'r{self.state["round"]:02}') + ".saved.json"}
        context.update({k: "logo/" + v for k, v in evidence.items() if (self.root / v).is_file()})
        fingerprint = c.digest(context)
        label = f"prepare-r{next_round:02}"
        if result := self.cached(label, fingerprint):
            return result
        save(self.root / "refine-context.json", context)
        return self.receipt(label, fingerprint, {"status": "completed", "round": next_round,
            "context": "logo/refine-context.json", "output": "logo/refined.json"}, [])

    def adopt_refine(self):
        self.only("real", "fixture")
        b = load(self.root / "brief.json")
        next_round = load(self.root / "refine-context.json")["round"]
        label = f"selected-r{next_round:02}"
        selected = load(self.root / "selected.json")
        v = ({"product": b["product"], **selected, "changes": ["Fixture persists selected vectors; no paid refinement."], "declined": []}
             if self.mode == "fixture" else load(self.root / "refined.json"))
        v = c.refinement_contract(v, b, self.state["direction"]["decision"])
        fingerprint = c.digest({"refinement": v, "context": load(self.root / "refine-context.json")})
        if result := self.cached(label, fingerprint):
            return result
        if next_round != self.state["round"] + 1 or next_round > self.round_cap():
            raise ValueError("duplicate or unbounded refinement")
        save(self.root / (label + ".json"), v)
        report, size_path = self.size_report(label, [v["concept"]])
        size = report["symbols"][0]
        state, exports = self.native_file(label, lambda canvas: canvas.final_boards(b, v["concept"], v["palette"], size=size))
        facts = source.measurements(state, {v["concept"]["id"]: v["palette"]})
        if facts["violations"]:
            raise ValueError("selected identity measured layout failed; source retained")
        save(self.root / (label + ".measurements.json"), facts)
        cold = self.cold_prepare(f"r{next_round:02}", [v["concept"]], {v["concept"]["id"]: v["palette"]})
        save(self.root / "selected.json", {"concept": v["concept"], "palette": v["palette"]})
        self.state["round"] = next_round
        self.commit()
        return self.receipt(label, fingerprint, {"status": "completed", "round": next_round, "round_label": f"{next_round:02}",
            "pngs": [r["path"] for r in exports if r["kind"] == "png"], "source": self.state["files"][label]["url"],
            "size": "logo/" + size_path.name, "minimum_px": size["claim_px"], "coldread_context": "logo/coldread-context.json"},
            [self.root / (label + ".json"), self.root / (label + ".source.json"), self.root / (label + ".exports.json"), size_path, *cold])

    def handoff(self):
        self.only("real", "fixture")
        round_number = self.state["round"]
        label = f"selected-r{round_number:02}"
        size = load(self.root / (label + ".size.json"))["symbols"][0]
        fingerprint = c.digest({"selected": sha(self.root / (label + ".json")), "critic": sha(self.root / f"critic-r{round_number:02}.json"),
                                "size": sha(self.root / (label + ".size.json"))})
        if result := self.cached("handoff-r" + str(round_number), fingerprint):
            return result
        source_state = load(self.root / (label + ".source.json"))
        fresh = h.Penpot()
        fresh.login()
        checked = source.source_checks(fresh.get(source_state["file_id"]), source_state)
        save(self.root / (label + ".handoff-reopen.json"), {**checked, "fresh_login": True, "at": h.now()})
        b, selected = load(self.root / "brief.json"), load(self.root / "selected.json")
        save(self.root / "tokens.json", {"product": b["product"], "sRGB": selected["palette"],
             "font": {"family": "Source Sans Pro", "weight": selected["concept"]["wordmark_weight"], "licence": "SIL OFL 1.1", "assets": "assets/"},
             "clear_space_unit": "0.25 of symbol nominal box on every side", "minimum_symbol_px": size["claim_px"],
             "declared_minimum_symbol_px": selected["concept"]["minimum_symbol_px"],
             "measured_size": {k: size[k] for k in ("minimum_px", "exact_minimum_px", "clear_from_px", "exact_clear_from_px")},
             "size_check": label + ".size.json",
             "proposed_minimum_lockup_px": 160, "not_publication_approved": True})
        brand = f'''# {b["product"]} / identity study

Selected concept: {selected["concept"]["name"]} ({selected["concept"]["id"]}).
{selected["concept"]["idea"]}
Trade-off: {selected["concept"]["tradeoff"]}

## Status and sources
The direction gate's answer is saved with who decided it; final approval remains a separate gate.
This packet approves no publication, production rebrand or app/CSS/logo change.
Facts and interpretations: brief.json; direction choice, decided_by and reasons: gate-direction.json.
Native editable source: {self.state["files"][label]["url"]}
Vector layers/shared colours/live typography IDs: {label}.source.json.
Original declarative curves/primitives: {label}.json. No stock primary mark.

## Variants
exports/ contains native PNG and safe self-contained SVG for primary lockup,
secondary name, monochrome, reverse, symbol, symbol-mono, symbol-reverse,
live wordmark, 512px avatar and actual-size/light-dark board. Exact board-to-file
mapping and hashes: {label}.exports.json. Reverse transparent marks need a dark
background. Editable text source stays live; portable SVG embeds the same font.
No raster-in-vector or remote-font fallback. Symbol negative spaces remain empty.

## Use
Clear space: at least 0.25 of the nominal symbol square on all sides; keep text
and other marks outside it. {size_check.board_note(size)}
The size check measures the saved vectors ({label}.size.json): {size["summary"]}.
16/24/32/48/64px remain shown at actual size, not declared equally good. Proposed
lockup minimum: 160px; visually confirm at 160 and 320, never squeeze the wordmark.
512px avatar uses generous padding. Use monochrome if colour reproduction fails.
Do not stretch, rotate, add gradients/shadows, redraw/close counters, substitute a
font or separate internal shapes. Do not use the accent alone to encode status.

## Colour and type
Digital sRGB HEX roles: tokens.json. Ink/paper/surface carry identity and normal
content; muted is secondary readable companion text; accent is bounded emphasis,
accent_on is its readable text. Palette measured pairs: {label}.measurements.json.
No CMYK/Pantone or print equivalence is asserted. Logos/logotypes have WCAG
exemptions; companion text/UI contrasts are measured, not an overall WCAG claim.
Source Sans Pro regular/semibold are pre-installed licensed assets; actual TTF
name tables/version/copyright/SHA and full SIL OFL 1.1: assets/licenses.json and
assets/Source-Sans-OFL.txt. No new vendor/assets/purchase. Native Latin/LTR cache
uses installed TTF advances, not a kerning or complex-script shaper; editor edits
may recompute. Fresh-editor and offline export evidence must accompany delivery.

## Review limits
critic-r00.json and later reviews separate measured, visual, taste and similarity
observations. Refinement changes/declined points stay in {label}.json. AI taste
is advice, not an aesthetic score, user testing or trademark clearance. Native
save/reopen and static screenshots do not prove runtime interaction accessibility.
Naming/similarity screen is dated and non-exhaustive. Exact-name AI/automation
namesakes merit professional clearance before public use. No uniqueness claim.
'''
        (self.root / "BRAND.md").write_text(brand)
        shutil.copyfile(self.root / "BRAND.md", self.root / f"BRAND-r{round_number:02}.md")
        shutil.copyfile(self.root / "tokens.json", self.root / f"tokens-r{round_number:02}.json")
        artifacts = [self.root / (label + ".json"), self.root / (label + ".source.json"), self.root / (label + ".exports.json"),
                     self.root / (label + ".size.json"), self.root / f"BRAND-r{round_number:02}.md", self.root / f"tokens-r{round_number:02}.json"]
        self.state["final_artifact_hash"] = c.digest({a.name: sha(a) for a in artifacts})
        self.commit()
        manifest = {"run_id": self.run_id, "mode": self.mode, "round": round_number,
             "direction_approved": self.direction_flag(), "final_approved": {"approved": False, "decided_by": None},
             "workflow_verified": False, "source_verified": False, "exports_verified": False,
             "native_save_and_fresh_reopen_checked": True, "safe_svg_checked": True,
             "artifact_hash": self.state["final_artifact_hash"], "brief_hash": self.state["brief_hash"],
             "source_url": self.state["files"][label]["url"], "exports": self.state["files"][label]["exports"],
             "host_checks_required": ["exact deployed revision", "model-free/resume tests", "real editor", "offline SVG font/vector render", "actual-size visual inspection", "packet/licence integrity", "actual cost/time"],
             "ready_for_publication": False, "packet_built": True, "at": h.now()}
        save(self.root / "manifest.json", manifest)
        return self.receipt("handoff-r" + str(round_number), fingerprint, {"status": "completed", "manifest": "logo/manifest.json", "brand": "logo/BRAND.md",
            "run_id": self.run_id, "brief_hash": self.state["brief_hash"], "artifact_hash": self.state["final_artifact_hash"], "choices": ["approve", "revise"],
            "round": round_number}, artifacts)

    def final(self, raw, gate_only):
        self.only("real", "fixture")
        decision = c.approval_contract(json.loads(raw), kind="final", run_id=self.run_id,
            brief_hash=self.state["brief_hash"], artifact_hash=self.state["final_artifact_hash"], choices={"approve", "revise"},
            gate_only=gate_only, fictional=self.fictional)
        path = self.root / f'gate-final-r{self.state["round"]:02}.json'
        save(path, {**decision, "recorded_at": h.now(), "fictional_test": self.fictional})
        by = decision["decided_by"]
        if decision["decision"] == "revise":
            if self.state["round"] >= 2:
                raise ValueError("final-gate revision is still pending: two paid refinements exhausted")
            if not decision.get("note"):
                raise ValueError("revision requires the final gate's own note")
            self.state["final_feedback"] = decision
            self.commit()
            return {"status": "completed", "verdict": "request_changes", "decided_by": by,
                    "direction_approved": self.direction_flag(), "final_approved": {"approved": False, "decided_by": by}}
        self.state["final_approval"] = decision
        self.commit()
        manifest = load(self.root / "manifest.json")
        manifest["final_approved"] = {"approved": True, "decided_by": by}
        manifest["final_receipt"] = path.name
        save(self.root / "manifest.json", manifest)
        return {"status": "completed", "verdict": "approved", "decided_by": by, "direction_approved": self.direction_flag(),
                "final_approved": {"approved": True, "decided_by": by}, "ready_for_publication": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("brief", "budget", "explore", "revise", "coldread", "palette", "critic", "direction",
                                          "prepare", "refine", "handoff", "final", "replay"))
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--mode", choices=("real", "fixture", "replay", "trial"), required=True)
    parser.add_argument("--budget-stage", choices=("initial", "refine"), default="initial")
    parser.add_argument("--native-gate", action="store_true")
    args = parser.parse_args()
    job = Job(args.workspace, args.run_id, args.mode)
    raw = os.getenv("LOGO_DATA", "")
    methods = {"brief": lambda: job.brief(raw), "budget": lambda: job.budget(raw, args.budget_stage),
        "explore": job.adopt_exploration, "revise": job.adopt_revision, "coldread": job.adopt_cold_read,
        "replay": lambda: job.adopt_replay(raw), "palette": job.adopt_palette, "critic": job.adopt_critic,
        "direction": lambda: job.direction(raw, args.native_gate), "prepare": job.prepare_refine,
        "refine": job.adopt_refine, "handoff": job.handoff, "final": lambda: job.final(raw, args.native_gate)}
    started = time.monotonic()
    try:
        out = methods[args.stage]()
    except (ValueError, RuntimeError, KeyError, OSError, json.JSONDecodeError):
        # Never forward native/CLI response bodies, credentials or model payloads.
        raise SystemExit("logo stage rejected; inspect owned saved state/artifacts, not model request bodies") from None
    print(json.dumps({**out, "seconds": round(time.monotonic() - started, 3)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
