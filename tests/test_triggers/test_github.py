"""GitHub as a trigger source: who may start work, and which rule an event matches.

Pinned: only the allowed authors start anything (never the app itself, never
anyone else); the shipped rules match what they say (a "temper" label, an
@mention, a reply on a labelled issue) and nothing else; the automatic
review of new pull requests ships turned off; and the settings are read from
configs/github.
"""

from pathlib import Path

import pytest

from temper_ai.integrations.github.settings import GitHubSettings, load_settings
from temper_ai.triggers import github
from temper_ai.triggers.rules import load_triggers, render_inputs

ROOT = Path(__file__).resolve().parents[2]
CONFIGS = ROOT / "configs"
SETTINGS = GitHubSettings(app="shine-temper", allowed_authors=("shine2lay",))


def repository(name="shine2lay/temper-ai", private=False):
    return {"full_name": name, "private": private, "default_branch": "master"}


def issue_labeled(label="temper", sender="shine2lay", repo="shine2lay/temper-ai", labels=("temper",)):
    return "issues", {
        "action": "labeled",
        "issue": {"number": 12, "title": "Fix the typo", "body": "In the README", "state": "open",
                  "html_url": f"https://github.com/{repo}/issues/12", "user": {"login": "shine2lay"},
                  "labels": [{"name": n} for n in labels]},
        "label": {"name": label},
        "repository": repository(repo),
        "sender": {"login": sender, "type": "User"},
        "installation": {"id": 99},
    }


def comment(body="@shine-temper what does this do?", sender="shine2lay", on_pull=False,
            labels=(), repo="shine2lay/temper-ai"):
    issue = {"number": 7, "title": "A thing", "body": "", "state": "open", "user": {"login": "shine2lay"},
             "labels": [{"name": n} for n in labels]}
    if on_pull:
        issue["pull_request"] = {"url": f"https://api.github.com/repos/{repo}/pulls/7"}
    return "issue_comment", {
        "action": "created",
        "issue": issue,
        "comment": {"id": 555, "body": body, "html_url": f"https://github.com/{repo}/issues/7#c555",
                    "user": {"login": sender}},
        "repository": repository(repo),
        "sender": {"login": sender, "type": "Bot" if sender.endswith("[bot]") else "User"},
    }


def pull_opened(sender="shine2lay", draft=False, repo="shine2lay/temper-ai", action="opened"):
    return "pull_request", {
        "action": action,
        "number": 3,
        "pull_request": {"number": 3, "title": "Add a page", "body": "", "draft": draft, "state": "open",
                         "user": {"login": sender}, "head": {"ref": "add-page", "repo": {"full_name": repo}},
                         "base": {"ref": "master"}, "labels": []},
        "repository": repository(repo),
        "sender": {"login": sender, "type": "User"},
    }


def shipped(name):
    [trigger] = [t for t in load_triggers(CONFIGS, source="github") if t.name == name]
    return trigger


def fires(name, event):
    """Whether the shipped rule `name` starts work for this event (the settings' gate first)."""
    event_name, payload = event
    trigger = shipped(name)
    if not trigger.enabled or github.refusal(event_name, payload, SETTINGS):
        return False
    return github.matches(trigger.on, event_name, payload, SETTINGS)


