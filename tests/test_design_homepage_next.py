"""The homepage workflow's W4e candidate (H4-H7): script findings wired in beside the live files.

design_homepage_v2_next and its twins (W8 design_homepage_review_next, W10
design_craft_bench_next, W11 design_homepage_copy_review_next and design_homepage_content_next)
run the B2 scripts where models used to count: the facts check (design_review_verify.py)
between the usability critics and the merge (H4), measured findings (design_measured_findings.py,
H5), craft anchors (design_craft_anchors.py, H6) and word checks (design_word_checks.py, H7).
The live workflow and agent files stay byte-identical to master until W8, W10 and W11 have
graded the candidate. Fixture: a real homepage review folder (tests/fixtures/
design_homepage_next/fernlight, made by the live measure and runtime stages on a bench page;
the screenshots are left out, the tests write empty tiles under the same names).
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import sys
from pathlib import Path

import pytest
import yaml

from temper_ai.config.importer import parse_yaml
from temper_ai.stage.models import WorkflowConfig

ROOT = Path(__file__).resolve().parents[1]
DESIGN = ROOT / "configs/design"
BIN = DESIGN / "bin"
FIX = ROOT / "tests/fixtures/design_homepage_next/fernlight"
sys.path.insert(0, str(BIN))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, BIN / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


verify = _load("design_review_verify")
hn = _load("design_homepage_next")
v2 = _load("design_homepage_v2")

LINK = (
    "div.hero-grid.wrap > div.hero-copy:nth-of-type(3) > div.actions > "
    "a.link-down:nth-of-type(2)"
)


def _workspace(tmp_path: Path) -> Path:
    """The fixture as a run's workspace: homepage/ and review/ with empty screenshot tiles."""
    ws = tmp_path / "ws"
    shutil.copytree(FIX, ws)
    review = ws / "review"
    for d in ("critic", "craft", "content", "shots"):
        (review / d).mkdir(exist_ok=True)
    capture = json.loads((review / "capture.json").read_text(encoding="utf-8"))
    for page in capture["pages"]:
        for view in page["views"]:
            for tile in view["tiles"]:
                (review / tile).write_bytes(b"")
    return ws


def _critic(review: Path, name: str, findings: list[dict]) -> None:
    (review / "critic" / f"{name}.json").write_text(
        json.dumps({"critic": name, "pages": ["index.html"], "findings": findings}),
        encoding="utf-8",
    )


# --------------------------------------------------------------------------- H4: the facts check


def test_verify_reads_a_homepage_review_folder_unchanged_in_shape(tmp_path):
    """H4's first step: design_review_verify.py reads the homepage's own review/ folder (one page,
    index.html; desktop and mobile facts; critic/*.json; shots/) as it is, and writes
    review/verify.json for the merge."""
    review = _workspace(tmp_path) / "review"
    _critic(
        review,
        "critic_a",
        [
            {
                "id": "F1",
                "page": "index.html",
                "viewport": "mobile",
                "element": f'`{LINK}` "Read how your schedule works"',
                "problem": "The text link under the button is too small to tap.",
                "evidence": "shots/index-mobile-2.png",
                "criterion": "2.5.8 Target Size (Minimum)",
                "kind": "judged",
                "severity": 2,
            },
            {
                "id": "F2",
                "page": "index.html",
                "viewport": "desktop",
                "element": "Price section",
                "problem": "The price reads as an afterthought.",
                "evidence": "",
                "kind": "judged",
                "severity": 2,
            },
        ],
    )
    _critic(
        review,
        "critic_b",
        [
            {
                "id": "F1",
                "page": "index.html",
                "viewport": "desktop",
                "element": "the three plan cards in Price",
                "problem": "The cards compete with the main action.",
                "evidence": "index-desktop-6",
                "kind": "judged",
                "severity": 2,
            }
        ],
    )
    assert verify.main(["--review", str(review)]) == 0
    out = json.loads((review / "verify.json").read_text(encoding="utf-8"))
    assert out["version"] == 1 and out["critics"] == ["critic_a", "critic_b"]
    assert out["unreadable_critics"] == []
    rows = {r["source_id"]: r for r in out["findings"]}
    assert set(rows) == {"critic_a:F1", "critic_a:F2", "critic_b:F1"}
    # Nothing measures that link's size, so its size claim is not checked (never contradicted).
    assert rows["critic_a:F1"]["verdict"] == "not checked"
    assert rows["critic_a:F1"]["checkable"] is True
    assert "index-mobile-2.png" in rows["critic_a:F1"]["checkable_why"]
    assert rows["critic_a:F2"]["checkable"] is False
    assert rows["critic_b:F1"]["checkable"] is True  # a tile named without ".png"
    assert out["summary"] == {
        "findings": 3,
        "contradicted": 0,
        "partly_contradicted": 0,
        "supported": 0,
        "not_checked": 3,
        "not_checkable": 1,
    }


