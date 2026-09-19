"""Long-run properties of the ``compress`` policy.

The unit tests walk four or five turns. These walk hundreds, the way a real
run does — the service's order of events (tools execute, *then* the assistant
message and its results are appended, then ``prepare`` builds the next view)
— with a scripted model that does what the nudges say, folds tiers as blocks
pile up, and decompresses and searches along the way. A second model throws
arbitrary ranges at the tools. After every ``prepare`` the wire view is checked
for the invariants a provider (and the model) depend on.
"""

import json
import random
import re

import pytest

from temper_ai.llm.context import (
    ContextCompressor,
    ContextError,
    estimate_messages_tokens,
    ref,
)

_TAG = re.compile(r'<acp tokens="[^"]*">(m\d+|b\d+)</acp>\s*$')
_RANGE = re.compile(r"(m\d{5})–(m\d{5}) \(~([\d,.]+K?)\)")


# -- invariants ---------------------------------------------------------------


def _check(c: ContextCompressor, messages: list[dict], view: list[dict]) -> None:
    """What must hold for every wire view, however it was reached."""
    # 1. Provider-valid: every tool result directly follows the assistant
    #    message that called it, and every call in the view has its results.
    pending: set[str] = set()
    for m in view:
        if m["role"] == "tool":
            assert m["tool_call_id"] in pending, (
                f"orphan tool result {m['tool_call_id']}: {m['content'][:80]!r}"
            )
            pending.discard(m["tool_call_id"])
        else:
            assert not pending, (
                f"calls {pending} have no results before a {m['role']} message"
            )
            if m["role"] == "assistant":
                pending = {tc["id"] for tc in m.get("tool_calls") or []}
    assert not pending, f"view ends with unanswered calls {pending}"

    # 2. Chronological, and 3. complete: every transcript message is shown,
    #    hidden by an active block, or a compress pair whose blocks are all
    #    folded — never silently lost.
    hidden = c._hidden_indices()
    folded = c._folded_calls()
    shown: list[int] = []
    for m in view:
        content = m.get("content") if isinstance(m.get("content"), str) else ""
        if m["role"] == "system":
            continue
        if tag := _TAG.search(content or ""):
            t = tag.group(1)
            if t.startswith("b"):
                assert c.blocks[t].active, f"folded block {t} rendered"
                shown.append(c.blocks[t].start)
            else:
                shown.append(int(t[1:]) - 1)
        elif m["role"] == "user" and (content or "").startswith("[context] "):
            pass  # the nudge, not a transcript message
        elif m["role"] == "assistant":
            pass  # untagged by design
        else:
            raise AssertionError(
                f"untagged {m['role']} message in view: {content[:80]!r}"
            )
    assert shown == sorted(shown), "view is out of transcript order"
    assert len(shown) == len(set(shown)), "a transcript message appears twice"
    shown_set = set(shown)
    for i, m in enumerate(messages):
        if m["role"] not in ("user", "tool"):
            continue
        if i in shown_set:
            assert i not in hidden, f"{ref(i)} is shown but hidden by a block"
        elif i in hidden:
            continue
        elif m["role"] == "tool" and m.get("tool_call_id") in folded:
            continue
        else:
            raise AssertionError(
                f"{ref(i)} ({m['role']}) is neither shown, hidden nor folded"
            )

    # 4. Blocks: active ones disjoint; every folded one lies whole inside
    #    exactly one active ancestor.
    active = sorted((b for b in c.blocks.values() if b.active), key=lambda b: b.start)
    for a, b in zip(active, active[1:], strict=False):
        assert a.end < b.start, f"{a.id} and {b.id} overlap"
    for b in c.blocks.values():
        if not b.active:
            owners = [a for a in active if a.start <= b.start and a.end >= b.end]
            assert len(owners) == 1, f"folded {b.id} has {len(owners)} active owners"
        assert b.tokens_after < b.tokens_before, f"{b.id} gained nothing"

    # 5. Every block, folded or not, can still be opened and searched.
    for b in c.blocks.values():
        assert b.label() in c.decompress(messages, b.id)

    # 6. The system prompt and the task are always there.
    assert view[0]["role"] == "system"
    assert any(m["role"] == "user" and "TASK" in (m.get("content") or "") for m in view)


def _within_limit(c: ContextCompressor, view: list[dict]) -> bool:
    body = [
        m
        for m in view
        if not (
            m["role"] == "user" and str(m.get("content", "")).startswith("[context] ")
        )
    ]
    return estimate_messages_tokens(body) <= c.max_context_tokens


# -- a simulated agent loop ---------------------------------------------------


