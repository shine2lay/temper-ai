"""Who may do what in Slack: the one decision, and the file it reads.

The decision is a plain function with no Slack, no database and no clock in
it, so every case can be asked here directly: each command, each button,
somebody's own run against somebody else's, the inputs a role forces, a
person nobody listed, and the owner.
"""

from __future__ import annotations

import pytest
import yaml

from temper_ai.integrations.slack.access import (
    ANY,
    AccessConfig,
    AccessConfigError,
    AccessWatcher,
    Role,
    decide,
    load_config,
    parse_config,
    refusal,
)

OWNER = "U0OWNER01"
LOMIT = "U0LOMIT02"
NOBODY = "U0NOONE03"
ROAMEE_CHANNEL = "C0ROAMEE1"

FILE = {
    "access": {
        "owner": OWNER,
        "default": "readonly",
        "people": {LOMIT: {"role": "roamee", "name": "lomit"}},
        "roles": {
            "readonly": {
                "commands": ["help", "list", "search", "ask"],
                "workflows": ["repo_answer"],
                "runs": "none",
                "gates": "none",
            },
            "roamee": {
                "commands": ["help", "list", "search", "status", "ask", "pick", "stop", "gate"],
                "workflows": ["repo_answer", "github_work"],
                "force": {"github_work": {"repo": "shine2lay/roamee"}},
                "repos": ["roamee"],
                "auto": ["repo_answer"],
                "runs": "own",
                "gates": "own",
            },
        },
    }
}


@pytest.fixture
def cfg() -> AccessConfig:
    return parse_config(FILE)


class TestTheOwner:
    def test_keeps_everything(self, cfg):
        for action in ("run", "pick", "stop", "gate", "status", "ask", "list", "search"):
            assert decide(cfg, OWNER, action, workflow="blog_writer", run_by=LOMIT), action

    def test_nothing_is_forced_on_the_owner(self, cfg):
        allowed = decide(cfg, OWNER, "run", workflow="github_work")
        assert allowed.force == {} and allowed.workflows is None

    def test_without_a_file_everyone_may_do_everything(self):
        open_rules = AccessConfig(on=False)
        assert decide(open_rules, NOBODY, "run", workflow="anything")
        assert decide(open_rules, NOBODY, "gate", run_by=OWNER)


class TestAnyoneNotListed:
    def test_may_ask_search_and_list(self, cfg):
        for action in ("help", "ask", "search", "list"):
            assert decide(cfg, NOBODY, action), action

    def test_may_not_start_stop_or_gate(self, cfg):
        for action in ("run", "pick", "stop", "gate"):
            refused = decide(cfg, NOBODY, action, workflow="blog_writer", run_by=NOBODY)
            assert not refused and refused.why, action

    def test_may_not_even_see_runs(self, cfg):
        assert not decide(cfg, NOBODY, "status", run_by=NOBODY)

    def test_the_refusal_is_one_line(self, cfg):
        line = refusal(decide(cfg, NOBODY, "run", workflow="blog_writer"))
        assert line.count("\n") == 0 and line.startswith(":lock:")


class TestARoleWithAPatch:
    def test_may_use_its_own_workflows_only(self, cfg):
        assert decide(cfg, LOMIT, "pick", workflow="github_work")
        assert not decide(cfg, LOMIT, "pick", workflow="blog_writer")
        assert not decide(cfg, LOMIT, "run", workflow="linear_work")

    def test_the_forced_inputs_come_with_the_allowance(self, cfg):
        allowed = decide(cfg, LOMIT, "pick", workflow="github_work")
        assert allowed.force == {"repo": "shine2lay/roamee"}
        assert decide(cfg, LOMIT, "pick", workflow="repo_answer").force == {}

    def test_the_interpreter_sees_only_its_workflows(self, cfg):
        assert decide(cfg, LOMIT, "pick").workflows == ("repo_answer", "github_work")
        assert decide(cfg, OWNER, "pick").workflows is None

    def test_a_safe_workflow_starts_without_a_click(self, cfg):
        assert decide(cfg, LOMIT, "pick", workflow="repo_answer").auto
        assert not decide(cfg, LOMIT, "pick", workflow="github_work").auto

    def test_only_its_own_repos_are_answerable(self, cfg):
        assert decide(cfg, LOMIT, "ask").repos == ("roamee",)
        assert decide(cfg, NOBODY, "ask").repos == ()

    def test_own_runs_only(self, cfg):
        for action in ("status", "stop", "gate"):
            assert decide(cfg, LOMIT, action, run_by=LOMIT), action
            assert not decide(cfg, LOMIT, action, run_by=OWNER), action
            # Nobody in Slack started it (a trigger did): not theirs either.
            assert not decide(cfg, LOMIT, action, run_by=""), action

    def test_a_proposal_built_for_someone_else_is_not_theirs_to_start(self, cfg):
        assert decide(cfg, LOMIT, "pick", workflow="github_work", run_by=LOMIT)
        assert not decide(cfg, LOMIT, "pick", workflow="github_work", run_by=OWNER)

    def test_the_list_of_what_is_going_is_allowed_but_narrowed(self, cfg):
        # run_by=None is "no run in question": the list itself is allowed,
        # and each run in it is then asked about one at a time.
        assert decide(cfg, LOMIT, "status", run_by=None)
        assert not decide(cfg, NOBODY, "status", run_by=None)


