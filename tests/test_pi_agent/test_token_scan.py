"""The token scan (M4 SW-52), model-free: a hit is reported by rule, count and path only -- the
matched text is never in a report, a record, a refusal or a log line.

The fake tokens are built at run time, so the file itself holds none.
"""

from __future__ import annotations

import logging

import pytest

from temper_ai.pi_agent import token_scan
from temper_ai.pi_agent.token_scan import (
    RUN_TOKEN,
    WITHHELD,
    Hits,
    LogGuard,
    TokenRefusal,
    refuse_tokens,
    scan,
    scan_all,
    scan_obj,
    withhold,
)

#: A run's own token as the hand-off gives it (any text, not only a known shape), and fakes of
#: the three shapes.
RUN_SECRET = "fake-run-" + "Q7" * 12
ACCESS = "sk-ant-" + "oat01-" + "A" * 24
REFRESH = "sk-ant-" + "ort01-" + "B" * 24
API_KEY = "sk-ant-" + "api03-" + "C" * 24


@pytest.fixture(autouse=True)
def _forget():
    token_scan.forget_all()
    token_scan.remember(RUN_SECRET)
    yield
    token_scan.forget_all()


def no_secret_in(text: str) -> None:
    for secret in (RUN_SECRET, ACCESS, REFRESH, API_KEY):
        assert secret not in text


def test_each_rule_is_found_and_reported_by_name_count_and_path_only():
    text = f"a {RUN_SECRET} b {ACCESS} c {REFRESH} d {API_KEY} e {ACCESS}"
    hits = scan(text, "notes.md")
    assert hits.rules == {RUN_TOKEN: 1, "anthropic_oauth_access_token": 2,
                          "anthropic_oauth_refresh_token": 1, "anthropic_api_key": 1}
    assert hits.paths == ["notes.md"]
    record = hits.record()
    assert record["refused"] is True and record["paths"] == ["notes.md"]
    no_secret_in(repr(record) + hits.words())
    assert hits.words().startswith("5 login-token match(es) (")


def test_bytes_and_nested_values_are_scanned_too():
    assert scan(f"x{ACCESS}y".encode(), "blob").rules == {"anthropic_oauth_access_token": 1}
    found = scan_obj({"summary": "fine", ACCESS: ["deep", {"k": RUN_SECRET}]}, "record")
    assert found.rules == {"anthropic_oauth_access_token": 1, RUN_TOKEN: 1}
    many = scan_all([("a.txt", "clean"), ("b.txt", REFRESH), (None, b"")])
    assert many.rules == {"anthropic_oauth_refresh_token": 1} and many.paths == ["b.txt"]


def test_clean_text_has_no_hits():
    for text in ("", None, "sk-ant-oat01-short", "the word token", b"\x00\xff"):
        assert not scan(text)


def test_short_strings_are_never_remembered_as_a_run_s_token():
    token_scan.remember("abc", None, "")
    assert not scan("abc def")


def test_a_file_named_after_a_token_is_named_without_it():
    hits = Hits()
    hits.add("anthropic_oauth_access_token", 1, f"docs/{ACCESS}.txt")
    assert hits.paths == [f"docs/{WITHHELD}.txt"]


def test_a_member_s_call_holding_a_token_is_refused_naming_the_rules_only():
    with pytest.raises(TokenRefusal) as refused:
        refuse_tokens({"to": "lead", "body": f"here: {ACCESS}"})
    no_secret_in(refused.value.detail)
    assert "anthropic_oauth_access_token" in refused.value.detail
    refuse_tokens({"to": "lead", "body": "nothing secret"})  # a clean one passes


def test_withhold_replaces_every_match():
    out = withhold(f"{RUN_SECRET} / {ACCESS} / {API_KEY}")
    assert out == f"{WITHHELD} / {WITHHELD} / {WITHHELD}"


def test_the_log_guard_withholds_tokens_in_messages_arguments_and_tracebacks():
    records: list[str] = []

    class Keep(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(self.format(record))

    handler = Keep()
    handler.setFormatter(logging.Formatter("%(message)s"))
    log = logging.getLogger("tests.token_scan.guard")
    log.propagate = False
    log.addHandler(handler)
    try:
        token_scan.guard_logs(log)
        token_scan.guard_logs(log)  # once only
        assert sum(isinstance(f, LogGuard) for f in handler.filters) == 1
        log.warning("handed %s to the box", RUN_SECRET)
        log.warning(f"refresh {REFRESH}")
        try:
            raise RuntimeError(f"bad token {ACCESS}")
        except RuntimeError:
            log.exception("it failed")
    finally:
        log.removeHandler(handler)
    assert len(records) == 3
    for line in records:
        no_secret_in(line)
    assert WITHHELD in records[0] and WITHHELD in records[1]
    assert "RuntimeError" in records[2] and WITHHELD in records[2]
