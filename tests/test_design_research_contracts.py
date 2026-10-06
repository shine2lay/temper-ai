"""Rules of the design research step (Design queue #38): claims sourced or assumptions, playbook evidence
and families, research.json, gate answers, and the five measured audience axes."""
from __future__ import annotations

import copy
import importlib.util
import sys
from pathlib import Path

import pytest

BIN = Path(__file__).resolve().parents[1] / "configs" / "design" / "bin"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, BIN / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rc = _load("research_contracts")
axes = _load("design_axes")
PLAYBOOK = rc.load_playbook()

README = """# Lanternfish

Lanternfish is a night-shift log for lighthouse keepers.
Keepers write about forty entries per shift on a desktop terminal.
Most keepers have worked the lamps for more than ten years.

## Old notes (2023)
Keepers mostly log on paper tablets in the lamp room.

## Survey (2026)
Paper logs were retired in 2025; every keeper logs at the desk terminal.

## Brainstorm
Keepers want a playful, game-like log.
"""


@pytest.fixture()
def ws(tmp_path: Path) -> Path:
    (tmp_path / "source" / "docs").mkdir(parents=True)
    (tmp_path / "source" / "docs" / "README.md").write_text(README)
    return tmp_path


def claim(cid: str, text: str, quote: str | None, status: str = "sourced", **extra) -> dict:
    c = {"id": cid, "topic": "users", "text": text, "status": status, **extra}
    if quote is not None:
        c["source"] = {"file": "source/docs/README.md", "quote": quote}
    return c


def good_users() -> dict:
    return {
        "product": {"name": "Lanternfish", "what": "A night-shift log", "for_whom": "lighthouse keepers",
                    "value": "Logs a shift quickly", "meaning": "a small light in the dark", "claims": ["c1"]},
        "groups": [{"name": "Keepers", "role": "primary", "summary": "Experienced keepers on night shifts.",
                    "claims": ["c2", "c3", "c4", "c5", "c6"]}],
        "claims": [
            claim("c1", "A night-shift log for keepers", "a night-shift log for lighthouse keepers"),
            claim("c2", "About forty entries a shift at a desktop", "write about forty entries per shift on a desktop terminal"),
            claim("c3", "Most have 10+ years", "worked the lamps for more than ten years"),
            claim("c4", "They used paper tablets", "Keepers mostly log on paper tablets", status="superseded",
                  superseded_by="c5", note="the 2026 survey says paper logs were retired"),
            claim("c5", "Everyone logs at the desk terminal", "every keeper logs at the desk terminal"),
            claim("c6", "Keepers want a game-like log", "Keepers want a playful, game-like log", status="rejected",
                  note="a brainstorm line with no evidence"),
        ],
        "assumptions": ["Keepers read the log in dim rooms"],
    }


# ---------------------------------------------------------------- claims

def test_good_users_pass(ws: Path) -> None:
    assert rc.check_users(good_users(), ws) == []
    md = rc.users_md(good_users())
    assert "[source/docs/README.md]" in md and "## Not used" in md and "c4 (superseded)" in md


def test_quote_must_be_in_the_cited_file(ws: Path) -> None:
    u = good_users()
    u["claims"][1]["source"]["quote"] = "write about ninety entries per shift"
    assert any("quote is not in source/docs/README.md" in p for p in rc.check_users(u, ws))


def test_quote_matching_ignores_markdown_and_quotes(ws: Path) -> None:
    assert rc.quote_in("“Lanternfish is a night-shift log”", README)
    assert not rc.quote_in("night", README)  # too short to prove anything


def test_unsourced_claim_must_be_an_assumption(ws: Path) -> None:
    u = good_users()
    u["claims"][2].pop("source")
    assert any(p.startswith("c3: source is") for p in rc.check_users(u, ws))
    u["claims"][2].update(status="assumption", note="no source says so")
    assert rc.check_users(u, ws) == []


def test_source_outside_pack_refused(ws: Path) -> None:
    u = good_users()
    u["claims"][1]["source"]["file"] = "../etc/passwd"
    assert any("a path in the pack" in p for p in rc.check_users(u, ws))