class TestChannels:
    def test_a_role_tied_to_a_channel_does_not_apply_elsewhere(self):
        body = yaml.safe_load(yaml.safe_dump(FILE))
        body["access"]["roles"]["roamee"]["channels"] = [ROAMEE_CHANNEL]
        cfg = parse_config(body)
        assert decide(cfg, LOMIT, "pick", channel=ROAMEE_CHANNEL, workflow="github_work")
        refused = decide(cfg, LOMIT, "pick", channel="C0SOMEWHERE", workflow="github_work")
        assert not refused and refused.role == "readonly"

    def test_a_channel_name_is_refused_because_slack_sends_ids(self):
        body = yaml.safe_load(yaml.safe_dump(FILE))
        body["access"]["roles"]["roamee"]["channels"] = ["#roamee"]
        with pytest.raises(AccessConfigError, match="not a channel id"):
            parse_config(body)


class TestForcedOnEverything:
    def test_a_star_forces_the_same_inputs_on_every_workflow(self):
        role = Role(name="r", force={ANY: {"repo": "roamee"}, "github_work": {"number": "7"}})
        assert role.forced("blog_writer") == {"repo": "roamee"}
        assert role.forced("github_work") == {"repo": "roamee", "number": "7"}


class TestTheFile:
    def test_an_unknown_key_in_a_role_fails_rather_than_being_ignored(self):
        with pytest.raises(AccessConfigError, match="unknown key"):
            parse_config({"access": {"roles": {"r": {"command": ["run"]}}}})

    def test_an_unknown_top_level_key_fails(self):
        with pytest.raises(AccessConfigError, match="unknown key"):
            parse_config({"access": {"rolls": {}}})

    def test_a_person_in_no_role_fails(self):
        with pytest.raises(AccessConfigError, match="no role"):
            parse_config({"access": {"roles": {"r": {}}, "people": {LOMIT: ""}}})

    def test_a_person_in_an_unknown_role_fails(self):
        with pytest.raises(AccessConfigError, match="there is no role 'roamee'"):
            parse_config({"access": {"roles": {"r": {}}, "people": {LOMIT: "roamee"}}})

    def test_an_unknown_default_role_fails(self):
        with pytest.raises(AccessConfigError, match="there is no role"):
            parse_config({"access": {"roles": {"r": {}}, "default": "nope"}})

    def test_something_that_is_not_a_user_id_fails(self):
        with pytest.raises(AccessConfigError, match="not a Slack user id"):
            parse_config({"access": {"roles": {"r": {}}, "people": {"lomit": "r"}}})

    def test_a_command_that_does_not_exist_fails(self):
        with pytest.raises(AccessConfigError, match="is not a command"):
            parse_config({"access": {"roles": {"r": {"commands": ["deploy"]}}}})

    def test_a_scope_that_is_not_own_all_or_none_fails(self):
        with pytest.raises(AccessConfigError, match="expected one of"):
            parse_config({"access": {"roles": {"r": {"runs": "sometimes"}}}})

    def test_force_must_be_inputs_per_workflow(self):
        with pytest.raises(AccessConfigError, match="expected a mapping of input name"):
            parse_config({"access": {"roles": {"r": {"force": {"github_work": "roamee"}}}}})

    def test_an_unknown_action_is_a_mistake_in_temper_not_in_the_file(self, cfg):
        with pytest.raises(ValueError, match="no such action"):
            decide(cfg, LOMIT, "deploy")


class TestReadingTheFileFromDisk:
    def write(self, root, where: str, body: dict) -> None:
        folder = root / "slack" / where if where else root / "slack"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "access.yaml").write_text(yaml.safe_dump(body))

    def test_no_file_means_everyone_may_do_everything(self, tmp_path):
        assert load_config(tmp_path).on is False
        assert decide(load_config(tmp_path), NOBODY, "run", workflow="anything")

    def test_the_local_file_is_used_instead_of_the_tracked_one(self, tmp_path):
        self.write(tmp_path, "", {"access": {"roles": {"readonly": {}}, "default": "readonly"}})
        self.write(tmp_path, "local", FILE)
        cfg = load_config(tmp_path)
        assert cfg.people == {LOMIT: "roamee"} and cfg.names == {LOMIT: "lomit"}
        assert cfg.path.endswith("local/access.yaml")

    def test_a_broken_file_keeps_the_rules_that_were_in_force(self, tmp_path):
        self.write(tmp_path, "", FILE)
        watcher = AccessWatcher(tmp_path)
        assert watcher.get().people == {LOMIT: "roamee"}
        (tmp_path / "slack" / "access.yaml").write_text("access:\n  roles: [not, a, mapping]\n")
        again = watcher.get()
        assert watcher.error and again.people == {LOMIT: "roamee"}, "the last good rules stay in force"

    def test_a_file_that_was_never_good_lets_nobody_but_the_owner_through(self, tmp_path):
        self.write(tmp_path, "", {"access": {"roles": "nonsense"}})
        watcher = AccessWatcher(tmp_path)
        cfg = watcher.get()
        assert watcher.error and cfg.on is True and cfg.roles == {}
        assert not decide(cfg, NOBODY, "run", workflow="anything")

    def test_a_changed_file_is_read_again(self, tmp_path):
        self.write(tmp_path, "", FILE)
        watcher = AccessWatcher(tmp_path)
        assert decide(watcher.get(), LOMIT, "pick", workflow="github_work")
        narrowed = yaml.safe_load(yaml.safe_dump(FILE))
        narrowed["access"]["roles"]["roamee"]["workflows"] = ["repo_answer"]
        self.write(tmp_path, "", narrowed)
        import os

        path = tmp_path / "slack" / "access.yaml"
        os.utime(path, (0, 0))   # the watcher reads by the file's stamp
        assert not decide(watcher.get(), LOMIT, "pick", workflow="github_work")