def test_verify_contradicts_a_size_claim_the_homepage_facts_measure_as_passing(tmp_path):
    """The same folder with that link measured as a pass by the spacing exception: the facts
    check contradicts the claim, so the merge drops it (design_merge's INPUT)."""
    review = _workspace(tmp_path) / "review"
    path = review / "facts/index-mobile.json"
    facts = json.loads(path.read_text(encoding="utf-8"))
    facts["targets_pass"] = [
        {
            "sel": LINK,
            "name": "Read how your schedule works",
            "box": [24, 1078, 273, 20],
            "passes": "spacing",
            "nearest": {"edge": 30},
        }
    ]
    path.write_text(json.dumps(facts), encoding="utf-8")
    _critic(
        review,
        "critic_a",
        [
            {
                "id": "F1",
                "page": "index.html",
                "viewport": "mobile",
                "element": f'`{LINK}` "Read how your schedule works"',
                "problem": "Too small to tap: under 24 px tall.",
                "evidence": "shots/index-mobile-2.png",
                "criterion": "2.5.8",
                "kind": "judged",
                "severity": 2,
            }
        ],
    )
    verify.main(["--review", str(review)])
    out = json.loads((review / "verify.json").read_text(encoding="utf-8"))
    (row,) = out["findings"]
    assert row["verdict"] == "contradicted" and row["contradicted_pages"] == ["index.html"]
    assert "spacing exception" in row["contradicting_facts"][0]


# --------------------------------------------------------------------------- the live files stay as they are

# The live files the candidate copies or runs beside, pinned at W4e (2026-10-19, byte-identical to master
# 18d61ffe). Promoting the candidate (after W8, W10 and W11) changes them on purpose and updates these.
LIVE_SHA256 = {
    "workflows/design_homepage_v2.yaml": "4e13b0af6c6e247751267801bdb33223ee3b75ea69c951cd8061e3c801dd2406",
    "workflows/design_homepage_v2_bench.yaml": "4dff3b63e4fe55b7f972ba4c970692b4f172b3d99278d98a3ab65bd7b2284daf",
    "workflows/design_homepage_v2_fixture.yaml": "36882fab6fea6234a4c1798fc037cca1e0db8c24183ef2905575b278b2fb6349",
    "workflows/design_homepage_v2_pilot.yaml": "b22492221ca8a99b5c585d49cc2bb9c265fc2c7e01d159d3d68350fbfd2561f8",
    "workflows/design_review.yaml": "b6004ef127bc95057f5544566112d676e8147efeeb9df097daf4c939b9f0681b",
    "workflows/design_craft_bench.yaml": "2a8113faa8c0a8aa129e9a4124cc6588faaceb368579f05cd10d4e21e532b980",
    "agents/design_critic.yaml": "47728644cf76425e8c2bedcfd56536a8568a5b6c5dd229e9bdd6b9d66e1604ec",
    "agents/design_merge.yaml": "55412ee81d3f6cee5a607a562230694943eb49fa7337405c1e105a9355bca5af",
    "agents/design_homepage_craft_critic_v2.yaml": "3e62a17dc22042211298af14dc9c08a73f31e420c0c6726fffde06f767b69baf",
    "agents/design_homepage_content_critic_v2.yaml": "a4d732cb91e65ea863138cddafa9392964b2f1c26b9889de509baa858b3939ca",
    "agents/design_homepage_stage_v2.yaml": "066d018adf28191bdf0dea69a7776b826856f7406d148420f9f25fee1ba24739",
    "agents/design_verify.yaml": "3c4dfa0f2246b7e4d984e4fbe7f899a6d549934f024d3b5b809b42d51ec0cdfe",
    "agents/design_capture.yaml": "3dd509cb5a4464eee441eae10c668c800128d70f20ac63ac352af1f4f83ea73e",
    "agents/design_craft_bench_stage.yaml": "5623043c4a8942460631a93e9658311c0007a08107ba9085fb110ecee54704de",
    # Re-pinned for W3c (queue #98, first committed as 69bae180; Design home's decision, 2026-10-19 16:58 PDT):
    # the pairings stage names unreadable log lines instead of dropping them silently. On a readable log its
    # output is byte-identical (tests/test_design_homepage_v2_bad_inputs.py::
    # test_pairings_stage_on_a_clean_log_writes_the_same_bytes_as_before), and the live log
    # workspaces/.design/type-pairings.jsonl had 61 lines, 0 unreadable, at 16:52 PDT: no trial output moves.
    "bin/design_homepage_v2.py": "e82f33022f55ae47d849e11faaf8390714846684cc1726af5f312186d59e752d",
    "bin/design_review_verify.py": "2f2ca0bf9997dd31782c33a5ebffc44a8d729ed2b6850d30bafd6cc208bd6550",
    "bin/design_craft_bench.py": "c010ee576bf2617904777234d0095e7043b0f461314008cc68ee7805c30d1441",
}
LIVE_WORKFLOWS = ["design_homepage_v2", "design_homepage_v2_bench", "design_homepage_v2_fixture",
                  "design_homepage_v2_pilot", "design_review", "design_craft_bench"]