def test_web_claim_needs_the_page(ws: Path) -> None:
    u = good_users()
    u["claims"][2]["source"] = {"url": "https://example.org/keepers", "quote": "keepers serve for decades"}
    assert any("not checked in this run" in p for p in rc.check_users(u, ws))
    assert any("could not be opened" in p for p in rc.check_users(u, ws, web={"https://example.org/keepers": None}))
    page = {"https://example.org/keepers": "Most keepers serve for decades at one light."}
    assert rc.check_users(u, ws, web=page) == []
    assert rc.claim_urls(u) == ["https://example.org/keepers"]


def test_superseded_needs_a_sourced_replacement(ws: Path) -> None:
    u = good_users()
    u["claims"][3]["superseded_by"] = "c6"
    assert any("superseded_by names the sourced claim" in p for p in rc.check_users(u, ws))


def test_rejected_and_assumption_say_why(ws: Path) -> None:
    u = good_users()
    u["claims"][5].pop("note")
    assert any("a rejected claim says why" in p for p in rc.check_users(u, ws))


def test_a_long_note_is_named_as_too_long(ws: Path) -> None:
    u = good_users()
    u["claims"][5]["note"] = "Rejected because nothing in the pack supports it. " * 8  # ~400 characters
    assert rc.check_users(u, ws) == []
    u["claims"][5]["note"] = "x" * (rc.NOTE_MAX + 1)
    problems = rc.check_users(u, ws)
    assert any(f"keep it under {rc.NOTE_MAX}" in p for p in problems)
    assert not any("says why" in p for p in problems)


def test_exactly_one_primary_group(ws: Path) -> None:
    u = good_users()
    u["groups"].append({"name": "Owners", "role": "primary", "summary": "Lighthouse owners who pay.", "claims": ["c1"]})
    assert any("exactly one group is primary" in p for p in rc.check_users(u, ws))


# ---------------------------------------------------------------- directions and the playbook

def candidate(cid: str, family: str, ctx: str = "marketing-landing-general", **over) -> dict:
    d = {"id": cid, "name": f"Direction {cid}", "context": ctx, "family": family,
         "why": "Suits experienced keepers who scan quickly.",
         "axes": {"density": "high", "type_scale": "compact", "colour_energy": "low", "motion": "low", "copy_tone": "expert"},
         "principles": ["Show the work", "Quiet colour"], "do": ["dense tables", "plain words"],
         "dont": ["confetti", "stock photos"], "follow": ["log on the left"], "differentiate": ["night-friendly view"],
         "evidence": ["E001", "E055"], "palette": "deep navy with one amber accent", "type": "compact grotesk, 15 px body"}
    d.update(over)
    return d


def direction(**over) -> dict:
    d = {"contexts": [{"id": "marketing-landing-general", "role": "page", "why": "The job is the product's homepage."},
                      {"id": "saas-b2b-settings", "role": "product", "why": "An all-day work tool for experts."}],
         "candidates": [candidate("D1", "flat 2.0"),
                        candidate("D2", "editorial", axes={"density": "medium", "type_scale": "medium",
                                                            "colour_energy": "medium", "motion": "low", "copy_tone": "neutral"})],
         "recommended": {"id": "D1", "reason": "The users are experts who want the work shown."},
         "taste": {"ids": ["T3"], "note": "Owner likes depth; kept as a bias."}, "assumptions": []}
    d.update(over)
    return d


def test_direction_good() -> None:
    assert rc.check_direction(direction(), PLAYBOOK, job="homepage", fixed=[]) == []


def test_family_must_be_allowed_by_the_playbook() -> None:
    d = direction()
    d["candidates"][0]["family"] = "neo-brutalism"
    assert any("family is a style the playbook allows" in p for p in rc.check_direction(d, PLAYBOOK, job="homepage", fixed=[]))
    d["candidates"][0].update(family="flat 2.0 / Material with standard patterns", context="saas-b2b-settings")
    assert rc.check_direction(d, PLAYBOOK, job="homepage", fixed=[]) == []


