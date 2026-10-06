"""One account per Pi run, and how an account's refusal or limit ends a turn (M4 ADR-M4-09,
-14, -16; SW-53, SW-54), model-free: the room figures, the pick, the record, and the mapping of
a turn that did not complete. The team-level effects (the red turn, the stopped team, the
recovery wait) are in tests/test_runner/pi_team/test_account_endings.py.

Every error text here is a small fake written for the test.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import yaml

from temper_ai.llm.pi_stream import PiOutcome
from temper_ai.pi_agent import accounts, team_config
from temper_ai.pi_agent.accounts import (
    LIMITED,
    REFUSED,
    AccountError,
    Room,
    RoomReading,
    call_trouble,
    choose,
    pick,
    read_room,
    turn_ending,
    whole_result_refusal,
)
from temper_ai.pi_agent.member import DEFAULT_PROVIDER
from temper_ai.pi_agent.team_config import TeamConfig, load_team_config, slot_problem

SLOTS = ("acct-b", "acct-c")
#: A fake 403 as the API words it for an organisation that doesn't allow OAuth.
REFUSAL_403 = ('403 {"type":"error","error":{"type":"permission_error","message":'
               '"OAuth authentication is currently not allowed for this organization."}}')
#: The CLI's refusal sentence (the one roles quote in their notes).
DISABLED = "Your organization has disabled Claude subscription access for Claude Code"
LIMIT = "429 rate_limit_error: You've hit your session limit \u00b7 resets 10:50pm (UTC)"


def outcome(*, output: str = "", stop: str | None = "stop", error: str | None = None,
            completion: int = 3, tool_calls: int = 0, status: str = "completed") -> PiOutcome:
    """A turn's outcome as pi_stream reports it: how its last model reply ended."""
    return PiOutcome(status=status, output=output, structured_output=None, errors=[],
                     warnings=[], tokens={"prompt_tokens": 12, "completion_tokens": completion,
                                          "total_tokens": 12 + completion, "cost_usd": 0.0},
                     llm_calls=1 if stop else 0, tool_calls=tool_calls, counts={},
                     last_stop=stop, last_error=error)


def report(state: str, error: str | None, out: PiOutcome | None) -> SimpleNamespace:
    return SimpleNamespace(state=state, error=error, outcome=out)


def config(**over) -> TeamConfig:
    return TeamConfig(**{"account_slots": SLOTS, "account_room_file": "/rooms/now.json",
                         **over})


def rooms(**figures: tuple[float | None, float | None]) -> dict[str, Room]:
    return {slot.replace("_", "-"): Room(slot.replace("_", "-"), five, seven)
            for slot, (five, seven) in figures.items()}


# --- the account-room file (ADR-M4-18, the account-room interface version 1) -----------------

NOW = datetime(2026, 10, 6, 20, 0, tzinfo=UTC)


