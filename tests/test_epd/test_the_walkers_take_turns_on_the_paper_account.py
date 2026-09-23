"""A proposal's walkers take turns on the Alpaca paper account.

Every walk used to run on a mock-broker tenant of its own, most of them with the market shut, and
five walks in three rounds reported the practice broker's unfilled entries as the product's
friction (b017). The walkers now sign in to the seed's Alpaca paper login while the market is
open. One account means one walker at a time, so the walks are chained; the personas design their
jobs for what the account holds and for the order they walk in; the report writer is told both.

The driver's side -- the market clock, the account's state, rounds taking turns -- is tested in
test_epd_loop. Here: the shipped YAML, and the prompts rendered through the real PromptRenderer.
"""

from pathlib import Path

import yaml

from temper_ai.llm.prompt_renderer import PromptRenderer

EPD = Path(__file__).resolve().parents[2] / "configs" / "epd"
MARKET = "the market is open; it closes Thu Sep 24 13:00 PDT"
HOLDS = "Cash $98,543.60.\nPositions:\n- F: 100 shares long, average $12.10, now $12.34"


def workflow(name: str) -> dict:
    return yaml.safe_load((EPD / "workflows" / f"{name}.yaml").read_text())["workflow"]


def nodes(name: str) -> dict:
    return {n["name"]: n for n in workflow(name)["nodes"]}


def render(agent: str, **inputs) -> tuple[str, str]:
    """The agent's system prompt and first message for these inputs, as the agent renders them."""
    config = yaml.safe_load((EPD / "agents" / f"{agent}.yaml").read_text())["agent"]
    messages = PromptRenderer().render(agent_config=config, input_data=inputs)
    return messages[0]["content"], messages[1]["content"]


def test_the_walks_run_one_after_another_all_on_the_paper_login():
    n = nodes("epd_report")
    assert not [k for k in n if k.startswith("seed_")], "no walker seeds a tenant of its own any more"
    assert n["walk_1"]["depends_on"] == ["personas"]
    assert n["walk_2"]["depends_on"] == ["personas", "walk_1"]
    assert n["walk_3"]["depends_on"] == ["personas", "walk_2"]
    for i in (1, 2, 3):
        m = n[f"walk_{i}"]["input_map"]
        assert m["email"] == "input.paper_email" and m["turn"] == str(i) and m["market"] == "input.market"
        assert m["persona"] == f"personas.structured.persona_{i}"
    assert n["personas"]["input_map"]["account_state"] == "input.account_state"
    assert n["report"]["input_map"]["account_state"] == "input.account_state"


def test_the_proposal_hands_the_round_the_login_the_account_and_the_market():
    passed = nodes("epd_propose")["report"]["input_map"]
    taken = workflow("epd_report")["inputs"]
    required = {k for k, v in taken.items() if v.get("required")}
    assert required <= set(passed), f"epd_propose leaves out {required - set(passed)}"
    assert set(passed) <= set(taken), f"epd_propose passes {set(passed) - set(taken)}, which epd_report does not take"
    given = workflow("epd_propose")["inputs"]
    assert all(given[k]["required"] for k in ("paper_email", "account_state", "market"))


def test_the_walker_signs_in_to_the_paper_login_and_knows_it_is_taking_a_turn():
    system, task = render("epd_walk", app_url="https://epd-r009.example", persona="You hold 100 F.",
                          turn="2", email="alpaca@rollcall.test", password="rollcall-qa", market=MARKET)
    assert "Sign in as alpaca@rollcall.test / rollcall-qa" in task
    assert f"Market: {MARKET}." in task and "walker 2 of 3" in task
    assert "simulator" not in system and "Never cancel or close an order or a" in system


def test_the_personas_are_designed_for_what_the_account_holds():
    system, task = render("epd_personas", profile="RollCall", goals="Trust first.", focus="",
                          last_outcome="", account_state=HOLDS, market=MARKET)
    assert HOLDS in task and f"Market: {MARKET}." in task
    assert '"empty"' not in system and "account_1" not in system, "the mock tenants are gone"


def test_the_report_writer_knows_the_walkers_took_turns_and_what_the_account_held():
    system, task = render("epd_report", report_path="/r/report.md", bet_id="r009", goals="Trust first.",
                          coverage="c", walk_1="w1", walk_2="w2", walk_3="w3", last_outcome="",
                          account_state=HOLDS, market=MARKET)
    assert HOLDS in task and "1 then 2 then 3" in task
    assert "The walkers took turns on one account" in system