class _Loop:
    """The service's loop with the provider replaced by a scripted model.

    ``step`` takes the model's tool calls for one turn, executes them the way
    ``LLMService`` does (context tools against the live transcript, a
    ``ContextError`` becomes an ``Error:`` result), appends the assistant
    message and its results, then prepares the next view and checks it.
    """

    def __init__(self, limit: int, seed: int):
        self.c = ContextCompressor(limit)
        self.rng = random.Random(seed)
        self.messages = [
            {"role": "system", "content": "You are a coder."},
            {"role": "user", "content": "TASK: audit every file under src/."},
        ]
        self.calls = 0
        self.reads = 0
        self.compresses = 0
        self.rejected: list[str] = []  # Error: results of *scripted* context calls
        self.harness_hid = 0  # turns on which the harness had to hide something
        self.over_limit = 0
        self.view = self.c.prepare(self.messages)
        _check(self.c, self.messages, self.view)

    def cid(self) -> str:
        self.calls += 1
        return f"c{self.calls}"

    def run(self, name: str, args: dict) -> str:
        if self.c.handles(name):
            try:
                return self.c.execute(name, args, self.messages, tool_call_id=self._cid)
            except ContextError as e:
                return f"Error: {e}"
        if name == "Read":
            self.reads += 1
            size = args.get("size", 3000)
            return (
                f"file {self.reads} ({args['path']}): class C{self.reads}\n"
                + "x" * size
            )
        raise AssertionError(name)

    def step(self, tool_calls: list[tuple[str, dict]]) -> list[str]:
        results = []
        calls = []
        for name, args in tool_calls:
            self._cid = self.cid()
            calls.append(
                {
                    "id": self._cid,
                    "type": "function",
                    "function": {"name": name, "arguments": json.dumps(args)},
                }
            )
            results.append((self._cid, self.run(name, args)))
        self.messages.append({"role": "assistant", "content": "", "tool_calls": calls})
        for cid, r in results:
            self.messages.append({"role": "tool", "tool_call_id": cid, "content": r})
        self.view = self.c.prepare(self.messages)
        if "The harness hid" in self.nudge():
            self.harness_hid += 1
        if not _within_limit(self.c, self.view):
            self.over_limit += 1
        _check(self.c, self.messages, self.view)
        return [r for _, r in results]

    # what the scripted model can see
    def nudge(self) -> str:
        last = self.view[-1]
        content = last.get("content") or ""
        return (
            content
            if last["role"] == "user" and content.startswith("[context] ")
            else ""
        )

    def visible_refs(self) -> list[str]:
        tags = (_TAG.search(m.get("content") or "") for m in self.view)
        return [t.group(1) for t in tags if t]

    def active_blocks(self) -> list[str]:
        return [b.id for b in self.c.blocks.values() if b.active]


def _obedient_turn(loop: _Loop, turn: int) -> list[tuple[str, dict]]:
    """A model that compresses what the nudge names, folds blocks when they
    pile up, and otherwise reads files — with the odd decompress and search."""
    nudge = loop.nudge()
    if "Largest compressible ranges" in nudge:
        s, e, _ = _RANGE.findall(nudge)[0]
        loop.compresses += 1
        return [
            (
                "compress",
                {
                    "ranges": [
                        {
                            "start": s,
                            "end": e,
                            "summary": f"turn {turn}: {s}–{e} held nothing relevant",
                            "topic": f"t{turn}",
                        }
                    ]
                },
            )
        ]
    active = [b for b in loop.c.blocks.values() if b.active]
    for tier in (1, 2, 3):
        same = [b for b in active if b.tier == tier]
        if len(same) >= 4:
            loop.compresses += 1
            return [
                (
                    "compress",
                    {
                        "ranges": [
                            {
                                "start": same[0].id,
                                "end": same[-1].id,
                                "summary": f"turn {turn}: tiers folded, nothing relevant",
                                "topic": f"fold t{tier}",
                            }
                        ]
                    },
                )
            ]
    roll = loop.rng.random()
    if roll < 0.06 and loop.c.blocks:
        b = loop.rng.choice(list(loop.c.blocks))
        return [("decompress", {"block_id": b, "max_chars": 6000})]
    if roll < 0.10:
        return [("search_context", {"query": "class C7"})]
    if roll < 0.12:
        return [("context_status", {})]
    if roll < 0.2:  # two reads in one turn
        return [
            ("Read", {"path": f"src/f{turn}a.py", "size": loop.rng.randint(300, 4000)}),
            ("Read", {"path": f"src/f{turn}b.py", "size": loop.rng.randint(300, 4000)}),
        ]
    return [("Read", {"path": f"src/f{turn}.py", "size": loop.rng.randint(300, 9000)})]


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_hundreds_of_turns_following_the_nudges(seed):
    """Not four compresses: as many as a long run needs, with the block tree
    growing three tiers deep, and no nudged range ever rejected."""
    loop = _Loop(12_000, seed)
    for turn in range(400):
        results = loop.step(_obedient_turn(loop, turn))
        for r in results:
            if r.startswith("Error:"):
                loop.rejected.append(f"turn {turn}: {r}")

    assert loop.rejected == []
    assert loop.compresses >= 40, loop.compresses
    assert max(b.tier for b in loop.c.blocks.values()) >= 3
    assert len(loop.messages) > 800
    assert loop.over_limit == 0
    # the model kept up, so the harness rarely had to step in
    assert loop.harness_hid <= 2, loop.harness_hid
    # and the whole transcript is still accounted for
    _check(loop.c, loop.messages, loop.view)