def ago(minutes: float) -> str:
    """A time ``minutes`` before NOW as the writer words it (whole seconds, UTC, Z)."""
    return (NOW - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")


def ok_row(slot: str, five=10, seven=20, *, observed: str | None = None,
           five_resets: str | None = None, seven_resets: str | None = None) -> dict:
    return {"slot": slot, "status": "ok", "observed_at": observed or ago(1),
            "five_hour": {"used_percent": five, "resets_at": five_resets},
            "seven_day": {"used_percent": seven, "resets_at": seven_resets}}


def room_file(tmp_path, rows: list, **top) -> str:
    path = tmp_path / "account-room.json"
    path.write_text(json.dumps({"schema_version": 1, "slots": rows, **top}), encoding="utf-8")
    return str(path)


def read(path: str) -> RoomReading:
    return read_room(path, now=NOW)


def test_a_version_1_file_is_read_with_its_sha256_and_every_slot_judged(tmp_path):
    path = room_file(tmp_path, [
        ok_row("acct-b", 12, 40.5, five_resets=ago(-30)),
        {"slot": "acct-c", "status": "unavailable", "reason": "busy"}])
    got = read(path)
    assert got.schema_version == 1
    with open(path, "rb") as fh:
        assert got.sha256 == hashlib.sha256(fh.read()).hexdigest()
    assert got.rooms["acct-b"] == Room("acct-b", 12.0, 40.5, ago(-30), None, ago(1))
    assert got.rooms["acct-b"].passes()
    assert got.rooms["acct-c"].unusable == "unavailable (busy when it was read)"
    assert not got.rooms["acct-c"].passes()


@pytest.mark.parametrize("text, says", [
    ('{"schema_version": 1, "slots": [', "is not JSON"),
    (b"\xff\xfe", "is not JSON"),
    ('{"schema_version": 1, "schema_version": 1, "slots": []}', "has a JSON key twice"),
    ('{"schema_version": 1, "slots": [{"slot": "acct-b", "slot": "acct-c"}]}',
     "has a JSON key twice"),
    ("[]", "is not a JSON object"),
    ('{"slots": []}', "has no schema_version 1"),
    ('{"schema_version": 2, "slots": []}', "has no schema_version 1"),
    ('{"schema_version": "1", "slots": []}', "has no schema_version 1"),
    ('{"schema_version": true, "slots": []}', "has no schema_version 1"),
    ('{"schema_version": 1, "slots": [], "note": 1}',
     "has a top-level field version 1 doesn't list"),
    ('{"schema_version": 1, "slots": [{"slot": "acct-b", "status": "ok", "plan": 1}]}',
     "has a field version 1 doesn't list in slot row 1"),
    ('{"schema_version": 1, "slots": [{"slot": "acct-b", "status": "ok", '
     '"five_hour": {"used_percent": 1, "limit": 2}}]}',
     "has a field version 1 doesn't list in slot row 1"),
    ('{"schema_version": 1, "slots": {}}', "has slots that aren't a list"),
    ('{"schema_version": 1, "slots": ["acct-b"]}', "has slot row 1 that isn't an object"),
    ('{"schema_version": 1, "slots": [{"status": "ok"}]}',
     "has slot row 1 without a slot label"),
    ('{"schema_version": 1, "slots": [{"slot": "acct-b"}, {"slot": "acct-b"}]}',
     "lists one slot twice (slot rows 1 and 2)"),
], ids=["not-json", "not-utf8", "duplicate-key", "duplicate-row-key", "not-object",
        "no-version", "version-2", "version-text", "version-true", "unlisted-field",
        "unlisted-row-field", "unlisted-window-field", "slots-not-list", "row-not-object",
        "row-no-label", "label-twice"])
def test_a_file_version_1_doesn_t_allow_is_refused_whole_naming_the_file(tmp_path, text, says):
    path = tmp_path / "account-room.json"
    path.write_bytes(text if isinstance(text, bytes) else text.encode())
    with pytest.raises(AccountError) as refused:
        read(str(path))
    assert str(refused.value) == f"the account-room file {path} {says}"


def test_a_file_that_isn_t_a_plain_file_of_at_most_64_kib_is_refused_whole(tmp_path):
    good = room_file(tmp_path, [ok_row("acct-b")])
    cases = {"is missing": tmp_path / "gone.json", "is a link": tmp_path / "link.json",
             "is not a regular file": tmp_path / "folder",
             "is over 64 KiB": tmp_path / "big.json"}
    cases["is a link"].symlink_to(good)
    cases["is not a regular file"].mkdir()
    cases["is over 64 KiB"].write_text(" " * (64 * 1024) + "{}", encoding="utf-8")
    fifo = tmp_path / "fifo"
    os.mkfifo(fifo)
    for says, path in [*cases.items(), ("is not a regular file", fifo)]:
        with pytest.raises(AccountError) as refused:
            read(str(path))
        assert str(refused.value) == f"the account-room file {path} {says}"
    assert read(good).rooms["acct-b"].passes()


@pytest.mark.parametrize("change, says", [
    ({"five_hour": {"resets_at": None}}, "its 5-hour use is missing or not a number from 0 to 100"),
    ({"seven_day": {"used_percent": "lots", "resets_at": None}},
     "its 7-day use is missing or not a number from 0 to 100"),
    ({"five_hour": {"used_percent": True, "resets_at": None}}, "its 5-hour use is missing"),
    ({"five_hour": {"used_percent": float("nan"), "resets_at": None}},
     "its 5-hour use is missing"),
    ({"seven_day": {"used_percent": 100.5, "resets_at": None}}, "its 7-day use is missing"),
    ({"five_hour": {"used_percent": -1, "resets_at": None}}, "its 5-hour use is missing"),
    ({"observed_at": None}, "its reading time is missing"),
    ({"observed_at": "2026-10-06T19:59:00"}, "its reading time is without a timezone"),
    ({"observed_at": "yesterday"}, "its reading time is not a time"),
    ({"observed_at": ago(-1)}, "its reading time is in the future"),
    ({"observed_at": ago(15)}, "its reading is 15 min old (it must be under 15 min)"),
    ({"five_hour": {"used_percent": 10, "resets_at": ago(0.5)}},
     "its 5-hour window reset since the reading"),
    ({"seven_day": {"used_percent": 20, "resets_at": "soon"}},
     "its 7-day reset time is not a time"),
    ({"five_hour": {"used_percent": 85, "resets_at": None}}, "5-hour use at or over 85%"),
    ({"seven_day": {"used_percent": 90, "resets_at": None}}, "7-day use at or over 90%"),
    ({"status": "unavailable", "reason": "signed_out"}, "unavailable (signed out)"),
    ({"status": "unavailable", "reason": "gremlins"}, "unavailable"),
    ({"status": "maybe"}, "its reading isn't ok"),
], ids=["5h-missing", "7d-text", "5h-bool", "5h-nan", "7d-over-100", "5h-negative",
        "no-observed", "observed-no-tz", "observed-not-time", "observed-future", "15-min-old",
        "reset-passed", "reset-not-time", "5h-at-85", "7d-at-90", "unavailable",
        "unknown-reason", "status-unknown"])
def test_a_row_that_can_t_start_a_run_makes_only_its_slot_unusable(tmp_path, change, says):
    row = {**ok_row("acct-b"), **change}
    got = read(room_file(tmp_path, [row, ok_row("acct-c")]))
    assert says in (got.rooms["acct-b"].unusable or "")
    assert not got.rooms["acct-b"].passes()
    assert got.rooms["acct-c"].passes()
    assert pick(SLOTS, got.rooms).slot == "acct-c"


def test_an_unknown_reason_is_given_as_no_reason():
    assert accounts._judge({"slot": "acct-b", "status": "unavailable", "reason": "gremlins"},
                           NOW).unusable == "unavailable"


# --- the pick: the least 7-day use under R-D6, ties in the settings' order --------------------


def test_the_slot_with_the_least_weekly_use_is_picked_ties_in_the_settings_order():
    assert pick(SLOTS, rooms(acct_b=(10, 60), acct_c=(10, 30))).slot == "acct-c"
    # a tie on the week goes by the settings' order, whatever the 5-hour use
    assert pick(SLOTS, rooms(acct_b=(40, 30), acct_c=(10, 30))).slot == "acct-b"
    assert pick(SLOTS[::-1], rooms(acct_b=(10, 30), acct_c=(40, 30))).slot == "acct-c"


def test_account_1_is_never_picked_even_with_the_most_room():
    found = {**rooms(acct_b=(50, 80)), "anthropic": Room("anthropic", 1, 1)}
    assert pick(("anthropic", "acct-b"), found).slot == "acct-b"
    with pytest.raises(AccountError, match="no account slot is allowed"):
        pick(("anthropic",), found)


@pytest.mark.parametrize("c_figures", [(85, 10), (10, 90), (None, 10), (10, None)],
                         ids=["5h-at-85", "7d-at-90", "5h-unknown", "7d-unknown"])
def test_a_slot_at_either_limit_or_without_figures_is_not_picked(c_figures):
    assert pick(SLOTS, rooms(acct_b=(84, 89), acct_c=c_figures)).slot == "acct-b"


def test_no_slot_with_room_refuses_naming_each_slot_s_reading_and_the_known_resets():
    found = {"acct-b": Room("acct-b", 90, 20, ago(-45), None, ago(1)),
             "acct-c": Room("acct-c", unusable="unavailable (signed out)")}
    with pytest.raises(AccountError) as refused:
        pick((*SLOTS, "acct-d"), found)
    words = str(refused.value)
    assert f"acct-b: 5 h 90% (resets {ago(-45)}), 7 d 20% -- 5-hour use at or over 85%" in words
    assert "acct-c: unavailable (signed out)" in words and "acct-d: no reading" in words
    assert words.endswith("Start a new run once an account has room")
    assert "wait" not in words and "enough" not in words


def test_a_slot_the_settings_don_t_list_is_never_picked():
    assert pick(("acct-b",), rooms(acct_b=(50, 80), acct_c=(1, 1))).slot == "acct-b"


# --- choose: picked once, recorded, never moved -----------------------------------------------


def test_choose_picks_by_room_and_records_the_label_the_reading_and_the_file_s_sha256():
    reading = RoomReading(rooms(acct_b=(10, 60), acct_c=(10, 30)), "ab" * 32, 1)
    got = choose({}, config=config(), read=lambda _p, now=None: reading, now=NOW)
    assert set(got) == {"slot", "picked_at", "by", "room", "room_file"}
    assert got["slot"] == "acct-c" and got["by"] == "room"
    assert got["picked_at"] == NOW.isoformat()
    assert got["room"] == {"five_hour": 10.0, "seven_day": 30.0, "five_hour_resets_at": None,
                           "seven_day_resets_at": None, "observed_at": None}
    assert got["room_file"] == {"sha256": "ab" * 32, "schema_version": 1}


def test_choose_reads_the_settings_file_once(tmp_path):
    path = room_file(tmp_path, [ok_row("acct-b", seven=70), ok_row("acct-c", seven=20),
                                ok_row("acct-z", seven=1)])
    seen = []

    def read_once(p, now=None):
        seen.append(p)
        return read_room(p, now=now)

    got = choose({}, config=config(account_room_file=path), read=read_once, now=NOW)
    assert seen == [path] and got["slot"] == "acct-c"
    with open(path, "rb") as fh:
        assert got["room_file"]["sha256"] == hashlib.sha256(fh.read()).hexdigest()
    assert got["room"]["observed_at"] == ago(1)


def test_a_run_admitted_before_with_no_account_recorded_is_refused_never_picked_again():
    def no_read(*_a, **_k):
        raise AssertionError("a run's account is picked once, at its first claim")

    with pytest.raises(AccountError, match="picked once, at its first claim, and never again"):
        choose({}, config=config(), read=no_read, admitted=True)


def test_a_run_keeps_its_recorded_account_whatever_the_room_now():
    kept = {"slot": "acct-c", "picked_at": "2026-10-06T10:00:00+00:00", "by": "room"}
    row = {"spawner_metadata": {"pi_lane": {"account": kept}}}

    def no_read(*_a, **_k):
        raise AssertionError("a recorded account is never picked again")

    assert choose(row, config=config(), read=no_read) == kept


def test_a_recorded_account_the_settings_no_longer_allow_stops_the_run_rather_than_moving():
    row = {"spawner_metadata": {"pi_lane": {"account": {"slot": "acct-c"}}}}
    with pytest.raises(AccountError, match="never moves to another account"):
        choose(row, config=config(account_slots=("acct-b",)),
               read=lambda *_a, **_k: rooms(acct_b=(1, 1)))


@pytest.mark.parametrize("over, says", [
    ({"account_slots": ()}, "no account slot is allowed"),
    ({"account_room_file": None}, "has no account-room file"),
], ids=["no-slots", "no-room-file"])
def test_without_slots_or_room_figures_a_run_doesn_t_start(over, says):
    with pytest.raises(AccountError, match=says):
        choose({}, config=config(**over), read=lambda *_a, **_k: rooms(acct_b=(1, 1)))


# --- account 1 is refused by name -------------------------------------------------------------


def test_account_1_is_refused_by_name_wherever_it_appears(tmp_path):
    assert DEFAULT_PROVIDER == "anthropic"
    assert "account 1" in (slot_problem(DEFAULT_PROVIDER) or "")
    for bad in ("Anthropic-2", "a b", "someone@example.com", "", 7):
        assert slot_problem(bad)
    assert slot_problem("acct-b") is None
    row = {"spawner_metadata": {"pi_lane": {"account": {"slot": DEFAULT_PROVIDER}}}}
    with pytest.raises(AccountError, match="account 1"):
        choose(row, config=config(account_slots=(*SLOTS, DEFAULT_PROVIDER)))

    tracked = tmp_path / team_config.TEAM_DIR / "team.yaml"
    tracked.parent.mkdir(parents=True)
    tracked.write_text(yaml.safe_dump({"account_slots": [DEFAULT_PROVIDER, "acct-b"],
                                       "account_room_file": "relative/room.json"}),
                       encoding="utf-8")
    cfg = load_team_config(tmp_path)
    assert cfg.account_slots == ("acct-b",) and cfg.account_room_file is None
    assert any("account_slots[0]" in p and "account 1" in p for p in cfg.problems)
    assert any("account_room_file must be a plain absolute path" in p for p in cfg.problems)


def test_the_tracked_defaults_list_the_two_other_slots_and_never_account_1():
    from pathlib import Path

    tracked = Path(__file__).resolve().parents[2] / "configs" / team_config.TEAM_DIR / "team.yaml"
    data = yaml.safe_load(tracked.read_text(encoding="utf-8"))
    assert data["account_slots"] == ["anthropic-2", "anthropic-3"]
    assert DEFAULT_PROVIDER not in data["account_slots"]


# --- how a model call ended: the error path only (ADR-M4-16) -----------------------------------


def test_a_403_on_the_last_reply_s_error_is_the_account_s_refusal():
    out = outcome(stop="error", error=REFUSAL_403, completion=0, status="failed")
    assert call_trouble(out, "the last model call failed: " + REFUSAL_403) == (REFUSED,
                                                                               REFUSAL_403)
    ending = turn_ending(report("failed", "the last model call failed", out), "acct-b")
    assert ending.kind == "refused" and ending.details is None
    assert ending.text.startswith("account acct-b refused the call (not allowed for this "
                                  "organization)")


def test_the_whole_result_of_a_call_with_no_model_output_counts_too():
    alone = outcome(output=DISABLED, completion=0)
    assert whole_result_refusal(alone) == DISABLED
    # turn.py makes that turn a failed one, its error the sentence; the mapping reads it there
    failed = outcome(output="", completion=0, status="failed")
    assert call_trouble(failed, DISABLED) == (REFUSED, DISABLED)
    assert turn_ending(report("failed", DISABLED, failed), "acct-c").kind == "refused"


@pytest.mark.parametrize("answer", [
    DISABLED,
    f"The roles' notes say: \"{DISABLED}\". That is the CLI's refusal; we key on the error.",
    REFUSAL_403,
], ids=["exactly-the-sentence", "quoted-in-an-answer", "a-403-quoted"])
def test_a_normal_answer_is_never_read_for_the_refusal(answer):
    """A member's answer, with model output, whatever it says: not a refusal, not a limit."""
    out = outcome(output=answer, completion=40)
    assert whole_result_refusal(out) is None
    assert call_trouble(out, None) is None
    # and a turn error after model output never makes the answer's words count
    assert call_trouble(out, f"the worker container was not removed; {DISABLED}") is None


def test_a_tool_call_alone_is_model_output_too():
    assert whole_result_refusal(outcome(output=DISABLED, completion=0, tool_calls=1)) is None


def test_a_limit_is_a_recovery_wait_naming_the_slot_the_limit_and_the_reset():
    out = outcome(stop="error", error=LIMIT, completion=0, status="failed")
    assert call_trouble(out, None) == (LIMITED, LIMIT)
    ending = turn_ending(report("failed", "the last model call failed", out), "acct-b")
    assert ending.kind == "held"
    assert ending.details == {"account_slot": "acct-b", "limit": " ".join(LIMIT.split()),
                              "resets": "10:50pm (UTC)"}
    assert "account acct-b hit a usage limit" in ending.text
    assert "Retrying keeps the same account, model and thinking" in ending.text


def test_a_limit_without_a_reset_takes_it_from_the_room_figures_at_the_start():
    out = outcome(stop="error", error="429 too many requests", completion=0, status="failed")
    room = {"five_hour_resets_at": "2026-10-06T22:50:00+00:00"}
    ending = turn_ending(report("failed", "429 too many requests", out), "acct-c", room)
    assert ending.kind == "held"
    assert ending.details["resets"] == "2026-10-06T22:50:00+00:00 (room figures at the run's start)"
    unknown = turn_ending(report("failed", "429 too many requests", out), "acct-c")
    assert unknown.details["resets"] is None
    assert "at a time the provider did not say" in unknown.text


def test_any_other_provider_error_is_a_failed_turn_with_its_error():
    out = outcome(output="", stop="error", error="500 overloaded_error", status="failed")
    ending = turn_ending(report("failed", "the last model call failed: 500 overloaded_error",
                                out), "acct-b")
    assert ending.kind == "failed"
    assert ending.text == "the last model call failed: 500 overloaded_error"


@pytest.mark.parametrize("error", [
    "The model refused to complete the request",
    "Provider stopped with: sensitive",
    "Output blocked by the cyber classifier",
], ids=["refusal-stop", "sensitive", "classifier"])
def test_a_classifier_refusal_is_a_red_turn_naming_it(error):
    out = outcome(stop="error", error=error, status="failed")
    ending = turn_ending(report("failed", "the last model call failed", out), "acct-b")
    assert ending.kind == "failed"
    assert ending.text.startswith("the model refused the request (safety classifier): ")
    assert error in ending.text


def test_a_request_the_api_turned_down_is_not_a_classifier_refusal():
    error = "400 invalid_request_error: the request was refused, the image is too large"
    out = outcome(stop="error", error=error, status="failed")
    assert turn_ending(report("failed", error, out), "acct-b").text == error


def test_a_cut_off_turn_is_held_for_the_owner():
    ending = turn_ending(report("uncertain", "the box went away", None), "acct-b")
    assert (ending.kind, ending.text) == ("held", "the box went away")