NEXT_WORKFLOWS = ["design_homepage_v2_next", "design_homepage_review_next", "design_craft_bench_next",
                  "design_homepage_copy_review_next", "design_homepage_content_next"]
NEXT_AGENTS = {  # candidate copy: the live agent it copies
    "design_critic_next": "design_critic",
    "design_merge_next": "design_merge",
    "design_homepage_craft_critic_v2_next": "design_homepage_craft_critic_v2",
    "design_homepage_content_critic_v2_next": "design_homepage_content_critic_v2",
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.mark.parametrize("rel", sorted(LIVE_SHA256))
def test_live_files_are_byte_identical_while_the_candidate_is_on_trial(rel):
    assert _sha(DESIGN / rel) == LIVE_SHA256[rel], (
        f"{rel} changed while design_homepage_v2_next is on trial: change the _next copy instead, or "
        "promote the candidate (and update LIVE_SHA256) once W8, W10 and W11 have graded it")


@pytest.mark.parametrize("name", LIVE_WORKFLOWS)
def test_live_workflows_never_call_the_candidate(name):
    text = (DESIGN / "workflows" / f"{name}.yaml").read_text(encoding="utf-8")
    raw = yaml.safe_load(text)["workflow"]
    assert not [n["name"] for n in raw["nodes"] if str(n.get("agent", "")).endswith("_next")]
    assert "design_homepage_next" not in text and "design_homepage_stage_next" not in text


# --------------------------------------------------------------------------- the candidate files load


def _workflow(name: str) -> tuple[dict, dict]:
    raw = yaml.safe_load((DESIGN / "workflows" / f"{name}.yaml").read_text(encoding="utf-8"))["workflow"]
    assert WorkflowConfig.from_dict(raw).name == name
    return raw, {n["name"]: n for n in raw["nodes"]}


@pytest.mark.parametrize("name", NEXT_WORKFLOWS)
def test_candidate_workflows_load_validate_and_use_existing_agents(name):
    raw, nodes = _workflow(name)
    parsed = parse_yaml(DESIGN / "workflows" / f"{name}.yaml")
    assert parsed["name"] == name and parsed["config_type"] == "workflow"
    for node in nodes.values():
        if node.get("agent"):
            assert (DESIGN / "agents" / f"{node['agent']}.yaml").is_file(), node["agent"]
        for dep in node.get("depends_on") or []:
            assert dep in nodes, (node["name"], dep)
        stage = (node.get("input_map") or {}).get("stage")
        if node.get("agent") == "design_homepage_stage_next":
            assert stage in hn.STAGES, (node["name"], stage)


@pytest.mark.parametrize("name", [*NEXT_AGENTS, "design_homepage_stage_next"])
def test_candidate_agents_load_under_their_own_names(name):
    parsed = parse_yaml(DESIGN / "agents" / f"{name}.yaml")
    assert parsed["name"] == name and parsed["config_type"] == "agent"


def test_candidate_agents_keep_the_live_model_and_one_version_up():
    for name, live in NEXT_AGENTS.items():
        nxt = yaml.safe_load((DESIGN / "agents" / f"{name}.yaml").read_text(encoding="utf-8"))["agent"]
        old = yaml.safe_load((DESIGN / "agents" / f"{live}.yaml").read_text(encoding="utf-8"))["agent"]
        assert nxt["version"] == old["version"] + 1
        for key in ("type", "provider", "model", "provider_config", "max_iterations", "total_timeout"):
            assert nxt.get(key) == old.get(key), (name, key)
        assert "tools" not in nxt and "```json" in nxt["system_prompt"]
    stage = yaml.safe_load((DESIGN / "agents/design_homepage_stage_next.yaml").read_text())["agent"]
    template = stage["script_template"]
    assert stage["type"] == "script" and "/app/configs/design/bin/design_homepage_next.py" in template
    assert "PASSWORD" not in template and "design_homepage_v2.py" not in template


# --------------------------------------------------------------------------- the wiring (H4-H7)


def test_full_candidate_puts_the_facts_check_between_the_critics_and_the_merge():
    """H4: design_verify runs after both usability critics; the merge waits for it, so its fallback
    (the facts check done by the model) has nothing to fall back from."""
    for name in ("design_homepage_v2_next", "design_homepage_review_next"):
        _, nodes = _workflow(name)
        assert nodes["critic_a"]["agent"] == nodes["critic_b"]["agent"] == "design_critic_next"
        assert nodes["critic_a"]["depends_on"] == nodes["critic_b"]["depends_on"] == ["measured"]
        assert nodes["review_verify"]["agent"] == "design_verify"
        assert set(nodes["review_verify"]["depends_on"]) == {"critic_a", "critic_b"}
        assert nodes["merge"]["agent"] == "design_merge_next" and nodes["merge"]["depends_on"] == ["review_verify"]
        assert nodes["merge_join"]["depends_on"] == ["merge"]
        assert nodes["merge_join"]["input_map"]["stage"] == "merge_join"


def test_full_candidate_wires_each_script_before_the_model_that_takes_it_as_given():
    raw, nodes = _workflow("design_homepage_v2_next")
    stage = {n: v["input_map"].get("stage") for n, v in nodes.items() if v.get("agent") == "design_homepage_stage_next"}
    assert {"measure", "measured", "craft_anchors", "deck_words", "page_words", "merge_join", "craft_join",
            "content_join", "copy_review_join"} <= set(stage.values())
    assert all(v["input_map"]["mode"] == "real" for v in nodes.values() if v.get("agent", "").startswith("design_homepage_stage"))
    # H5, H6: measured findings and craft anchors come from the measure stage's own capture.
    assert nodes["measured"]["depends_on"] == nodes["craft_anchors"]["depends_on"] == ["measure"]
    assert nodes["craft"]["agent"] == "design_homepage_craft_critic_v2_next"
    assert nodes["craft"]["depends_on"] == ["craft_anchors"] and nodes["craft_join"]["depends_on"] == ["craft"]
    # H7: deck mode after copy_check_draft, page mode in the review.
    assert nodes["deck_words"]["depends_on"] == ["copy_check_draft"]
    assert nodes["copy_review"]["agent"] == nodes["content"]["agent"] == "design_homepage_content_critic_v2_next"
    assert nodes["copy_review"]["depends_on"] == ["deck_words"] and nodes["copy_review"]["input_map"] == {"target": "deck"}
    assert nodes["copy_review_join"]["depends_on"] == ["copy_review"]
    assert nodes["copy_revise"]["depends_on"] == ["copy_review_join"]
    assert nodes["page_words"]["depends_on"] == ["runtime"] and nodes["content"]["depends_on"] == ["page_words"]
    assert nodes["content"]["input_map"] == {"target": "page"} and nodes["content_join"]["depends_on"] == ["content"]
    # The live combine reads what the joins write.
    assert nodes["combine"]["agent"] == "design_homepage_stage_v2"
    assert set(nodes["combine"]["depends_on"]) == {"merge_join", "craft_join", "runtime", "content_join"}
    assert nodes["next_round"]["loop_to"] == "plan_round"
    # Everything else is the live workflow's: same nodes, same agents.
    _, live = _workflow("design_homepage_v2")
    added = {"measured", "craft_anchors", "deck_words", "copy_review_join", "review_verify", "merge_join",
             "craft_join", "page_words", "content_join"}
    assert set(nodes) == set(live) | added
    swapped = {"measure", "critic_a", "critic_b", "merge", "craft", "copy_review", "content"}
    assert {n for n in live if live[n].get("agent") != nodes[n].get("agent")} == swapped
    assert set(raw["outputs"]) == set(yaml.safe_load(
        (DESIGN / "workflows/design_homepage_v2.yaml").read_text())["workflow"]["outputs"])


def test_benchmark_twins_run_the_candidate_stages():
    _, craft = _workflow("design_craft_bench_next")
    assert craft["craft"]["agent"] == "design_homepage_craft_critic_v2_next"
    assert set(craft["craft"]["depends_on"]) == {"craft_anchors", "measured"}
    assert [craft[n]["input_map"]["stage"] for n in ("prepare", "craft_anchors", "craft_join", "collect")] == [
        "bench_prepare", "craft_anchors", "craft_join", "bench_collect"]
    _, deck = _workflow("design_homepage_copy_review_next")
    assert deck["deck_words"]["depends_on"] == ["copy_check_draft"]
    assert deck["copy_review"]["input_map"] == {"target": "deck"}
    _, page = _workflow("design_homepage_content_next")
    assert page["page_words"]["depends_on"] == ["page_prepare"] and page["content"]["input_map"] == {"target": "page"}


# --------------------------------------------------------------------------- the candidate prompts


def _prompt(name: str) -> str:
    agent = yaml.safe_load((DESIGN / "agents" / f"{name}.yaml").read_text(encoding="utf-8"))["agent"]
    return " ".join((agent["system_prompt"] + "\n" + agent["task_template"]).split())


def test_candidate_critics_no_longer_ask_for_what_the_scripts_count():
    critic, merge = _prompt("design_critic_next"), _prompt("design_merge_next")
    craft, content = _prompt("design_homepage_craft_critic_v2_next"), _prompt("design_homepage_content_critic_v2_next")
    # H5: the usability critic writes judged findings only; the page checks' problems are measured.json's.
    assert '"kind": "measured" if facts.md shows it' not in critic and "review/measured.json" in critic
    for check in ("signifier", "text-over-image", "dark-small-text", "repeated-copy", "first-screen-action", "nav-fit"):
        assert f'"{check}"' not in critic
    # H4, H5: the merge never does the facts check itself and never rates a measured finding.
    assert "If verify.json is missing, do those checks yourself" not in merge
    assert "never do those checks yourself" in merge
    assert "facts.md measures it, OR" not in merge and "with one exception: for a measured" not in merge
    assert "review/measured.json" in merge and "is this element the page's primary action?" in merge
    # H6: the settled numbers are anchors.json's; empty columns are a fenced yes/no.
    assert "spacing share on a 4 px grid below 0.6" not in craft and "scale ratio below 2x" not in craft
    assert "more than 8 distinct text sizes" not in craft and "review/anchors.json" in craft
    assert "dead space, or a purposeful part of the layout" in craft and "candidate_answers" in craft
    # H7: the word checks the script counts are gone from the content checklist.
    assert "a paragraph over about three lines" not in content
    assert "a call to action that does not say what happens" not in content
    assert "a term renamed, a notice repeated" not in content and "words.json" in content


def test_candidate_prompts_write_where_the_joins_read():
    assert "review/merge.json" in _prompt("design_merge_next")
    assert "review/report-judged.md" in _prompt("design_merge_next")
    craft = _prompt("design_homepage_craft_critic_v2_next")
    # combine reads every review/craft/*.json as a critic: the critic writes beside it, the join into it.
    assert "write review/craft-critic.json" in craft and "write review/craft/craft.json" not in craft
    content = _prompt("design_homepage_content_critic_v2_next")
    assert "write review/content-critic.json" in content and "homepage/copy/review-critic.json" in content
    assert "review/critic/" not in content and "review/content/content.json" not in content


def test_candidate_critic_and_merge_share_one_severity_rule_text():
    rules = [_prompt(n).split("SEVERITY", 1)[1] for n in ("design_critic_next", "design_merge_next")]
    assert all("Nielsen" in r for r in rules)


# --------------------------------------------------------------------------- the stages on a real review folder


def _stage(name: str, ws: Path) -> dict:
    return hn.run(name, ws, argparse.Namespace(fixture=False, pilot=False, bench=True, site="", page=""), "")


def _critics_and_verify(review: Path) -> None:
    _critic(review, "critic_a", [{
        "id": "F1", "page": "index.html", "viewport": "mobile",
        "element": "hero button 'See a sample care plan'",
        "problem": "The main action sits below the first screen on phones.",
        "evidence": "shots/index-mobile-1.png", "kind": "judged", "severity": 2}])
    _critic(review, "critic_b", [{
        "id": "F1", "page": "index.html", "viewport": "desktop", "element": "the three plan cards in Price",
        "problem": "The cards compete with the main action.", "evidence": "shots/index-desktop-6.png",
        "kind": "judged", "severity": 2}])
    assert verify.main(["--review", str(review)]) == 0


def _merge(review: Path, **extra) -> None:
    (review / "merge.json").write_text(json.dumps({
        "critics": ["critic_a", "critic_b"],
        "findings": [{"id": "D1", "status": "single", "page": "index.html", "viewport": "desktop",
                      "element": "the three plan cards in Price", "problem": "The cards compete with the main action.",
                      "evidence": "shots/index-desktop-6.png", "criterion": "visual hierarchy", "kind": "judged",
                      "severity": 2, "found_by": ["critic_b"]}],
        "rejected": [], "answers": [],
        "covered": [{"source_ids": ["critic_a:F1"], "measured_id": "index-mobile-first-screen-action-1",
                     "summary": "the main action below the first screen"}], **extra}), encoding="utf-8")
    (review / "report-judged.md").write_text("# Judged findings\n\nD1 the plan cards.\n", encoding="utf-8")


def test_measured_and_anchor_stages_write_beside_the_critics_never_among_them(tmp_path):
    ws = _workspace(tmp_path)
    review = ws / "review"
    assert _stage("measured", ws)["measured_path"] == "review/measured.json"
    assert _stage("craft_anchors", ws)["anchors_path"] == "review/anchors.json"
    assert not list((review / "critic").iterdir()) and not list((review / "craft").iterdir())
    measured = json.loads((review / "measured.json").read_text(encoding="utf-8"))
    assert measured["viewports"] == {"index": ["desktop", "mobile"]}  # only what the review captured
    assert measured["primary_action"] == "See a sample care plan"  # from the brief's cta
    assert all("severity" in f and "level" not in f for f in measured["findings"])
    assert {f["viewport"] for f in measured["findings"]} <= {"desktop", "mobile"}
    assert "empty-column" not in {f["check"] for f in measured["findings"]}  # never a measured finding
    anchors = json.loads((review / "anchors.json").read_text(encoding="utf-8"))
    assert [c["rule"] for c in anchors["checks"]] == ["spacing-grid", "scale-ratio", "text-sizes", "font-loading"]
    (cand,) = anchors["candidates"]
    assert cand["check"] == "empty-column" and cand["answers"] == ["yes", "no"] and cand["if_yes"] in (2, 3)


def test_merge_join_refuses_without_the_facts_check_so_the_fallback_is_never_reached(tmp_path):
    ws = _workspace(tmp_path)
    review = ws / "review"
    _stage("measured", ws)
    _merge(review)
    with pytest.raises(ValueError, match="verify.json missing"):
        _stage("merge_join", ws)
    assert not (review / "findings.json").exists()


def test_merge_join_puts_each_measured_problem_once_beside_the_judged_findings(tmp_path):
    ws = _workspace(tmp_path)
    review = ws / "review"
    _stage("measured", ws)
    _critics_and_verify(review)
    _merge(review)
    out = _stage("merge_join", ws)
    assert out["findings_path"] == "review/findings.json" and out["covered"] == 1 and out["covered_unknown"] == 0
    assert out["left_to_craft_review"] == 1
    merged = json.loads((review / "findings.json").read_text(encoding="utf-8"))
    measured = [f for f in merged["findings"] if f["kind"] == "measured"]
    assert {f["check"] for f in measured} == {"repeated-copy", "first-screen-action"}
    assert len({(f["page"], f["check"], f["severity"]) for f in measured}) == len(measured)  # one per problem
    first = next(f for f in measured if f["check"] == "first-screen-action")
    assert "critic_a:F1" in first["source_ids"] and "critic_a" in first["found_by"]  # covered: credited, not repeated
    assert [f["id"] for f in merged["findings"] if f["kind"] == "judged"] == ["D1"]
    assert "empty-column" not in {f.get("check") for f in merged["findings"]}
    assert [c["id"] for c in merged["measured"]["left_to_craft_review"]] == ["index-desktop-empty-column-1"]
    report = (review / "report.md").read_text(encoding="utf-8")
    assert "| M1 |" in report and "# Judged findings" in report and "Left to the craft review" in report


def test_craft_join_settles_anchors_and_applies_the_empty_column_answer(tmp_path):
    ws = _workspace(tmp_path)
    review = ws / "review"
    _stage("craft_anchors", ws)
    critic = {"critic": "craft", "findings": [], "template_test": {"verdict": "distinctive", "evidence": "e"},
              "strengths_to_keep": [], "visual_purpose": [], "not_checked": []}
    for answer, expect in (("no", 0), ("yes", 1)):
        (review / "craft-critic.json").write_text(json.dumps({**critic, "candidate_answers": [
            {"candidate": "index-desktop-empty-column-1", "answer": answer, "evidence": "tile 6"}]}), encoding="utf-8")
        out = _stage("craft_join", ws)
        assert out["findings_path"] == "review/craft/craft.json" and out["candidates_confirmed"] == expect
        craft = json.loads((review / "craft/craft.json").read_text(encoding="utf-8"))
        assert [f["rule"] for f in craft["findings"] if f["kind"] == "anchored"] == ["text-sizes"]
        assert len([f for f in craft["findings"] if f["kind"] == "candidate"]) == expect
    assert [p.name for p in (review / "craft").glob("*.json")] == ["craft.json"]  # combine reads every file there


H12 = "H12 (queue #114): the measured vacancy rule is not built yet"


def _measured_vacancy(review: Path, answer: str, reason: str) -> None:
    """The vacancy pass's answer on the fixture's one empty column (index at desktop, in Price)."""
    path = review / "facts/index-desktop.json"
    facts = json.loads(path.read_text(encoding="utf-8"))
    (col,) = facts["page_checks"]["columns"]
    evidence = {"track": 2, "track_x": [459, 821], "cover": 1.0} if answer == "yes" else {
        "left": "div.plan:nth-of-type(1)", "right": "div.plan:nth-of-type(2)"}
    col["vacancy"] = {"answer": answer, "reason": reason, "evidence": evidence, "container": {
        "sel": "div.plans", "display": "grid", "tracks": [[78, 427], [459, 821], [853, 1202]],
        "placed": [1, 0 if answer == "yes" else 1, 1], "items": 3 if answer == "no" else 2}}
    path.write_text(json.dumps(facts), encoding="utf-8")


@pytest.mark.xfail(strict=True, reason=H12)
def test_craft_join_settles_the_empty_column_from_the_measured_vacancy(tmp_path):
    ws = _workspace(tmp_path)
    review = ws / "review"
    (review / "craft-critic.json").write_text(json.dumps({  # the critic no longer answers empty columns
        "critic": "craft", "findings": [], "template_test": {"verdict": "distinctive", "evidence": "e"},
        "strengths_to_keep": [], "visual_purpose": [], "not_checked": []}), encoding="utf-8")
    for answer, reason, expect in (("no", "between", 0), ("yes", "vacant_track", 1)):
        _measured_vacancy(review, answer, reason)
        _stage("craft_anchors", ws)
        out = _stage("craft_join", ws)
        assert (out["candidates_confirmed"], out["candidates_declined"], out["candidates_unanswered"]) == (
            expect, 1 - expect, 0)
        craft = json.loads((review / "craft/craft.json").read_text(encoding="utf-8"))
        found = [f for f in craft["findings"] if f["kind"] == "candidate"]
        assert len(found) == expect
        (row,) = craft["candidates"]
        assert (row["answer"], row["reason"]) == (answer, reason)
    assert "vacant_track" in found[0]["evidence"] and "the critic" not in found[0]["evidence"]
    assert found[0]["severity"] in (2, 3) and found[0]["measured_id"] == "index-desktop-empty-column-1"


@pytest.mark.xfail(strict=True, reason=H12)
def test_the_craft_critic_candidate_leaves_empty_columns_to_the_measure():
    craft = _prompt("design_homepage_craft_critic_v2_next")
    assert "EMPTY COLUMNS" not in craft and "candidate_answers" not in craft
    assert "dead space, or a purposeful part of the layout" not in craft and "anchors.json candidate" not in craft


@pytest.mark.xfail(strict=True, reason=H12)
def test_only_the_candidate_path_turns_the_vacancy_pass_on(monkeypatch):
    import inspect
    import os

    env = hn.mf.pc.VACANCY_ENV
    monkeypatch.delenv(env, raising=False)
    with hn.vacancy_pass():
        assert os.environ[env] == "1"
    assert env not in os.environ
    assert all("vacancy_pass()" in inspect.getsource(fn) for fn in (hn.measure, hn.bench_prepare))
    named = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "configs").rglob("*")
                   if p.is_file() and p.suffix in (".py", ".yaml", ".js", ".json", ".md")
                   and env in p.read_text(encoding="utf-8", errors="ignore"))
    assert named == ["configs/design/bin/design_page_checks.py"]  # live code reaches it only through the switch