def test_unknown_context_and_evidence_refused() -> None:
    d = direction()
    d["contexts"][1]["id"] = "freight-dispatch"
    assert any("not in the playbook" in p for p in rc.check_direction(d, PLAYBOOK, job="homepage", fixed=[]))
    d = direction()
    d["candidates"][0]["evidence"] = ["E001", "E999"]
    assert any("E999" in p for p in rc.check_direction(d, PLAYBOOK, job="homepage", fixed=[]))


def test_page_job_needs_one_page_context() -> None:
    d = direction()
    d["contexts"][0]["role"] = "product"
    assert any("role page" in p for p in rc.check_direction(d, PLAYBOOK, job="homepage", fixed=[]))
    assert not any("role page" in p for p in rc.check_direction(d, PLAYBOOK, job="logo", fixed=[]))


def test_fixed_parts_stay_fixed() -> None:
    probs = rc.check_direction(direction(), PLAYBOOK, job="homepage", fixed=["colour"])
    assert any('palette is "fixed"' in p for p in probs)
    d = direction()
    for c in d["candidates"]:
        c["palette"] = "fixed"
    assert rc.check_direction(d, PLAYBOOK, job="homepage", fixed=["colour"]) == []


def test_too_long_texts_are_named_with_their_length() -> None:
    # Trial 6a10a704: a context's why 2 characters over its cap read only "role and why", and the
    # director's revise loop ran out without trimming it.
    d = direction()
    d["contexts"][1]["why"] = "w" * 402
    probs = rc.check_direction(d, PLAYBOOK, job="homepage", fixed=[])
    assert any("why is 402 characters; keep it 10-400" in p for p in probs)
    d = direction()
    d["candidates"][0].update(name="n" * 61, why="y" * 650, do=["plain words", "d" * 301])
    probs = rc.check_direction(d, PLAYBOOK, job="homepage", fixed=[])
    assert any("name is 61 characters; keep it 2-60" in p and "why is 650 characters; keep it 10-600" in p for p in probs)
    assert any("do line 2 is 301 characters; keep each line at most 300" in p for p in probs)
    d = direction(recommended={"id": "D1", "reason": "r" * 601})
    assert any("reason is 601 characters" in p for p in rc.check_direction(d, PLAYBOOK, job="homepage", fixed=[]))
    # A missing text still reads as missing, with no length.
    d = direction()
    d["contexts"][1].pop("why")
    probs = rc.check_direction(d, PLAYBOOK, job="homepage", fixed=[])
    assert any(p.endswith("and why (10-400 characters)") for p in probs)


def test_too_long_users_texts_are_named(ws: Path) -> None:
    u = good_users()
    u["groups"][0]["summary"] = "s" * 401
    u["claims"][0]["text"] = "t" * 401
    probs = rc.check_users(u, ws)
    assert any("summary is 401 characters; keep it 10-400" in p for p in probs)
    assert any("text is 401 characters; keep it 5-400" in p for p in probs)


def test_twin_directions_refused() -> None:
    d = direction()
    d["candidates"][1] = candidate("D2", "flat 2.0")
    assert any("same direction" in p for p in rc.check_direction(d, PLAYBOOK, job="homepage", fixed=[]))


def test_axes_must_use_known_levels() -> None:
    d = direction()
    d["candidates"][0]["axes"]["motion"] = "lots"
    assert any("axes sets" in p for p in rc.check_direction(d, PLAYBOOK, job="homepage", fixed=[]))


def research_doc(ws: Path) -> dict:
    d = direction()
    return {"version": rc.VERSION, "product": "Lanternfish", "job": "homepage", "inventory": {"status": "none"},
            "users": good_users(), "contexts": rc.playbook_recommendations(PLAYBOOK, d["contexts"]),
            "category": {"sites": []}, "directions": d["candidates"], "recommended": d["recommended"],
            "taste": d["taste"], "assumptions": [], "files_to_create": ["DESIGN.md", "tokens.json"], "fixed": []}


