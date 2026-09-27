"""Bets built side by side take turns (queue task 8, 2026-09-27).

Two bets built at the same time changed the same files: b034's PR conflicted twice, after b012 and
after b025 merged, and was merged with master by hand; b013 and b014 fixed the same bug in
mock_account.py two ways (RETRO gap 6). So once a bet is planned, epd_loop's `turn` node compares the
files its tasks change with every live bet's -- its plan (tasks.json) and its branch (its open PR).
Sharing one with a live bet that started planning before it, the bet waits until that bet is merged
or closed, then builds on master and is told which files changed there since its plan. Only an
earlier bet makes a bet wait, so two bets never wait for each other. The plan stage is told what the
other live bets change.

The rule is blockers() in bin/epd_loop.py; the wait is cmd_turn, a script node (agents/epd_turn).
"""

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from temper_ai.llm.prompt_renderer import PromptRenderer
from tests.test_epd import test_epd_loop

# The driver, loaded with its state in a temporary directory: test_epd_loop's fixture, by name.
L = test_epd_loop.L

ROOT = Path(__file__).resolve().parents[2]
AGENTS = ROOT / "configs" / "epd" / "agents"
WORKFLOWS = ROOT / "configs" / "epd" / "workflows"

MOCK = "backend/rollcall/adapters/mock_account.py"
SCHEMAS = "backend/rollcall/api/schemas.py"


def bet(
    status="running", started="2026-09-23T21:29:01+00:00", files=(), **state
) -> dict:
    """One bet as blockers() reads it (bets_in_line)."""
    return {
        "status": status,
        "title": "",
        "state": {"plan_started": started, "stages": {}, **state},
        "files": None if files is None else set(files),
    }


# b014 started planning at 21:29 UTC on 09-23 and b013 at 22:34; both changed mock_account.py.
B014 = "2026-09-23T21:29:01+00:00"
B013 = "2026-09-23T22:34:48+00:00"


class TestTheRule:
    def test_a_bet_sharing_a_file_with_an_earlier_live_bet_waits_for_it(self, L):
        bets = {
            "b014": bet(started=B014, files=[MOCK, "backend/rollcall/models.py"]),
            "b013": bet(started=B013, files=[MOCK, "frontend/src/pages/Analysis.tsx"]),
        }
        assert L.blockers("b013", bets) == [
            {"bet_id": "b014", "title": "", "status": "running", "files": [MOCK]}
        ]

    def test_no_shared_file_goes_on(self, L):
        bets = {
            "b014": bet(started=B014, files=[MOCK]),
            "b013": bet(started=B013, files=["frontend/src/pages/Analysis.tsx"]),
        }
        assert L.blockers("b013", bets) == []

    def test_a_later_bet_never_makes_an_earlier_one_wait(self, L):
        bets = {
            "b014": bet(started=B014, files=[MOCK]),
            "b013": bet(started=B013, files=[MOCK]),
        }
        assert L.blockers("b014", bets) == []

    @pytest.mark.parametrize("second", [B014, B013, "2026-09-23T20:00:00+00:00"])
    def test_two_bets_never_wait_for_each_other(self, L, second):
        """Equal start times too: the bet id breaks the tie, so the line is always one order."""
        bets = {
            "b014": bet(started=B014, files=[MOCK]),
            "b013": bet(started=second, files=[MOCK]),
        }
        waits = [b for b in bets if L.blockers(b, bets)]
        assert len(waits) == 1

    def test_test_fixtures_and_generated_files_do_not_count(self, L):
        shared = [
            "frontend/tests/fixtures/book.json",
            "docs/reference/api.md",
            "./docs/reference/cli.md",
        ]
        bets = {
            "b014": bet(started=B014, files=shared),
            "b013": bet(started=B013, files=shared),
        }
        assert L.counted_files(shared) == set()
        assert L.blockers("b013", bets) == []

    @pytest.mark.parametrize(
        "status",
        [
            "iterate",
            "kept",
            "killed",
            "rejected",
            "closed",
            "changes_requested",
            "proposed",
            "shipped",
            "stopped",
            "build_failed",
        ],
    )
    def test_a_bet_that_is_not_being_built_holds_nobody_up(self, L, status):
        """Finished, merged, waiting for the owner's word as a pitch, or stopped until the owner resumes it."""
        bets = {
            "b014": bet(status=status, started=B014, files=[MOCK]),
            "b013": bet(started=B013, files=[MOCK]),
        }
        assert L.blockers("b013", bets) == []

    def test_an_open_pr_holds_later_bets_up_until_it_is_merged(self, L):
        bets = {
            "b014": bet(status="pr_opened", started=B014, files=[MOCK]),
            "b013": bet(started=B013, files=[MOCK]),
        }
        assert [b["bet_id"] for b in L.blockers("b013", bets)] == ["b014"]
        bets["b014"]["state"]["stages"] = {"ship": {"merged": True}}
        assert L.blockers("b013", bets) == []

    def test_an_earlier_bet_still_planning_is_waited_for(self, L):
        """Which files it will change is not known until its plan is written."""
        bets = {
            "b014": bet(started=B014, files=None),
            "b013": bet(started=B013, files=[MOCK]),
        }
        assert L.blockers("b013", bets) == [
            {
                "bet_id": "b014",
                "title": "",
                "status": "running",
                "files": [],
                "planning": True,
            }
        ]

    def test_a_bet_started_before_its_place_was_kept_comes_first(self, L):
        legacy = {
            "status": "running",
            "title": "",
            "files": {MOCK},
            "state": {"stages": {"loop": {"_launched": "2026-09-30T00:00:00+00:00"}}},
        }
        bets = {
            "b047": legacy,
            "b103": bet(started="2026-09-28T00:00:00+00:00", files=[MOCK]),
        }
        assert [b["bet_id"] for b in L.blockers("b103", bets)] == ["b047"]
        assert L.blockers("b047", bets) == []