def test_word_joins_take_the_script_findings_and_keep_one_finding_per_problem(tmp_path):
    ws = _workspace(tmp_path)
    review, copy = ws / "review", ws / "homepage/copy"
    # Page mode: the long paragraph the script counts goes into content.json with a quote that is on the page.
    assert _stage("page_words", ws)["words_path"] == "review/words.json"
    (review / "content-critic.json").write_text(json.dumps(
        {"target": "page", "summary": "s", "strengths": [], "findings": []}), encoding="utf-8")
    out = _stage("content_join", ws)
    assert out["findings_path"] == "review/content/content.json" and out["words"] == 1
    content = json.loads((review / "content/content.json").read_text(encoding="utf-8"))
    (word,) = content["findings"]
    assert word["rule"] == "long_paragraph" and word["kind"] == "word"
    assert word["quote"] in (review / "page-text.md").read_text(encoding="utf-8")
    # Deck mode: "More" is flagged by copy_contract (check.json) and by cta_verb; the review keeps one.
    deck = json.loads((copy / "copy.json").read_text(encoding="utf-8"))
    deck["ctas"]["secondary"] = "More"
    (copy / "copy.json").write_text(json.dumps(deck), encoding="utf-8")
    (copy / "check.json").write_text(json.dumps(
        {"problems": ["ctas.secondary: 'More' does not say what happens; name the action"]}), encoding="utf-8")
    assert _stage("deck_words", ws)["findings"] >= 1
    words = json.loads((copy / "words.json").read_text(encoding="utf-8"))
    assert "cta_verb" in {f["rule"] for f in words["findings"]}
    (copy / "review-critic.json").write_text(json.dumps(
        {"target": "deck", "summary": "s", "strengths": [], "findings": []}), encoding="utf-8")
    out = _stage("copy_review_join", ws)
    assert out["review_path"] == "homepage/copy/review.json" and out["covered_by_contract"] >= 1
    joined = json.loads((copy / "review.json").read_text(encoding="utf-8"))
    assert not [f for f in joined["findings"] if f.get("rule") == "cta_verb" and f["quote"] == "More"]


