"""Blanking secrets out of text, and the copy of it roamee-reader carries.

``scripts/roamee_reader.py`` runs on the host with plain ``python3`` and
nothing of temper installed, so it cannot import
:mod:`temper_ai.shared.secrets` and keeps its own copy of the rules. This
file holds the two to the same answers: a rule added to one and forgotten in
the other fails here.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

from temper_ai.shared.secrets import BLANK, blank_secrets

READER = Path(__file__).resolve().parents[2] / "scripts" / "roamee_reader.py"


def _reader() -> Any:
    spec = importlib.util.spec_from_file_location("roamee_reader_for_secrets", READER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SECRETS = [
    ("postgresql://roamee:hunter2@db:5432/trips", "hunter2"),
    ("DATABASE_URL=postgresql://u:p4ssw0rd@db:5432/x", "p4ssw0rd"),
    ("OPENAI_API_KEY=sk-live-0123456789abcdefghij", "sk-live-0123456789abcdefghij"),
    ("GITHUB_TOKEN=ghp_0123456789abcdefghij0123456789abcd", "ghp_0123456789abcdefghij0123456789abcd"),
    ("SLACK_BOT_TOKEN: xoxb-1234567890-abcdefghij", "xoxb-1234567890-abcdefghij"),
    ("LINEAR_API_KEY=lin_api_0123456789abcdef", "lin_api_0123456789abcdef"),
    ("authorization: Bearer abcdefghijklmnopqrst", "abcdefghijklmnopqrst"),
    ("Authorization: Basic YWxhZGRpbjpvcGVuc2VzYW1l", "YWxhZGRpbjpvcGVuc2VzYW1l"),
    ("password = 'swordfish'", "swordfish"),
    ("db_password=swordfish", "swordfish"),
    ("api_key: \"abcd-1234\"", "abcd-1234"),
    ("session: 9f8e7d6c5b4a", "9f8e7d6c5b4a"),
    ('{"secret": "topsecretvalue"}', "topsecretvalue"),
]

PLAIN = [
    "12 trips, 3 of them planned",
    "roamee-staging-backend-1 is running, healthy, up 28 hours",
    "the last commit on staging is abc1234, 3 September",
    "select count(*) from trips",
]


@pytest.mark.parametrize("text,gone", SECRETS)
def test_a_secret_never_comes_through(text: str, gone: str) -> None:
    out = blank_secrets(text)
    assert gone not in out
    assert BLANK in out


@pytest.mark.parametrize("text", PLAIN)
def test_ordinary_text_is_left_alone(text: str) -> None:
    assert blank_secrets(text) == text


@pytest.mark.parametrize("text,gone", SECRETS)
def test_the_readers_copy_says_the_same(text: str, gone: str) -> None:
    out = _reader().scrub(text)
    assert gone not in out
    assert BLANK in out


@pytest.mark.parametrize("text", PLAIN)
def test_the_readers_copy_leaves_ordinary_text_alone(text: str) -> None:
    assert _reader().scrub(text) == text


def test_both_answer_the_same_for_every_case() -> None:
    scrub = _reader().scrub
    for text, _ in SECRETS:
        assert scrub(text) == blank_secrets(text), f"the two copies differ on {text!r}"


def test_nothing_in_means_nothing_out() -> None:
    assert blank_secrets(None) == ""
    assert blank_secrets("") == ""
    assert _reader().scrub(None) == ""