def plan(L, bet_id: str, *files: str) -> None:
    (L.BETS_DIR / bet_id).mkdir(exist_ok=True)
    L.write(
        L.BETS_DIR / bet_id / "tasks.json",
        json.dumps({"bet_id": bet_id, "tasks": [{"id": 1, "files": list(files)}]}),
    )


def live(
    L, bet_id: str, started: str, status: str = "running", title: str = ""
) -> None:
    L.ledger_upsert(bet_id, title=title or f"Title of {bet_id}", status=status)
    st = L.load_state(bet_id)
    st.update(bet_id=bet_id, status=status, plan_started=started)
    L.save_state(st)


class TestWhatTheLoopReads:
    def test_planned_files_are_none_before_the_plan(self, L):
        (L.BETS_DIR / "b103").mkdir()
        assert L.planned_files("b103") is None
        plan(L, "b103", MOCK, "./" + SCHEMAS, "frontend/tests/fixtures/x.json")
        assert L.planned_files("b103") == {MOCK, SCHEMAS}

    def test_the_plan_stage_is_told_what_the_other_live_bets_change(self, L):
        live(L, "b014", B014, title="Scan now says what it did")
        plan(L, "b014", MOCK)
        live(L, "b013", B013)
        plan(L, "b013", SCHEMAS)
        live(L, "b012", B014, status="iterate")  # merged: not listed
        plan(L, "b012", SCHEMAS)
        live(L, "b020", B014)  # still planning: nothing to list yet
        text = L.live_bets_md("b013")
        assert (
            text
            == f"- b014 (running): Scan now says what it did\n  its plan changes: {MOCK}"
        )
        assert (
            L.live_bets_md("b099").count("\n- ") == 1
        )  # b014 and b013, not b012 or b020

    def test_the_build_is_told_what_changed_on_master_since_its_plan(self, L):
        note = L.master_moved_note(
            "a" * 40, "b" * 40, {MOCK, SCHEMAS}, {MOCK}, ["b014"]
        )
        assert "after it waited for b014" in note
        assert (
            f"Files this plan's tasks change that changed on master since: {MOCK}."
            in note
        )
        assert f"Other files that changed: {SCHEMAS}." in note
        assert L.master_moved_note("a" * 40, "a" * 40, set(), {MOCK}, []) == ""