def test_live_combine_reads_what_the_candidate_joins_write(tmp_path):
    """End to end on the fixture, models stood in by their files: every join's output is read by the live
    combine stage (design_homepage_v2.py, unchanged), and no content finding is dropped for its quote."""
    ws = _workspace(tmp_path)
    review = ws / "review"
    for name in ("measured", "craft_anchors", "page_words"):
        _stage(name, ws)
    _critics_and_verify(review)
    _merge(review)
    (review / "craft-critic.json").write_text(json.dumps({
        "critic": "craft", "findings": [], "template_test": {"verdict": "distinctive", "evidence": "e"},
        "strengths_to_keep": [], "visual_purpose": [], "not_checked": [],
        "candidate_answers": [{"candidate": "index-desktop-empty-column-1", "answer": "yes", "evidence": "t"}]}),
        encoding="utf-8")
    (review / "content-critic.json").write_text(json.dumps(
        {"target": "page", "summary": "s", "strengths": [], "findings": []}), encoding="utf-8")
    for name in ("merge_join", "craft_join", "content_join"):
        _stage(name, ws)
    job = v2.Job(str(ws), fixture=False, bench=True)
    job.state["round"] = 1
    job.commit()
    out = job.combine()
    assert out["status"] == "completed" and out["content_dropped"] == 0
    assert out["by_source"]["usability"] == 3 and out["by_source"]["craft"] == 2 and out["by_source"]["content"] == 1