def test_research_json_checks(ws: Path) -> None:
    r = research_doc(ws)
    assert rc.check_research(r, PLAYBOOK) == []
    bad = copy.deepcopy(r)
    bad["contexts"][0]["recommendations"]["avoid"] = ["nothing"]
    assert any("copied verbatim" in p for p in rc.check_research(bad, PLAYBOOK))
    bad = copy.deepcopy(r)
    bad["directions"][0]["why"] += " (E998)"
    assert any("E998" in p for p in rc.check_research(bad, PLAYBOOK))
    bad = copy.deepcopy(r)
    bad["directions"][1]["family"] = "skeuomorphism"
    assert any("family not allowed" in p for p in rc.check_research(bad, PLAYBOOK))
    bad = copy.deepcopy(r)
    del bad["users"]["claims"][1]["source"]["quote"]
    assert any("carries its quote" in p for p in rc.check_research(bad, PLAYBOOK))
    bad = copy.deepcopy(r)
    del bad["fixed"]
    assert rc.check_research(bad, PLAYBOOK) == ["research.json has fixed"]


def test_every_playbook_context_family_is_checkable() -> None:
    for c in PLAYBOOK["contexts"]:
        assert rc.allowed_families(c), c["id"]
        assert set(c["evidence"]) <= rc.evidence_ids(PLAYBOOK)


# ---------------------------------------------------------------- category

def test_category_pick_and_read() -> None:
    sites = [{"id": f"s{i}", "name": f"Site {i}", "url": f"https://s{i}.example.com", "kind": "leader" if i < 4 else "adjacent",
              "why": "category leader"} for i in range(6)]
    assert rc.check_category_pick({"category": "keeper logs", "sites": sites}) == []
    assert any("6-10" in p for p in rc.check_category_pick({"category": "keeper logs", "sites": sites[:5]}))
    read = {"expect": [{"text": "log first", "sites": ["s0", "s1"]}] * 3,
            "stand_out": [{"text": "night view", "why": "keepers work at night"}] * 2,
            "marks": [{"site": "s0", "family": "wordmark", "description": "plain name"}]}
    captured = ["s0", "s1"]
    assert rc.check_category_read(read, captured, marks_needed=False) == []
    assert any("missing: ['s1']" in p for p in rc.check_category_read(read, captured, marks_needed=True))
    read["expect"][0] = {"text": "log first", "sites": ["s0", "s9"]}
    assert any("captured sites" in p for p in rc.check_category_read(read, captured, marks_needed=False))


# ---------------------------------------------------------------- the research gate

def test_gate_answer_records_who_decided() -> None:
    a = rc.gate_answer({"decided_by": "design", "direction": "D1", "users": "confirm", "reasons": "fits the experts"},
                       ["D1", "D2"], rc.REAL_DECIDERS)
    assert a["decided_by"] == "design" and a["direction"] == "D1"
    with pytest.raises(ValueError, match="decided_by"):
        rc.gate_answer({"direction": "D1", "users": "confirm", "reasons": "fits users"}, ["D1"], rc.REAL_DECIDERS)
    with pytest.raises(ValueError, match="decided_by"):
        rc.gate_answer({"decided_by": "fixture-test", "direction": "D1", "users": "confirm", "reasons": "fits users"},
                       ["D1"], rc.REAL_DECIDERS)
    f = rc.gate_answer({"decided_by": "fixture-test", "direction": "D2", "users": "confirm", "reasons": "scripted"},
                       ["D1", "D2"], (rc.FIXTURE_DECIDER,))
    assert f["decided_by"] == "fixture-test"


def test_gate_answer_owner_and_corrections() -> None:
    with pytest.raises(ValueError, match="his own words"):
        rc.gate_answer({"decided_by": "owner", "direction": "D1", "users": "confirm", "reasons": "he said so"},
                       ["D1"], rc.REAL_DECIDERS)
    ok = rc.gate_answer({"decided_by": "owner", "direction": "D1", "users": "confirm", "reasons": "his call",
                         "notes": "go with D1", "source": "home chat m1"}, ["D1"], rc.REAL_DECIDERS)
    assert ok["source"] == "home chat m1"
    with pytest.raises(ValueError, match="source is for the owner"):
        rc.gate_answer({"decided_by": "design", "direction": "D1", "users": "confirm", "reasons": "fits users",
                        "source": "x"}, ["D1"], rc.REAL_DECIDERS)
    with pytest.raises(ValueError, match="corrections"):
        rc.gate_answer({"decided_by": "design", "direction": "D1", "users": "correct", "reasons": "fits users"},
                       ["D1"], rc.REAL_DECIDERS)
    with pytest.raises(ValueError, match="not an approval flag"):
        rc.gate_answer({"approval": True}, ["D1"], rc.REAL_DECIDERS)