class TurnWorld:
    """cmd_turn's outside world: git in the pipeline's clone, the fetch, and a clock."""

    def __init__(self, L, monkeypatch, base="1" * 40, head="2" * 40, moved=(MOCK,)):
        self.fetches = 0
        self.sleeps = 0
        monkeypatch.setattr(L, "turn_fetch", self.fetch)
        monkeypatch.setattr(L, "branch_files", lambda bet_id, st: set())
        monkeypatch.setattr(L.time, "sleep", self.sleep)
        self.base, self.head, self.moved = base, head, moved

        def git(*args, env=None):
            if args[:1] == ("rev-parse",):
                return subprocess.CompletedProcess(
                    args, 0, stdout=self.head + "\n", stderr=""
                )
            if args[:2] == ("diff", "--name-only"):
                assert args[2:] == (self.base, self.head)
                return subprocess.CompletedProcess(
                    args, 0, stdout="\n".join(self.moved) + "\n", stderr=""
                )
            raise AssertionError(args)

        monkeypatch.setattr(L, "turn_git", git)

    def fetch(self):
        self.fetches += 1
        return ""

    def sleep(self, s):
        self.sleeps += 1


def turn(L, capsys, bet_id="b013") -> dict:
    L.cmd_turn(bet_id)
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


class TestTheWait:
    @pytest.fixture
    def pair(self, L, monkeypatch):
        live(L, "b014", B014, status="pr_opened")
        plan(L, "b014", MOCK)
        live(L, "b013", B013)
        plan(L, "b013", MOCK, SCHEMAS)
        L.write(L.BETS_DIR / "b013" / "plan_base", "1" * 40 + "\n")
        monkeypatch.setenv(
            "EPD_TURN_DESCRIPTION", "This task is bet b013 of the EPD loop."
        )
        monkeypatch.setattr(L, "TURN_POLL_S", 0)
        monkeypatch.setattr(L, "TURN_ROUND_S", 0)
        return TurnWorld(L, monkeypatch)

    def test_it_waits_and_the_node_goes_round_again(self, L, pair, capsys):
        out = turn(L, capsys)
        assert out["waiting"] is True
        assert [b["bet_id"] for b in out["blockers"]] == ["b014"]
        assert out["blockers"][0]["files"] == [MOCK]
        kept = json.loads((L.BETS_DIR / "b013" / "turn.json").read_text())
        assert kept["waited_for"] == ["b014"] and kept["since"]

    def test_once_the_earlier_bet_is_merged_it_builds_on_master_and_is_told_what_moved(
        self, L, pair, capsys
    ):
        turn(L, capsys)  # waits
        L.ledger_upsert("b014", status="iterate")  # merged, measured
        out = turn(L, capsys)
        assert out["waiting"] is False
        assert out["waited_for"] == ["b014"]
        assert out["master_moved"] == [MOCK]
        assert out["task_description"].startswith(
            "This task is bet b013 of the EPD loop."
        )
        assert "after it waited for b014" in out["task_description"]
        assert f"that changed on master since: {MOCK}" in out["task_description"]
        assert pair.fetches == 3  # at each start, and again once the wait was over
        assert json.loads((L.BETS_DIR / "b013" / "turn.json").read_text())["cleared"]

    def test_nothing_shared_goes_straight_on(self, L, pair, capsys):
        plan(L, "b013", SCHEMAS)
        pair.moved = ()
        out = turn(L, capsys)
        assert out == {
            "waiting": False,
            "blockers": [],
            "waited_for": [],
            "waited_min": 0,
            "master_moved": [],
            "task_description": "This task is bet b013 of the EPD loop.",
        }

    def test_it_looks_again_every_few_minutes_within_a_round(
        self, L, pair, capsys, monkeypatch
    ):
        monkeypatch.setattr(L, "TURN_POLL_S", 1)
        monkeypatch.setattr(L, "TURN_ROUND_S", 10)
        clock = iter(range(0, 1000, 3))
        monkeypatch.setattr(L.time, "monotonic", lambda: next(clock))
        out = turn(L, capsys)
        assert out["waiting"] is True
        assert pair.sleeps == 3

    def test_after_a_day_of_waiting_the_run_stops_for_the_owner(self, L, pair, capsys):
        L.write(
            L.BETS_DIR / "b013" / "turn.json",
            json.dumps({"since": "2026-09-20T00:00:00+00:00", "waited_for": ["b014"]}),
        )
        with pytest.raises(SystemExit) as stop:
            L.cmd_turn("b013")
        assert stop.value.code == 1
        printed = capsys.readouterr().out
        assert json.loads(printed.strip().splitlines()[0])["gave_up"] is True
        assert (
            "b014 (pr_opened: " + MOCK + ")" in printed
            and "resume --bet b013" in printed
        )

    def test_the_turn_command_runs_before_the_hosts_setup(
        self, L, pair, capsys, monkeypatch
    ):
        """The node runs as the container's user, which cannot chmod the owner's directories."""
        monkeypatch.setattr(L, "mkdir_shared", lambda p: pytest.fail("host setup ran"))
        monkeypatch.setattr(L.sys, "argv", ["epd_loop.py", "turn", "--bet", "b013"])
        L.main()
        assert (
            json.loads(capsys.readouterr().out.strip().splitlines()[-1])["waiting"]
            is True
        )


