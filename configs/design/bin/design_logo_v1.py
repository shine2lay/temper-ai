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
import shutil
import time
import uuid
from pathlib import Path

import design_homepage_v1 as h
import logo_contracts as c
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


def fixture_palette(brief):
    c.brief_contract(brief, "fixture")
    palette = {"ink": "#142E34", "paper": "#FFFFFF", "accent": "#277F88", "accent_on": "#FFFFFF", "muted": "#52616A", "surface": "#F1F4F2"}
    return {"product": brief["product"], "shortlist": [{"id": "fixture-" + str(i), "palette": palette, "rationale": "Fictional fixture only."} for i in range(3)],
            "recommendation": "fixture-2", "recommendation_reason": "Fixture only; exercises editable cubic geometry."}


class Job:
    def __init__(self, workspace, run_id, mode):
        uuid.UUID(run_id)
        if mode not in ("real", "fixture"):
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
        b = c.brief_contract(json.loads(raw), self.mode)
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
            lines += ["## Earlier round the owner rejected (run " + row["run_id"] + ")", "",
                      "Owner's answer: " + row["owner_answer"], "",
                      "Rejected directions (do not repeat their ideas or look):",
                      *("- " + r["name"] + ": " + r["idea"] for r in row["rejected"]),
                      "Boards of that round: " + ", ".join("logo/research/" + e for e in row["evidence"]), ""]
        lines += ["## Dated comparison notes", "", (self.root / "research" / "comparison.md").read_text()]
        (self.root / "comparison.md").write_text("\n".join(lines))
        return [*copies, self.root / "comparison.md"]

    def budget(self, raw, stage):
        if self.mode == "fixture":
            c.brief_contract(load(self.root / "brief.json"), "fixture")
            return {"status": "completed", "model_calls": 0, "fictional_test": True}
        reservation = c.budget_contract(json.loads(raw), c.INITIAL_RESERVE if stage == "initial" else c.REFINE_RESERVE)
        if stage != "initial" and self.state["round"] >= 2:
            raise ValueError("two refinement rounds exhausted; owner must decide reduced scope/new plan")
        label = "budget-initial" if stage == "initial" else f'budget-r{self.state["round"] + 1:02}'
        path = self.root / (label + ".json")
        save(path, {**reservation, "recorded_at": h.now()})
        return {"status": "completed", "budget_receipt": "logo/" + path.name, "round": self.state["round"] + 1}

    def native_file(self, label, build):
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
            for kind in ("png", "svg"):
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
        out = {"status": "completed", "monochrome": exports[0]["path"], "product": b["product"], "concepts": [r["id"] for r in v["concepts"]]}
        return self.receipt("exploration", fingerprint, out, [self.root / "exploration.saved.json", self.root / "roughs.source.json", self.root / "roughs.exports.json"])

    def adopt_revision(self):
        """Second explorer pass: it has seen its own render and redrawn what failed."""
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
        out = {"status": "completed", "monochrome": exports[0]["path"], "revised": [r["id"] for r in v["revisions"]]}
        return self.receipt("revision", fingerprint, out, [self.root / "sketches.saved.json", self.root / "sketches.source.json", self.root / "sketches.exports.json"])

    def concepts(self):
        return load(self.root / "sketches.saved.json")["concepts"]

    def adopt_palette(self):
        b, concepts = load(self.root / "brief.json"), self.concepts()
        v = fixture_palette(b) if self.mode == "fixture" else load(self.root / "palette.json")
        v = c.shortlist_contract(v, b, concepts)
        fingerprint = c.digest({"exploration": c.digest(concepts), "palette": v})
        if result := self.cached("shortlist", fingerprint):
            return result
        save(self.root / "palette.saved.json", v)
        def build(canvas):
            canvas.comparison_board(concepts, v["shortlist"])
            for i, row in enumerate(v["shortlist"]):
                concept = next(o for o in concepts if o["id"] == row["id"])
                canvas.actual_sizes_board(concept, row["palette"], origin=2300 + i * 900)
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
        b = load(self.root / "brief.json")
        round_number = self.state["round"]
        ids = ({self.state["direction"]["decision"]} if round_number else
               {r["id"] for r in load(self.root / "palette.saved.json")["shortlist"]})
        v = ({"product": b["product"], "observations": [], "recommendation": self.state.get("direction", {}).get("decision", "fixture-2"), "recommendation_reason": "Fictional contract fixture; no aesthetic evaluation.", "limitations": "No model call; this is not critic evidence."}
             if self.mode == "fixture" else load(self.root / "critic.json"))
        v = c.critique_contract(v, b, ids)
        label = f"critic-r{round_number:02}"
        fingerprint = c.digest({"critique": v, "round": round_number, "source": self.state["files"]["directions" if not round_number else f"selected-r{round_number:02}"]["file_id"]})
        if result := self.cached(label, fingerprint):
            return result
        path = self.root / (label + ".json")
        save(path, v)
        return self.receipt(label, fingerprint, {"status": "completed", "review": "logo/" + path.name,
            "round": round_number, "advisory_only": True, "aesthetic_scores": False}, [path])

    def direction(self, raw, gate_only):
        rows = load(self.root / "palette.saved.json")["shortlist"]
        decision = c.approval_contract(json.loads(raw), kind="direction", run_id=self.run_id,
            brief_hash=self.state["brief_hash"], artifact_hash=self.state["direction_artifact_hash"],
            choices={r["id"] for r in rows} | {c.EXPLORE_AGAIN}, gate_only=gate_only, fictional=self.mode == "fixture")
        fingerprint = c.digest(decision)
        if result := self.cached("owner-direction", fingerprint):
            return result
        save(self.root / "owner-direction.json", {**decision, "recorded_at": h.now(), "fictional_test": self.mode == "fixture"})
        if decision["decision"] == c.EXPLORE_AGAIN:
            # None of the three: this run ends; the next run carries the rejection.
            self.state["explore_again"] = decision
            save(self.root / "explore-again.json", {"run_id": self.run_id, "brief_hash": self.state["brief_hash"],
                "owner_answer": decision["owner_note"], "fictional_test": self.mode == "fixture",
                "rejected": [{"id": v["id"], "name": v["name"], "idea": v["idea"]}
                             for v in self.concepts() if v["id"] in {r["id"] for r in rows}],
                "evidence": ["exports/sketches-00.png", "exports/directions-00.png"], "recorded_at": h.now()})
            return self.receipt("owner-direction", fingerprint, {"status": "completed", "selected": c.EXPLORE_AGAIN,
                "outcome": "explore_again", "direction_owner_approved": False, "final_owner_approved": False},
                [self.root / "owner-direction.json", self.root / "explore-again.json"])
        self.state["direction"] = decision
        concept = next(v for v in self.concepts() if v["id"] == decision["decision"])
        palette = next(v["palette"] for v in rows if v["id"] == decision["decision"])
        save(self.root / "selected.json", {"concept": concept, "palette": palette})
        return self.receipt("owner-direction", fingerprint, {"status": "completed", "selected": decision["decision"],
            "outcome": "selected", "direction_owner_approved": self.mode == "real", "final_owner_approved": False},
            [self.root / "owner-direction.json"])

    def prepare_refine(self):
        if not self.state.get("direction"):
            raise ValueError("no selected owner direction")
        if self.state["round"] >= 2:
            raise ValueError("two refinement rounds exhausted")
        next_round = self.state["round"] + 1
        feedback = self.state.get("final_feedback", {}).get("owner_note", self.state["direction"].get("owner_note", self.state["direction"]["reason"]))
        # The current schema (e.g. optional accent-toned parts) goes to its own file, so the
        # brief stage's pinned schema.txt receipt stays intact for resume checks.
        (self.root / "schema-refine.txt").write_text(c.SCHEMA)
        context = {"product": load(self.root / "brief.json")["product"], "round": next_round,
                   "schema": "logo/schema-refine.txt", "schema_digest": c.digest(c.SCHEMA),
                   "selected": load(self.root / "selected.json"), "owner_note": feedback,
                   "critic": f'logo/critic-r{self.state["round"]:02}.json', "output": "logo/refined.json",
                   "pngs": [r["path"] for r in self.state["files"]["directions" if next_round == 1 else "selected-r01"]["exports"] if r["kind"] == "png"]}
        fingerprint = c.digest(context)
        label = f"prepare-r{next_round:02}"
        if result := self.cached(label, fingerprint):
            return result
        save(self.root / "refine-context.json", context)
        return self.receipt(label, fingerprint, {"status": "completed", "round": next_round,
            "context": "logo/refine-context.json", "output": "logo/refined.json"}, [])

    def adopt_refine(self):
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
        if next_round != self.state["round"] + 1 or next_round > 2:
            raise ValueError("duplicate or unbounded refinement")
        save(self.root / (label + ".json"), v)
        state, exports = self.native_file(label, lambda canvas: canvas.final_boards(b, v["concept"], v["palette"]))
        facts = source.measurements(state, {v["concept"]["id"]: v["palette"]})
        if facts["violations"]:
            raise ValueError("selected identity measured layout failed; source retained")
        save(self.root / (label + ".measurements.json"), facts)
        save(self.root / "selected.json", {"concept": v["concept"], "palette": v["palette"]})
        self.state["round"] = next_round
        self.commit()
        return self.receipt(label, fingerprint, {"status": "completed", "round": next_round, "round_label": f"{next_round:02}",
            "pngs": [r["path"] for r in exports if r["kind"] == "png"], "source": self.state["files"][label]["url"]},
            [self.root / (label + ".json"), self.root / (label + ".source.json"), self.root / (label + ".exports.json")])

    def handoff(self):
        round_number = self.state["round"]
        label = f"selected-r{round_number:02}"
        fingerprint = c.digest({"selected": sha(self.root / (label + ".json")), "critic": sha(self.root / f"critic-r{round_number:02}.json")})
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
             "clear_space_unit": "0.25 of symbol nominal box on every side", "minimum_symbol_px": selected["concept"]["minimum_symbol_px"],
             "proposed_minimum_lockup_px": 160, "not_publication_approved": True})
        brand = f'''# {b["product"]} / identity study

Selected concept: {selected["concept"]["name"]} ({selected["concept"]["id"]}).
{selected["concept"]["idea"]}
Trade-off: {selected["concept"]["tradeoff"]}

## Status and sources
Actual owner direction is saved; final approval remains a separate gate.
This packet approves no publication, production rebrand or app/CSS/logo change.
Facts and interpretations: brief.json; direction reasoning: owner-direction.json.
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
and other marks outside it. Proposed symbol minimum: {selected["concept"]["minimum_symbol_px"]}px;
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
        artifacts = [self.root / (label + ".json"), self.root / (label + ".source.json"), self.root / (label + ".exports.json"), self.root / f"BRAND-r{round_number:02}.md", self.root / f"tokens-r{round_number:02}.json"]
        self.state["final_artifact_hash"] = c.digest({a.name: sha(a) for a in artifacts})
        self.commit()
        manifest = {"run_id": self.run_id, "mode": self.mode, "round": round_number,
             "direction_owner_approved": self.mode == "real", "final_owner_approved": False,
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
        decision = c.approval_contract(json.loads(raw), kind="final", run_id=self.run_id,
            brief_hash=self.state["brief_hash"], artifact_hash=self.state["final_artifact_hash"], choices={"approve", "revise"},
            gate_only=gate_only, fictional=self.mode == "fixture")
        path = self.root / f'owner-final-r{self.state["round"]:02}.json'
        save(path, {**decision, "recorded_at": h.now(), "fictional_test": self.mode == "fixture"})
        if decision["decision"] == "revise":
            if self.state["round"] >= 2:
                raise ValueError("final owner revision is still pending: two paid refinements exhausted")
            if not decision.get("owner_note"):
                raise ValueError("revision requires actual owner guidance")
            self.state["final_feedback"] = decision
            self.commit()
            return {"status": "completed", "verdict": "request_changes", "final_owner_approved": False}
        self.state["final_approval"] = decision
        self.commit()
        manifest = load(self.root / "manifest.json")
        manifest["final_owner_approved"] = self.mode == "real"
        manifest["owner_final_receipt"] = path.name
        save(self.root / "manifest.json", manifest)
        return {"status": "completed", "verdict": "approved", "final_owner_approved": self.mode == "real", "ready_for_publication": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("brief", "budget", "explore", "revise", "palette", "critic", "direction", "prepare", "refine", "handoff", "final"))
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--mode", choices=("real", "fixture"), required=True)
    parser.add_argument("--budget-stage", choices=("initial", "refine"), default="initial")
    parser.add_argument("--native-gate", action="store_true")
    args = parser.parse_args()
    job = Job(args.workspace, args.run_id, args.mode)
    raw = os.getenv("LOGO_DATA", "")
    methods = {"brief": lambda: job.brief(raw), "budget": lambda: job.budget(raw, args.budget_stage),
        "explore": job.adopt_exploration, "revise": job.adopt_revision, "palette": job.adopt_palette, "critic": job.adopt_critic,
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