# --------------------------------------------------------------------------- H6: the spacing share from 4 px up
# Keyed cases from the W4e screen (2026-10-19, own headless browser): the spacing values CRAFT_CODE collected
# on two baseline pages, as {value in px: how many}. The v2.2 morrow page at 390 is off the grid only by 1-3 px
# hairlines (tile gaps and nudges): the live share 0.91 gave a level-2 spacing-grid false alarm, and it was
# unsteady between identical runs (0.89 and 0.91, one 1 px value more or less). The v2.1r morrow page at 1440
# is off the grid by real spacing (fluid gutters of 63 px, section padding of 115 px): it stays below 0.9.
V22_390 = {"1": 4, "2": 18, "3": 4, "4": 39, "8": 45, "12": 36, "16": 34, "20": 28, "24": 33, "32": 17, "40": 4,
           "48": 1, "56": 1, "64": 11}
MORROW_1440 = {"2": 4, "4": 19, "6": 2, "8": 35, "12": 38, "16": 31, "23": 1, "24": 55, "27": 1, "32": 13, "36": 1,
               "48": 5, "63": 9, "64": 1, "72": 3, "86": 2, "101": 1, "115": 9, "128": 1}


@pytest.mark.parametrize("hist, live, share, hairlines", [
    (V22_390, 0.91, 1, 26),  # trap: hairlines only -> no finding
    (MORROW_1440, 0.87, 0.89, 4),  # catch: real off-grid spacing still level 2
    ({"5": 3, "8": 1}, 0.25, 0.25, 0),  # off-grid values of 4 px and up still count
    ({"1": 3, "2": 1}, 0, 1, 4),  # nothing from 4 px up: nothing off the grid
])
def test_spacing_share_leaves_out_hairlines_and_keeps_real_off_grid_spacing(hist, live, share, hairlines):
    entry = hn.spacing_from({"spacing_values": len(hist), "spacing_on_4px": live, "spacing_histogram": dict(hist)})
    assert (entry["spacing_on_4px"], entry["spacing_on_4px_all"], entry["spacing_hairlines"], entry["spacing_from_px"]) == (
        share, live, hairlines, 4)
    level = {"1440": {**entry, "body_px": 18, "display_px": 76, "scale_ratio": 4.22, "text_sizes": 5,
                      "unloaded_families": []}}
    found = [f for f in _anchors(level)["findings"] if f["rule"] == "spacing-grid"]
    assert [f["severity"] for f in found] == ([] if share >= 0.9 else [2] if share >= 0.6 else [3])


