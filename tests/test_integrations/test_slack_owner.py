"""The DM temper sends about itself, and who it goes to.

Not a run's notices -- those go through notify, which decides where each one belongs. This is
the one channel temper uses to talk about temper: the CI watcher's red/green, and the message a
start-up sends about the runs it picked back up. The tests below are mostly about it never
being the reason something else fails.
"""

import pytest

from temper_ai.integrations.slack import owner as O


class _Client:
    """A stand-in for the Slack client: remembers, answers, never touches the network."""

    def __init__(self, fails=False):
        self.posted = []
        self.opened = []
        self.fails = fails

    def open_dm(self, user):
        self.opened.append(user)
        if self.fails:
            raise RuntimeError("channel_not_found")
        return f"D-{user}"

    def post(self, channel, text):
        self.posted.append((channel, text))
        return {"ok": True}


@pytest.fixture
def client(monkeypatch):
    fake = _Client()
    monkeypatch.setattr(O, "_client", lambda: fake)
    monkeypatch.setattr("temper_ai.integrations.slack.client.bot_token", lambda: "xoxb-test")
    return fake


class TestWhoTheOwnerIs:
    def test_the_watchers_name_for_it_is_read(self, monkeypatch):
        """So the start-up message lands where the CI watcher's does."""
        monkeypatch.setenv("EPD_OWNER_SLACK_DM", "U-from-watcher")

        assert O.owner_dm() == "U-from-watcher"

    def test_tempers_own_name_for_it_works_too(self, monkeypatch):
        monkeypatch.delenv("EPD_OWNER_SLACK_DM", raising=False)
        monkeypatch.setenv("TEMPER_OWNER_SLACK_DM", "U-from-temper")

        assert O.owner_dm() == "U-from-temper"

    def test_otherwise_the_first_person_the_tools_may_dm(self, monkeypatch):
        monkeypatch.delenv("EPD_OWNER_SLACK_DM", raising=False)
        monkeypatch.delenv("TEMPER_OWNER_SLACK_DM", raising=False)

        class Config:
            agents = type("A", (), {"users": ["U-from-config", "U-someone-else"]})()

        monkeypatch.setattr("temper_ai.integrations.slack.config.load_config", lambda: Config())

        assert O.owner_dm() == "U-from-config"

    def test_nobody_set_is_not_an_error(self, monkeypatch):
        monkeypatch.delenv("EPD_OWNER_SLACK_DM", raising=False)
        monkeypatch.delenv("TEMPER_OWNER_SLACK_DM", raising=False)
        monkeypatch.setattr("temper_ai.integrations.slack.config.load_config",
                            lambda: (_ for _ in ()).throw(FileNotFoundError()))

        assert O.owner_dm() == ""


class TestTheMessage:
    def test_it_goes_to_the_owners_dm(self, client, monkeypatch):
        monkeypatch.setenv("EPD_OWNER_SLACK_DM", "U-owner")

        assert O.tell_owner("two runs came back") is True
        assert client.opened == ["U-owner"]
        assert client.posted == [("D-U-owner", "two runs came back")]

    def test_an_empty_message_is_not_sent(self, client):
        assert O.tell_owner("   ") is False
        assert client.posted == []

    def test_no_owner_means_no_message_and_no_error(self, client, monkeypatch):
        monkeypatch.delenv("EPD_OWNER_SLACK_DM", raising=False)
        monkeypatch.delenv("TEMPER_OWNER_SLACK_DM", raising=False)
        monkeypatch.setattr(O, "owner_dm", lambda: "")

        assert O.tell_owner("nobody to tell") is False
        assert client.posted == []

    def test_no_token_means_no_message_and_no_error(self, client, monkeypatch):
        monkeypatch.setenv("EPD_OWNER_SLACK_DM", "U-owner")
        monkeypatch.setattr("temper_ai.integrations.slack.client.bot_token", lambda: "")

        assert O.tell_owner("no token here") is False
        assert client.posted == []

    def test_slack_being_down_is_not_the_callers_problem(self, monkeypatch):
        """The work the message describes has already happened."""
        monkeypatch.setenv("EPD_OWNER_SLACK_DM", "U-owner")
        monkeypatch.setattr(O, "_client", lambda: _Client(fails=True))
        monkeypatch.setattr("temper_ai.integrations.slack.client.bot_token", lambda: "xoxb-test")

        assert O.tell_owner("this will not go") is False