def test_the_twelfth_compress_and_the_fiftieth():
    loop = _Loop(12_000, 7)
    receipts = []
    for turn in range(400):
        calls = _obedient_turn(loop, turn)
        results = loop.step(calls)
        if calls[0][0] == "compress":
            receipts.append(results[0])
        if len(receipts) == 50:
            break
    assert len(receipts) == 50
    for n in (11, 49):
        assert receipts[n].startswith("Compressed 1 range(s)"), (
            f"#{n + 1}: {receipts[n]}"
        )
    assert any("folds" in r for r in receipts)


# -- fuzz ---------------------------------------------------------------------


def _random_boundary(loop: _Loop) -> str:
    r = loop.rng.random()
    refs = loop.visible_refs()
    blocks = loop.active_blocks()
    if r < 0.45 and refs:
        return loop.rng.choice(refs)
    if r < 0.7 and blocks:
        return loop.rng.choice(blocks)
    if r < 0.85:
        return ref(
            loop.rng.randint(0, len(loop.messages) + 3)
        )  # may be hidden, may not exist
    if r < 0.95:
        return loop.rng.choice(list(loop.c.blocks) or ["b1"])  # may be folded
    return loop.rng.choice(["b99", "m0", "", "x"])


def _fuzz_turn(loop: _Loop, turn: int) -> list[tuple[str, dict]]:
    roll = loop.rng.random()
    if roll < 0.5:
        return [
            ("Read", {"path": f"src/f{turn}.py", "size": loop.rng.randint(200, 8000)})
        ]
    if roll < 0.85:
        ranges = []
        for _ in range(loop.rng.choice([1, 1, 1, 2, 3])):
            ranges.append(
                {
                    "start": _random_boundary(loop),
                    "end": _random_boundary(loop),
                    "summary": loop.rng.choice(
                        ["", "short", "s " * loop.rng.randint(1, 400)]
                    ),
                }
            )
        loop.compresses += 1
        return [("compress", {"ranges": ranges})]
    if roll < 0.92:
        return [("decompress", {"block_id": _random_boundary(loop)})]
    if roll < 0.97:
        return [
            (
                "search_context",
                {"query": loop.rng.choice(["class", "file 3", "", "zzz"])},
            )
        ]
    return [("context_status", {})]


@pytest.mark.parametrize("seed", [11, 12, 13, 14])
def test_arbitrary_ranges_never_corrupt_the_view(seed):
    """Whatever the model asks for, a bad request is an Error: result and the
    view stays provider-valid, ordered and complete. Only ContextError may
    surface — anything else is a bug in the policy, not in the request."""
    loop = _Loop(10_000, seed)
    accepted = 0
    for turn in range(400):
        for r in loop.step(_fuzz_turn(loop, turn)):
            if r.startswith("Compressed"):
                accepted += 1
    # the fuzzer did land real compressions (seeds 11-14 give 10-19 of ~140
    # attempts: empty summaries, inverted ranges and refs the harness has
    # already hidden are the rejections it exists to throw)
    assert accepted >= 8, accepted
    assert loop.over_limit == 0
    assert loop.harness_hid > 10  # the harness carried a model that would not
    _check(loop.c, loop.messages, loop.view)


def test_a_model_that_never_compresses_stays_within_the_limit():
    """The case eviction lost: with stubs, receipts and assistant messages all
    standing in the view per turn, 400 turns of reads went ~12K over a 10K
    window with 'nothing left to evict'. Harness blocks fold it all away."""
    loop = _Loop(10_000, 5)
    for turn in range(400):
        loop.step(
            [("Read", {"path": f"src/f{turn}.py", "size": loop.rng.randint(200, 8000)})]
        )
        if turn % 7 == 0:
            loop.step([("context_status", {})])  # once unbounded and un-evictable
    assert loop.over_limit == 0
    harness = [b for b in loop.c.blocks.values() if b.by_harness]
    assert len(harness) == 1 and harness[0].active  # one block, extended as it went
    assert harness[0].start == 2 and harness[0].end > 700
    assert len(loop.view) < 40  # not a stub per evicted result
    _check(loop.c, loop.messages, loop.view)