class TestWhoMayStartWork:
    def test_the_owner_may(self):
        assert github.refusal(*issue_labeled(), SETTINGS) is None

    def test_someone_else_may_not(self):
        why = github.refusal(*issue_labeled(sender="stranger"), SETTINGS)
        assert why.startswith("skipped: stranger may not start temper")

    def test_the_app_itself_may_not(self):
        why = github.refusal(*comment(sender="shine-temper[bot]"), SETTINGS)
        assert why == "skipped: the app's own doing (shine-temper[bot])"

    def test_the_app_is_refused_even_when_listed(self):
        settings = GitHubSettings(app="shine-temper", allowed_authors=("shine2lay", "shine-temper[bot]"))
        assert github.refusal(*comment(sender="shine-temper[bot]"), settings).startswith("skipped: the app's")

    def test_logins_compare_whatever_the_case(self):
        assert github.refusal(*issue_labeled(sender="Shine2Lay"), SETTINGS) is None

    def test_other_events_start_nothing(self):
        assert github.refusal("ping", {"sender": {"login": "shine2lay"}}, SETTINGS) == \
            "skipped: ping event starts nothing"
        assert github.refusal("", {}, SETTINGS).startswith("skipped:")

    def test_no_one_allowed_means_no_one(self):
        settings = GitHubSettings(app="shine-temper", allowed_authors=())
        assert github.refusal(*issue_labeled(), settings).startswith("skipped: shine2lay may not")


class TestTheShippedRules:
    def test_a_temper_label_on_an_issue_starts_github_work(self):
        assert shipped("github_label").workflow == "github_work"
        assert fires("github_label", issue_labeled())

    def test_another_label_does_not(self):
        assert not fires("github_label", issue_labeled(label="bug", labels=("bug", "temper")))

    def test_the_label_put_on_by_someone_else_does_not(self):
        assert not fires("github_label", issue_labeled(sender="stranger"))

    def test_the_label_put_on_by_the_app_does_not(self):
        assert not fires("github_label", issue_labeled(sender="shine-temper[bot]"))

    def test_an_at_mention_starts_github_work_on_an_issue_or_a_pull_request(self):
        assert shipped("github_mention").workflow == "github_work"
        assert fires("github_mention", comment())
        assert fires("github_mention", comment("@shine-temper review this", on_pull=True))

    def test_a_comment_without_the_mention_does_not(self):
        assert not fires("github_mention", comment("looks good to me"))
        assert not fires("github_mention", comment("mail me at me@shine-temper.dev"))
        assert not fires("github_mention", comment("@shine-temper-ai hi"))  # another name

    def test_someone_else_s_mention_does_not(self):
        assert not fires("github_mention", comment(sender="stranger"))

    def test_the_app_s_own_comment_does_not_even_when_it_names_itself(self):
        assert not fires("github_mention", comment("I am @shine-temper", sender="shine-temper[bot]"))
        assert not fires("github_reply", comment("A question", sender="shine-temper[bot]", labels=("temper",)))

    def test_a_reply_on_a_labelled_issue_carries_the_work_on(self):
        assert shipped("github_reply").workflow == "github_work"
        assert fires("github_reply", comment("Use the second option", labels=("temper",)))
        assert not fires("github_reply", comment("Use the second option"))  # not labelled

    def test_the_automatic_pull_request_review_ships_turned_off(self):
        trigger = shipped("github_pr_review")
        assert trigger.enabled is False
        assert trigger.workflow == "github_review"
        assert not fires("github_pr_review", pull_opened())
        # What it would match once turned on:
        assert github.matches(trigger.on, *pull_opened(), SETTINGS)
        assert github.matches(trigger.on, *pull_opened(action="ready_for_review"), SETTINGS)
        assert not github.matches(trigger.on, *pull_opened(draft=True), SETTINGS)
        assert not github.matches(trigger.on, *pull_opened(action="closed"), SETTINGS)

    def test_the_label_rule_gives_the_workflow_what_it_needs(self):
        event_name, payload = issue_labeled()
        inputs = render_inputs(shipped("github_label"), github.with_context(event_name, payload))
        assert inputs == {"repo": "shine2lay/temper-ai", "number": "12", "kind": "issue", "why": "label",
                          "default_branch": "master", "private": "false", "head_ref": "",
                          "head_repo": "", "base_ref": ""}

    def test_the_mention_rule_names_the_comment(self):
        event_name, payload = comment(on_pull=True)
        inputs = render_inputs(shipped("github_mention"), github.with_context(event_name, payload))
        assert (inputs["kind"], inputs["number"], inputs["comment_id"], inputs["why"]) == \
            ("pull", "7", "555", "mention")


