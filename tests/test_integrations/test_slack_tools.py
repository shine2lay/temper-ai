"""The agent tools post only where the Slack config lets agents post."""

from __future__ import annotations

import json

import pytest

from temper_ai.integrations.slack import store
from temper_ai.tools import slack as slack_tools
from temper_ai.tools.slack import SlackPost, SlackReadThread, SlackReply

from .conftest import OWNER


@pytest.fixture
def fake(slack, slack_config, monkeypatch):
    monkeypatch.setattr(slack_tools, "_client", lambda: slack)
    return slack


def test_post_to_an_allowed_dm_and_channel(fake):
    result = SlackPost().execute(to=OWNER, text="hello")
    assert result.success and fake.posts[0]["channel"] == f"D{OWNER}"
    assert json.loads(result.result)["ts"] == fake.posts[0]["ts"]
    assert SlackPost().execute(to="C0RUNS001", text="hi").success


def test_anywhere_else_is_refused_with_what_is_allowed(fake):
    result = SlackPost().execute(to="C0GENERAL1", text="hello")
    assert not result.success and "C0RUNS001" in result.error and fake.posts == []


def test_a_run_thread_is_open_to_agents_even_in_other_channels(fake):
    store.save_thread("run-1", "C0ASKED01", "1790000000.000123", origin=True)
    assert SlackReply().execute(to="C0ASKED01", thread_ts="1790000000.000123", text="progress").success
    assert not SlackReply().execute(to="C0ASKED01", thread_ts="1790000000.999999", text="x").success
    fake.threads[("C0ASKED01", "1790000000.000123")] = [{"ts": "1790000000.000123", "user": OWNER, "text": "go"}]
    read = SlackReadThread().execute(to="C0ASKED01", thread_ts="1790000000.000123")
    assert read.success and json.loads(read.result)[0]["text"] == "go"


def test_no_agents_list_means_nowhere(fake, slack_config):
    slack_config("slack:\n  notify: {}\n")
    result = SlackPost().execute(to=OWNER, text="hello")
    assert not result.success and "no agents: list" in result.error


def test_missing_fields(fake):
    assert not SlackPost().execute(to="", text="x").success
    assert not SlackReply().execute(to=OWNER, text="x").success