# ---------------------------------------------------------------- measured axes

def facts(**over) -> dict:
    f = {"first_items": 60, "first_words": 150, "first_fill": 0.5, "sizes": {"14": 900, "40": 30}, "display_px": 40,
         "pixels": {"mean_chroma": 0.01, "saturated_share": 0.02, "lightness_spread": 0.3},
         "animated": 1, "loops": 0, "animation_seconds": 0.4,
         "text": "ETA 14:20. Load 4821 to DAL via I-35, 42,000 lb. Reassign driver; check HOS and ELD status. "
                 "Dispatch board shows 64 loads across 3 terminals. Detention billing at 2 h."}
    f.update(over)
    return f


def test_levels_dense_expert_page() -> None:
    lv = axes.levels(facts())
    assert {k: v["level"] for k, v in lv.items()} == {"density": "high", "type_scale": "compact", "colour_energy": "low",
                                                       "motion": "low", "copy_tone": "expert"}


def test_levels_light_friendly_page() -> None:
    lv = axes.levels(facts(first_items=12, first_words=40, sizes={"18": 600, "88": 20}, display_px=88,
                           pixels={"mean_chroma": 0.09, "saturated_share": 0.4}, animated=6, loops=0, animation_seconds=5,
                           text="You've got this! We'll help you plan your week. Spend what's safe, save the rest. "
                                "It's your money, and you're in charge. Start in two minutes."))
    assert {k: v["level"] for k, v in lv.items()} == {"density": "low", "type_scale": "large", "colour_energy": "high",
                                                       "motion": "medium", "copy_tone": "friendly"}


def test_agreement_and_axes_apart() -> None:
    a, b = axes.levels(facts()), axes.levels(facts(first_items=12, first_words=40, display_px=90))
    want = {"density": "high", "type_scale": "compact", "colour_energy": "low", "motion": "low", "copy_tone": "neutral"}
    got = axes.agreement(a, want)
    assert got["matched"] == 4 and got["total"] == 5 and got["misses"][0].startswith("copy_tone")
    assert axes.axes_apart(a, b) == 2
    assert set(axes.LEVELS) == set(rc.AXES) and all(axes.LEVELS[k] == rc.AXES[k] for k in rc.AXES)


def test_body_px_is_character_weighted() -> None:
    assert axes.body_px({"14": 100, "48": 10}) == 14
    assert axes.body_px({"14": 10, "18": 100}) == 18
    assert axes.body_px({}) == 0


def test_token_use_counts_colours_and_fonts() -> None:
    f = {"colours": {"#1a1a17": 10, "#f7f5ef": 8, "#2e7e4f": 2, "#ff00ff": 1}, "fonts": {"inter": 10, "fraunces": 90}}
    got = axes.token_use(f, ["#1A1A17", "#F7F5EF", "#2E7D4F"], ["Fraunces"])
    assert got["colour_share"] == round(20 / 21, 4) and got["off_token_colours"] == {"#ff00ff": 1}
    assert got["font_share"] == 0.9 and got["off_token_fonts"] == {"inter": 10}


def test_measure_code_is_complete() -> None:
    code = axes.measure_code("http://h:1", [{"name": "A", "url": "http://h:1/A/index.html"}])
    assert "__PAGE_FN__" not in code and "__COLOUR_FN__" not in code and "__ARGS__" not in code
    assert code.startswith("async (page) =>") and '"name": "A"' in code
    assert axes.chroma("#808080") < 0.001 < axes.chroma("#2E7D4F")