class TestTheLine:
    def test_a_start_or_a_retry_puts_the_bet_at_the_back(self, L, monkeypatch):
        """b034's first run failed at 04:09 on 09-23; b012 was built from 06:58, and b034, retried at
        07:03 in its old place, would have waited for nobody -- its PR conflicted."""
        test_epd_loop.propose(L)
        st = L.load_state("b001")
        st["plan_started"] = "2026-09-23T03:44:04+00:00"
        L.save_state(st)
        monkeypatch.setattr(L, "loop_inputs", lambda bet_id: {"bet_id": bet_id})
        monkeypatch.setattr(L, "post_run", lambda wf, inputs, ws: "run-2")
        monkeypatch.setattr(L, "ready_to_start", lambda bet_id: None)
        L._real_start_bet("b001", keep=False, wait=False)
        assert L.load_state("b001")["plan_started"] > "2026-09-27"

    @pytest.mark.parametrize(
        "at, moves", [("tasks", True), ("build", True), ("ship", False)]
    )
    def test_a_resume_at_the_plan_or_the_build_goes_to_the_back_and_a_later_one_keeps_its_place(
        self, L, monkeypatch, at, moves
    ):
        test_epd_loop.propose(L)
        st = L.load_state("b001")
        st.update(status="running", plan_started="2026-09-23T03:44:04+00:00")
        st["stages"]["loop"] = {"_run_id": "run-1"}
        L.save_state(st)
        L.ledger_upsert("b001", status="running")
        L.write(
            L.BETS_DIR / "b001" / "turn.json",
            json.dumps({"since": "2026-09-23T04:00:00+00:00"}),
        )
        monkeypatch.setattr(
            L,
            "get_run",
            lambda rid: {
                "status": "failed",
                "error_message": "1 node(s) failed: turn",
                "nodes": [
                    {"name": "tasks", "status": "completed"},
                    {"name": "turn", "status": "failed"},
                ],
            },
        )
        monkeypatch.setattr(
            L,
            "checkpoints",
            lambda rid: [
                {"node_name": n, "status": "completed", "sequence": i}
                for i, n in enumerate(L.STAGES)
            ],
        )
        monkeypatch.setattr(
            L,
            "in_server",
            lambda cmd: subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""),
        )
        monkeypatch.setattr(
            L, "loop_inputs", lambda bet_id, planning=True: {"bet_id": bet_id}
        )
        forks = []
        monkeypatch.setattr(L, "fork_run", lambda *a: forks.append(a) or "run-2")
        L.cmd_resume(at=at, bet="b001")
        # a run that failed at `turn` names no stage; the first one not done is build, forked after tasks
        assert (
            forks and forks[0][1] == L.STAGES.index(at) - 1
            if at != "tasks"
            else forks[0][1] == 0
        )
        assert not (L.BETS_DIR / "b001" / "turn.json").exists()  # a new 24 h wait
        moved = L.load_state("b001")["plan_started"] > "2026-09-27"
        assert moved is moves