class TestTheOnKeys:
    def test_a_repo_filter(self):
        on = {"event": "issues", "repos": ["shine2lay/temper-ai"]}
        assert github.matches(on, *issue_labeled(), SETTINGS)
        assert not github.matches(on, *issue_labeled(repo="shine2lay/roamee"), SETTINGS)

    def test_a_repo_filter_by_owner(self):
        on = {"repos": "shine2lay/*"}
        assert github.matches(on, *issue_labeled(repo="shine2lay/roamee"), SETTINGS)
        assert not github.matches(on, *issue_labeled(repo="someone/roamee"), SETTINGS)

    def test_an_author_filter_narrows(self):
        assert not github.matches({"authors": ["someone"]}, *issue_labeled(), SETTINGS)
        assert github.matches({"authors": "SHINE2LAY"}, *issue_labeled(), SETTINGS)

    def test_pull_request_or_issue(self):
        assert github.matches({"pull_request": True}, *comment(on_pull=True), SETTINGS)
        assert not github.matches({"pull_request": True}, *comment(), SETTINGS)
        assert github.matches({"pull_request": False}, *comment(), SETTINGS)

    def test_mention_false_means_no_mention(self):
        assert github.matches({"mention": False}, *comment("thanks"), SETTINGS)
        assert not github.matches({"mention": False}, *comment(), SETTINGS)

    def test_an_unknown_key_is_an_error_not_a_filter(self):
        with pytest.raises(ValueError, match="unknown key"):
            github.matches({"labels": "temper"}, *issue_labeled(), SETTINGS)
        with pytest.raises(ValueError, match="true or false"):
            github.check_on({"mention": "yes"})


class TestMentions:
    @pytest.mark.parametrize("text", ["@shine-temper hi", "hey @shine-temper, look", "(@Shine-Temper)",
                                      "@shine-temper[bot] please", "line one\n@shine-temper"])
    def test_calls_on_the_app(self, text):
        assert github.mentions(text, "shine-temper")

    @pytest.mark.parametrize("text", ["shine-temper hi", "@shine-temperate", "@shine-temper-ai",
                                      "a@shine-temper", "https://x.dev/@shine-temper", ""])
    def test_does_not(self, text):
        assert not github.mentions(text, "shine-temper")


class TestTheSettings:
    def test_the_shipped_settings(self):
        settings = load_settings(CONFIGS)
        assert settings.app == "shine-temper"
        assert settings.allowed_authors == ("shine2lay",)
        assert settings.bot_login == "shine-temper[bot]"

    def test_a_local_file_wins(self, tmp_path):
        (tmp_path / "github" / "local").mkdir(parents=True)
        (tmp_path / "github" / "github.yaml").write_text("github:\n  app: one\n")
        (tmp_path / "github" / "local" / "github.yaml").write_text(
            "github:\n  app: '@shine-temper-ai[bot]'\n  allowed_authors: [a, '@b']\n")
        settings = load_settings(tmp_path)
        assert (settings.app, settings.allowed_authors) == ("shine-temper-ai", ("a", "b"))

    def test_no_file_means_the_defaults(self, tmp_path):
        assert load_settings(tmp_path) == GitHubSettings()

    def test_a_broken_file_means_the_defaults(self, tmp_path):
        (tmp_path / "github").mkdir()
        (tmp_path / "github" / "github.yaml").write_text("github: [unclosed\n")
        settings = load_settings(tmp_path)
        assert (settings.app, settings.allowed_authors) == ("shine-temper", ("shine2lay",))

    def test_the_folder_is_server_settings_not_a_workflow_config(self):
        from temper_ai.config.importer import NON_CONFIG_DIRS

        assert "github" in NON_CONFIG_DIRS