def _anchors(metrics: dict) -> dict:
    return _load("design_craft_anchors").anchors(metrics)


def test_spacing_share_rounds_as_the_browser_does_and_leaves_old_metrics_alone():
    assert hn.js_round2(0.125) == 0.13 and hn.js_round2(0.135) == 0.14  # Math.round halves up
    assert hn.js_round2(1.0) == 1 and isinstance(hn.js_round2(1.0), int)
    assert hn.spacing_from({"spacing_on_4px": 0.5}) == {"spacing_on_4px": 0.5}  # no histogram: as measured


def test_candidate_measure_adds_one_histogram_line_to_the_live_craft_code():
    code = hn.spacing_code(v2.CRAFT_CODE)
    assert code.count("spacing_histogram") == 1 and v2.CRAFT_CODE.count("spacing_histogram") == 0
    assert code.replace(hn.HISTOGRAM, "") == v2.CRAFT_CODE
    with pytest.raises(RuntimeError, match="spacing line changed"):
        hn.spacing_code(v2.CRAFT_CODE.replace(hn.SPACING_LINE, ""))


def test_craft_facts_say_which_spacing_values_the_share_counts(tmp_path):
    review = _workspace(tmp_path) / "review"
    metrics = json.loads((review / "craft-metrics.json").read_text(encoding="utf-8"))
    metrics["390"] = hn.spacing_from({**metrics["390"], "spacing_histogram": dict(V22_390)})
    (review / "craft-metrics.json").write_text(json.dumps(metrics), encoding="utf-8")
    assert hn.note_spacing(review) == 1 and hn.note_spacing(review) == 0  # idempotent
    facts = (review / "craft-facts.md").read_text(encoding="utf-8").split("\n")
    assert facts[10] == (f"- spacing values {metrics['390']['spacing_values']}, share on a 4 px grid 1 (values from 4 px up; "
                         f"26 hairline values of 1-3 px left out; all values {metrics['390']['spacing_on_4px_all']})")
    assert facts[20] == "- spacing values 17, share on a 4 px grid 0.96"  # 1440 has no histogram: unchanged