class TestTheWiring:
    def loop(self) -> dict:
        return yaml.safe_load((WORKFLOWS / "epd_loop.yaml").read_text())["workflow"]

    def test_the_turn_node_sits_between_the_plan_and_the_build(self):
        nodes = {n["name"]: n for n in self.loop()["nodes"]}
        turn = nodes["turn"]
        # the plan box, called `tasks` before epd_loop v13 (queue task 15)
        assert turn["agent"] == "epd_turn" and turn["depends_on"] == ["plan"]
        assert turn["condition"] == {
            "source": "plan.structured.status",
            "operator": "equals",
            "value": "COMPLETE",
        }
        assert turn["loop_to"] == "turn" and turn["on_max_loops"] == "fail"
        assert turn["loop_condition"] == {
            "source": "turn.structured.waiting",
            "operator": "equals",
            "value": True,
        }
        # 45-minute rounds: more than a day of them before max_loops, so the 24 h limit is the one that stops it
        assert turn["max_loops"] * 45 / 60 > 24
        assert turn["input_map"] == {
            "bet_id": "input.bet_id",
            "repo_path": "input.repo_path",
            "task_description": "input.task_description",
        }
        build = nodes["build"]
        assert build["depends_on"] == ["turn"]
        assert (
            build["input_map"]["task_description"] == "turn.structured.task_description"
        )

    def test_the_turn_script_runs_the_drivers_turn_command(self):
        agent = yaml.safe_load((AGENTS / "epd_turn.yaml").read_text())["agent"]
        assert agent["type"] == "script" and agent["strict_undefined"] is True
        assert (
            2700 < agent["timeout_seconds"] <= 3600
        )  # a round (45 min) fits; a script's ceiling is 1 h
        assert (
            "/app/configs/epd/bin/epd_loop.py turn --bet {{ bet_id }}"
            in agent["script_template"]
        )
        assert "EPD_TURN_DESCRIPTION={{ task_description }}" in agent["script_template"]

    def test_the_other_live_bets_reach_the_plan_lead(self):
        plan_box = next(n for n in self.loop()["nodes"] if n["name"] == "plan")
        assert plan_box["input_map"]["live_bets"] == "input.live_bets"
        assert "live_bets" in self.loop()["inputs"]
        plan = yaml.safe_load((WORKFLOWS / "epd_plan.yaml").read_text())["workflow"]
        assert "live_bets" in plan["inputs"]
        lead = next(n for n in plan["nodes"] if n["name"] == "lead")
        assert lead["input_map"]["live_bets"] == "input.live_bets"

    def test_the_lead_sees_them_and_is_told_what_to_do_with_them(self):
        config = yaml.safe_load((AGENTS / "epd_plan_lead.yaml").read_text())["agent"]
        listed = (
            f"- b014 (running): Scan now says what it did\n  its plan changes: {MOCK}"
        )
        inputs = {
            "bet_id": "b013",
            "tasks_path": "/t.json",
            "plan_dir": "/p",
            "pitch": "p",
            "profile": "",
            "core": "",
            "design": "",
            "frontend": "",
            "backend": "",
            "numbers": "",
            "qa": "",
        }

        def shown(live_bets: str) -> str:
            return PromptRenderer().render(
                agent_config=config, input_data=inputs | {"live_bets": live_bets}
            )[1]["content"]

        assert "## Bets being built now (rule 9)" in shown(listed) and MOCK in shown(
            listed
        )
        assert "Bets being built now" not in shown("")
        assert "9. Other bets may be being built now" in config["system_prompt"]

    def test_the_driver_hands_the_list_to_the_run(self, L, monkeypatch):
        monkeypatch.setattr(L, "live_bets_md", lambda me: f"(the others, for {me})")
        test_epd_loop.propose(L)
        assert L.loop_inputs("b001")["live_bets"] == "(the others, for b001)"
