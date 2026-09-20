"""Context policy — what the model may remember once the transcript outgrows the window.

Chosen per agent with ``context_policy:`` in the agent YAML; an agent that
says nothing gets ``compress``.

``truncate``
    The mechanical policy in ``service._enforce_context_limit``: once the
    estimate passes ``max_context_tokens``, window the messages and cut every
    tool result to its first 5000/2000/1000 characters. Silent, and it keeps
    the wrong half of a build log. It was the default until every agent had
    to be trusted with a long run; an agent can still ask for it.

``compress`` (default)
    Model-driven, after billion-context-pi. Every user message and tool
    result carries a ref tag the model can see (``m00042``); the model is
    given ``compress`` / ``decompress`` / ``search_context`` /
    ``context_status`` and, once the transcript passes a threshold, a
    ``[context]`` message after the latest tool result naming the largest
    compressible ranges (a message of its own, not a line inside the result:
    models are trained to discount instructions found in tool output, and
    gpt-5.6-luna ignored the inline form at 97% usage, every turn). It writes
    the summaries itself. The transcript is never mutated: in the wire view a
    compressed range is replaced, where it stood, by one message headed
    ``[Compressed b3 — topic]`` holding the summary the model wrote — so what
    the model remembers is exactly what it chose to write down, in the order
    it happened. The ``compress`` call itself stays in the transcript (every
    summary is in the run's tool-call log for audit), but the wire view stubs
    its summaries to a few lines so each summary is sent once, and drops the
    call once every block it made has been folded into a higher tier. If the
    model does not act and the hard limit is reached, the harness hides the
    oldest whole turns behind a block of its own — the same mechanism, with a
    listing of what was there for a summary, extended as the run goes on —
    never cut from the head, never stubbed in place. (Per-message eviction
    stubs were tried first: a 400-turn run left 33 stubs, 29 stubbed compress
    calls and 5 un-evictable receipts in a 10K window, ~12K tokens with
    "nothing left to evict". Everything that stays in the view per turn
    grows without bound unless it can be folded away.)

Refs are transcript positions: ``m00001`` is ``messages[0]``. Under this
policy the transcript is append-only, so a ref never moves and a ref the
model wrote down ten turns ago still names the same message. A block has one
position — where its range began — so a range either leaves it alone, or
spans it and folds it whole; there is no third case.

The rendered summary is a ``user`` message, not ``system``: every provider
here folds ``system`` messages into the single system parameter (Anthropic
keeps the last one it sees), so a system-role summary mid-transcript would
replace the agent's prompt.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

CONTEXT_POLICIES = ("truncate", "compress")
DEFAULT_CONTEXT_POLICY = "compress"

CONTEXT_TOOL_NAMES = ("compress", "decompress", "search_context", "context_status")

_REF = re.compile(r"^m(\d+)$")
_BLOCK = re.compile(r"^b(\d+)$")

# Fraction of max_context_tokens at which the model starts being told to compress.
NUDGE_AT = 0.6
# The nudge only fires when this much of the window could actually be reclaimed.
NUDGE_MIN_COMPRESSIBLE = 0.1
# When the harness has to make room it aims here, so it buys more than one turn.
MAKE_ROOM_TO = 0.9
# call_id of the blocks the harness makes itself; no tool call carries it.
HARNESS_CALL = "harness"
# A compress call's summaries are cut to this many chars in the wire view: the
# full text is rendered where the range was, and the call is only the trace.
SUMMARY_STUB_CHARS = 200
DECOMPRESS_MAX_CHARS = 20_000
SEARCH_LIMIT = 8


def estimate_messages_tokens(messages: list[dict]) -> int:
    """Rough token estimate for a message list (~3 chars per token).

    Uses 3 chars/token (conservative) to avoid underestimating and
    hitting model context limits.
    """
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        if content:
            total += len(str(content)) // 3 + 4  # message overhead
        # Tool calls in assistant messages
        for tc in msg.get("tool_calls", []):
            fn = tc.get("function", {})
            total += len(fn.get("name", "")) // 3
            total += len(str(fn.get("arguments", ""))) // 3
    return total


def _message_tokens(msg: dict) -> int:
    return estimate_messages_tokens([msg])


def _fmt(n: int) -> str:
    return f"{n / 1000:.1f}K" if n >= 1000 else str(n)


def ref(index: int) -> str:
    return f"m{index + 1:05d}"


class ContextError(ValueError):
    """A context tool was called with something that cannot be done. The message
    is written for the model: it says what is wrong and what to do instead."""


@dataclass
class Block:
    id: str
    tier: int
    start: int  # first transcript index hidden by this block; where its summary is rendered
    end: int  # last transcript index hidden by this block (inclusive)
    call_id: str  # tool_call_id of the compress call that created it, or HARNESS_CALL
    summary: str
    topic: str
    tokens_before: int
    tokens_after: int
    children: list[str] = field(default_factory=list)
    # harness blocks folded in (at any depth): the model never summarized
    # their content, so what this summary says about them is memory, not record
    unread: list[str] = field(default_factory=list)
    active: bool = True

    @property
    def by_harness(self) -> bool:
        return self.call_id == HARNESS_CALL

    def label(self) -> str:
        return f"{self.id} (tier {self.tier}, {ref(self.start)}–{ref(self.end)})"


GUIDANCE = """

## Context management
You manage your own context. Every user message and tool result ends with a tag like <acp tokens="4.1K">m00042</acp>; that ref names the message (your own messages are unnumbered — name them by their neighbours). When the transcript grows, a [context] message after the latest tool result says how full it is and which ranges are largest. Use `compress` to replace a contiguous range of consumed messages with a summary you write; the range is then shown, where it was, as one message headed [Compressed bN] holding your summary — the only record of that range, so keep file paths with line numbers, function signatures, exact error strings, decisions and why, exact values and open questions verbatim, and drop logs, duplicate reads and dead ends. Never compress what the current step still needs. `decompress` brings a block's original content back when you need exact detail, `search_context` finds where something is, `context_status` shows usage and blocks. Block ids (b1, b2, …) can bound a range to fold blocks into a higher-tier summary. If the limit is reached before you compress, the harness hides the oldest turns behind a block that only lists what was there — nothing gets summarized — so compress first."""


class ContextCompressor:
    """State and tools of the ``compress`` policy for one run.

    Owns the blocks; never owns the transcript. Every method takes the live
    ``messages`` list so the service stays the single owner of it.
    """

    def __init__(self, max_context_tokens: int) -> None:
        self.max_context_tokens = max_context_tokens
        self.blocks: dict[str, Block] = {}
        self._room_note: str = (
            ""  # what the harness hid since the model last saw a view
        )
        self._seen = 0  # transcript length last time we looked; it may only grow

    # -- wire view ---------------------------------------------------------

    def prepare(self, messages: list[dict], *, wrapping_up: bool = False) -> list[dict]:
        """Everything that happens between the transcript and the provider call.

        ``wrapping_up``: the iteration budget is nearly spent and the model has
        been told to answer from what it knows. Then the usage nudge is left
        out — asking for a compress call in the same breath as a final answer
        costs a turn the budget does not have, and the answer needs no room.
        What the harness had to hide is still reported.
        """
        if len(messages) < self._seen:
            raise RuntimeError(
                "transcript shrank under the compress policy; refs are no longer stable"
            )
        self._seen = len(messages)
        view = self.view(messages)
        est = estimate_messages_tokens(view)
        if est > self.max_context_tokens and self._make_room(
            messages, target=int(self.max_context_tokens * MAKE_ROOM_TO)
        ):
            view = self.view(messages)
            est = estimate_messages_tokens(view)
        self._append_nudge(view, messages, est, ask=not wrapping_up)
        return view

    def view(self, messages: list[dict]) -> list[dict]:
        """The message list the provider sees: each hidden range replaced by its
        rendered summary where it stood, tags on user/tool messages, compress
        calls stubbed (or dropped once every block they made is folded)."""
        hidden = self._hidden_indices()
        at = {b.start: b for b in self.blocks.values() if b.active}
        folded_calls = self._folded_calls()
        out: list[dict] = []
        for i in range(len(messages)):
            if (block := at.get(i)) is not None:
                out.append(self.render(block))
            if i in hidden:
                continue
            m = self._view_message(messages, i, folded_calls)
            if m is not None:
                out.append(m)
        return out

    def _view_message(
        self, messages: list[dict], i: int, folded_calls: set[str]
    ) -> dict | None:
        """``messages[i]`` as the view shows it (tagged, compress calls stubbed),
        or None when the view drops it: a folded compress pair."""
        msg = messages[i]
        m = {k: v for k, v in msg.items() if not k.startswith("_")}
        role = m.get("role")
        if role == "tool":
            if m.get("tool_call_id") in folded_calls:
                return None
            m["content"] = (
                f'{m.get("content") or ""}\n<acp tokens="{_fmt(_message_tokens(msg))}">{ref(i)}</acp>'
            )
        elif role == "assistant" and m.get("tool_calls"):
            calls = self._view_calls(m["tool_calls"], folded_calls)
            if calls:
                m["tool_calls"] = calls
            else:
                del m["tool_calls"]
                if not m.get("content"):
                    return (
                        None  # only carried a compress call whose blocks are all folded
                    )
        elif role == "user" and isinstance(m.get("content"), str):
            m["content"] = (
                f'{m["content"]}\n<acp tokens="{_fmt(_message_tokens(msg))}">{ref(i)}</acp>'
            )
        elif role == "system" and i == 0 and isinstance(m.get("content"), str):
            m["content"] = m["content"] + GUIDANCE
        return m

    @staticmethod
    def render(block: Block) -> dict:
        """The message that stands in for a block's range in the wire view."""
        head = f"[Compressed {block.id}" + (
            f" — {block.topic}]" if block.topic else "]"
        )
        head += (
            f" {ref(block.start)}–{ref(block.end)}, tier {block.tier}, "
            f"~{_fmt(block.tokens_before)} → {_fmt(block.tokens_after)} tokens"
        )
        if block.unread:
            head += (
                f"\n(folds {', '.join(block.unread)}, which the harness had hidden unsummarized; "
                "what this summary says about that content is from memory, not the content)"
            )
        return {
            "role": "user",
            "content": f'{head}\n{block.summary}\n<acp tokens="{_fmt(block.tokens_after)}">{block.id}</acp>',
        }

    def _folded_calls(self) -> set[str]:
        """Compress calls whose every block has been folded into a higher tier:
        their summaries live on in the parent, so the call carries nothing."""
        by_call: dict[str, list[Block]] = {}
        for b in self.blocks.values():
            by_call.setdefault(b.call_id, []).append(b)
        return {cid for cid, bs in by_call.items() if not any(b.active for b in bs)}

    def _view_calls(self, tool_calls: list[dict], folded_calls: set[str]) -> list[dict]:
        out = []
        for tc in tool_calls:
            if ((tc.get("function") or {}).get("name")) != "compress":
                out.append(tc)
            elif tc.get("id") in folded_calls:
                continue
            else:
                out.append(self._stub_call(tc))
        return out

    @staticmethod
    def _stub_call(tc: dict) -> dict:
        """A copy of a compress call with each summary cut to SUMMARY_STUB_CHARS."""
        fn = dict(tc.get("function") or {})
        args = fn.get("arguments", "")
        as_str = isinstance(args, str)
        try:
            parsed = json.loads(args) if as_str else args
        except (json.JSONDecodeError, TypeError):
            return tc
        if not isinstance(parsed, dict) or not isinstance(parsed.get("ranges"), list):
            return tc
        ranges = []
        for r in parsed["ranges"]:
            if (
                isinstance(r, dict)
                and isinstance(r.get("summary"), str)
                and len(r["summary"]) > SUMMARY_STUB_CHARS
            ):
                r = {**r, "summary": r["summary"][: SUMMARY_STUB_CHARS - 1] + "…"}
            ranges.append(r)
        stubbed = {**parsed, "ranges": ranges}
        fn["arguments"] = json.dumps(stubbed, ensure_ascii=False) if as_str else stubbed
        return {**tc, "function": fn}

    def tools(self) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": "compress",
                    "description": (
                        "Replace one or more contiguous ranges of consumed messages with summaries you write. "
                        "Each range is start ref to end ref inclusive (m-refs from the tags, or block ids to fold "
                        "blocks into a higher tier). Boundaries snap outward so a tool call and its results are "
                        "never split. All ranges apply or none. The summary is the only record of the range: keep "
                        "file paths with line numbers, signatures, exact error strings, decisions and why, exact "
                        "values, user intent and open questions verbatim; drop logs, duplicate reads and dead ends. "
                        "Rejected when a range touches the task message or the last user message, names a ref "
                        "inside an existing block (use the block id), or when the summary is not smaller than "
                        "what it replaces."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "ranges": {
                                "type": "array",
                                "minItems": 1,
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "start": {
                                            "type": "string",
                                            "description": "First ref, e.g. m00010 or b1",
                                        },
                                        "end": {
                                            "type": "string",
                                            "description": "Last ref (inclusive), e.g. m00044 or b3",
                                        },
                                        "topic": {
                                            "type": "string",
                                            "description": "Short label, 3-5 words",
                                        },
                                        "summary": {
                                            "type": "string",
                                            "description": "Complete, self-contained summary replacing the range",
                                        },
                                    },
                                    "required": ["start", "end", "summary"],
                                },
                            },
                        },
                        "required": ["ranges"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "decompress",
                    "description": (
                        "Return the original content of a compressed block (one tier up: a tier-2 block returns "
                        "its child summaries and the live messages between them). The block stays compressed; "
                        "the result is a new tool message you can compress again once used."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "block_id": {"type": "string", "description": "e.g. b1"},
                            "max_chars": {
                                "type": "integer",
                                "description": f"Cap on returned characters (default {DECOMPRESS_MAX_CHARS})",
                            },
                        },
                        "required": ["block_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_context",
                    "description": (
                        "Keyword search across the whole transcript, including messages hidden inside compressed "
                        "blocks. Returns refs, where each hit lives (visible / hidden in bN) and a snippet — "
                        "cheaper than decompressing blind."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string"},
                            "limit": {
                                "type": "integer",
                                "description": f"Max hits (default {SEARCH_LIMIT})",
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "context_status",
                    "description": "Context usage against the limit, the compressed blocks, and the largest compressible ranges.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
        ]

    # -- tool execution ----------------------------------------------------

    @staticmethod
    def handles(name: str) -> bool:
        return name in CONTEXT_TOOL_NAMES

    def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        messages: list[dict],
        *,
        tool_call_id: str,
    ) -> str:
        """Run a context tool. Raises ContextError with a model-facing message on bad input."""
        arguments = arguments or {}
        if name == "compress":
            return self.compress(
                messages, arguments.get("ranges"), tool_call_id=tool_call_id
            )
        if name == "decompress":
            return self.decompress(
                messages,
                str(arguments.get("block_id", "")),
                max_chars=int(arguments.get("max_chars") or DECOMPRESS_MAX_CHARS),
            )
        if name == "search_context":
            return self.search(
                messages,
                str(arguments.get("query", "")),
                limit=int(arguments.get("limit") or SEARCH_LIMIT),
            )
        if name == "context_status":
            return self.status(messages)
        raise ContextError(f"unknown context tool '{name}'")

    def compress(self, messages: list[dict], ranges: Any, *, tool_call_id: str) -> str:
        if not isinstance(ranges, list) or not ranges:
            raise ContextError(
                "compress needs a non-empty 'ranges' list of {start, end, summary}"
            )
        hidden = self._hidden_indices()
        protected = self._protected_indices(messages)
        folded = self._folded_calls()
        planned: list[Block] = []
        notes: dict[int, list[str]] = {}
        for r in ranges:
            if not isinstance(r, dict):
                raise ContextError(
                    "each range must be an object with start, end and summary"
                )
            summary = str(r.get("summary") or "").strip()
            if not summary:
                raise ContextError(
                    f"range {r.get('start')}–{r.get('end')} has an empty summary; the summary is the "
                    "only record of the range, so write one"
                )
            s = self._resolve(messages, str(r.get("start", "")), hidden, start=True)
            e = self._resolve(messages, str(r.get("end", "")), hidden, start=False)
            if e < s:
                raise ContextError(
                    f"range {r.get('start')}–{r.get('end')} is empty (end is before start)"
                )
            s0, e0 = s, e
            s, e = self._snap(messages, s, e)
            if (s, e) != (s0, e0):
                notes.setdefault(s, []).append(
                    f"snapped to {ref(s)}–{ref(e)} to keep tool-call pairs intact"
                )
            for i in range(s, e + 1):
                if i in protected:
                    raise ContextError(
                        f"{ref(i)} is protected ({protected[i]}) and lies inside {ref(s)}–{ref(e)}; "
                        "end the range before it or start after it"
                    )
            children = self._children_for(s, e)
            # what the range costs in the view today: live messages as the view
            # shows them, plus the children's summaries
            tokens_before = sum(
                self._view_cost(messages, i, folded)
                for i in range(s, e + 1)
                if i not in hidden
            ) + sum(c.tokens_after for c in children)
            block = Block(
                id="",
                tier=1 + max((c.tier for c in children), default=0),
                start=s,
                end=e,
                call_id=tool_call_id,
                summary=summary,
                topic=str(r.get("topic") or "").strip(),
                tokens_before=tokens_before,
                tokens_after=0,
                children=[c.id for c in children],
                unread=[c.label() for c in children if c.by_harness]
                + [u for c in children for u in c.unread],
            )
            planned.append(block)

        planned.sort(key=lambda b: b.start)
        for b1, b2 in zip(planned, planned[1:], strict=False):
            if b2.start <= b1.end:
                raise ContextError(
                    f"ranges overlap: {ref(b1.start)}–{ref(b1.end)} and one starting at {ref(b2.start)}"
                )
        for n, block in enumerate(
            planned
        ):  # ids in transcript order; the id is part of the render
            block.id = f"b{len(self.blocks) + 1 + n}"
            self._settle(block)
            if block.tokens_after >= block.tokens_before:
                raise ContextError(
                    f"summary for {ref(block.start)}–{ref(block.end)} is ~{block.tokens_after} tokens "
                    f"but the range is only ~{block.tokens_before}; nothing would be gained. "
                    "Compress a larger range or write less."
                )

        before = estimate_messages_tokens(self.view(messages))
        lines = []
        for block in planned:
            for c in block.children:
                self.blocks[c].active = False
            self.blocks[block.id] = block
            line = (
                f"{ref(block.start)}–{ref(block.end)} → {block.id} (tier {block.tier}, "
                f"{block.tokens_before:,} → {block.tokens_after:,} tokens)"
            )
            if block.children:
                line += f", folds {', '.join(block.children)}"
            if block.unread:
                line += (
                    f"; note: folds {', '.join(block.unread)}, which the harness had hidden "
                    "unsummarized — this summary covers that content from memory only"
                )
            if block.start in notes:
                line += f"; {'; '.join(notes[block.start])}"
            lines.append(line)
        after = estimate_messages_tokens(self.view(messages))  # measured, not derived
        logger.info(
            "context compress: %d range(s), %d → %d tokens", len(planned), before, after
        )
        return (
            f"Compressed {len(planned)} range(s): "
            + "; ".join(lines)
            + f". Context ≈ {before:,} → {after:,} of {self.max_context_tokens:,} tokens."
        )

    def decompress(
        self,
        messages: list[dict],
        block_id: str,
        *,
        max_chars: int = DECOMPRESS_MAX_CHARS,
    ) -> str:
        block = self.blocks.get(block_id)
        if block is None:
            raise ContextError(
                f"no block '{block_id}'; blocks: {', '.join(self.blocks) or 'none'}"
            )
        names = self._tool_names(messages)
        child_by_start = {self.blocks[c].start: self.blocks[c] for c in block.children}
        # a child's compress call and result say nothing its summary does not
        child_calls = {self.blocks[c].call_id for c in block.children}
        parts = [
            f"{block.label()}, {block.tokens_before:,} tokens{'' if block.active else ' (folded into a higher tier)'}:"
        ]
        i = block.start
        while i <= block.end:
            child = child_by_start.get(i)
            if child is not None:
                parts.append(
                    f"--- {child.id} (tier {child.tier}, {ref(child.start)}–{ref(child.end)}) summary ---\n{child.summary}"
                )
                i = child.end + 1
                continue
            if not self._is_call_pair_of(messages[i], child_calls):
                parts.append(
                    f"--- {ref(i)} {self._describe(messages[i], names)} ---\n{self._text(messages[i])}"
                )
            i += 1
        text = "\n\n".join(parts)
        if len(text) > max_chars:
            text = (
                text[:max_chars]
                + f"\n\n[… {len(text) - max_chars:,} more chars; raise max_chars or use search_context]"
            )
        return text

    def search(
        self, messages: list[dict], query: str, *, limit: int = SEARCH_LIMIT
    ) -> str:
        terms = [t for t in query.lower().split() if t]
        if not terms:
            raise ContextError("search_context needs a non-empty query")
        hidden = self._hidden_indices()
        names = self._tool_names(messages)
        hits: list[tuple[int, str]] = []
        for i, msg in enumerate(messages):
            if msg.get("role") == "system":
                continue
            text = self._text(msg)
            low = text.lower()
            counts = [low.count(t) for t in terms]
            if not any(counts):
                continue
            score = sum(counts) + (100 if all(counts) else 0)
            first = min(low.find(t) for t in terms if t in low)
            snippet = text[max(0, first - 100) : first + 160].replace("\n", " ")
            hits.append(
                (
                    score,
                    f"{ref(i)} ({self._describe(msg, names)}, {self._where(i, hidden)}, ~{_fmt(_message_tokens(msg))} tokens): …{snippet}…",
                )
            )
        for b in self.blocks.values():
            low = b.summary.lower()
            counts = [low.count(t) for t in terms]
            if any(counts):
                first = min(low.find(t) for t in terms if t in low)
                snippet = b.summary[max(0, first - 100) : first + 160].replace(
                    "\n", " "
                )
                hits.append(
                    (
                        sum(counts) + (100 if all(counts) else 0),
                        f"{b.id} summary ({ref(b.start)}–{ref(b.end)}): …{snippet}…",
                    )
                )
        if not hits:
            return f"No matches for '{query}'."
        hits.sort(key=lambda h: -h[0])
        shown = [h[1] for h in hits[:limit]]
        more = (
            f"\n({len(hits) - limit} more; raise limit or refine the query)"
            if len(hits) > limit
            else ""
        )
        return "\n".join(shown) + more

    def status(self, messages: list[dict]) -> str:
        view = self.view(messages)
        est = estimate_messages_tokens(view)
        lines = [
            f"Context: {est:,} / {self.max_context_tokens:,} tokens ({100 * est // max(self.max_context_tokens, 1)}%)."
        ]
        if self.blocks:
            lines.append(
                "Blocks: "
                + "; ".join(
                    f"{b.label()} {b.tokens_before:,}→{b.tokens_after:,}{'' if b.active else ' [folded]'}"
                    for b in self.blocks.values()
                )
            )
        ranges = self._compressible_ranges(messages)
        if ranges:
            lines.append(
                "Largest compressible ranges: "
                + ", ".join(f"{ref(s)}–{ref(e)} (~{_fmt(t)})" for s, e, t in ranges[:5])
            )
        return "\n".join(lines)

    # -- internals ---------------------------------------------------------

    def _hidden_indices(self) -> set[int]:
        hidden: set[int] = set()
        for b in self.blocks.values():
            if b.active:
                hidden.update(range(b.start, b.end + 1))
        return hidden

    def _protected_indices(self, messages: list[dict]) -> dict[int, str]:
        protected: dict[int, str] = {}
        users = [i for i, m in enumerate(messages) if m.get("role") == "user"]
        if messages and messages[0].get("role") == "system":
            protected[0] = "system prompt"
        if users:
            protected[users[-1]] = "the last user message"
            protected[users[0]] = (
                "the task message"  # wins when they are the same message
            )
        return protected

    def _resolve(
        self, messages: list[dict], token: str, hidden: set[int], *, start: bool
    ) -> int:
        token = token.strip()
        if _BLOCK.match(token):
            block = self.blocks.get(token)
            if block is None or not block.active:
                raise ContextError(
                    f"no active block '{token}'; active blocks: {', '.join(b.id for b in self.blocks.values() if b.active) or 'none'}"
                )
            return block.start if start else block.end
        if m := _REF.match(token):
            i = int(m.group(1)) - 1
            if i < 0 or i >= len(messages):
                raise ContextError(
                    f"{token} does not exist; the transcript ends at {ref(len(messages) - 1)}"
                )
            if i in hidden:
                owner = next(
                    b
                    for b in self.blocks.values()
                    if b.active and b.start <= i <= b.end
                )
                raise ContextError(
                    f"{token} is inside {owner.label()}; use {owner.id} as the boundary"
                )
            return i
        raise ContextError(f"'{token}' is not a ref (m00042) or a block id (b1)")

    @staticmethod
    def _snap(messages: list[dict], s: int, e: int) -> tuple[int, int]:
        """Widen [s, e] so no assistant tool call is separated from its results."""
        owner = ContextCompressor._owners(messages)
        if messages[s].get("role") == "tool" and (a := owner.get(s)) is not None:
            s = a
        if messages[e].get("role") == "tool" and (a := owner.get(e)) is not None:
            e = max(e, a)
        if messages[e].get("role") == "assistant" and messages[e].get("tool_calls"):
            ids = {tc.get("id") for tc in messages[e]["tool_calls"]}
            j = e + 1
            while (
                j < len(messages)
                and messages[j].get("role") == "tool"
                and messages[j].get("tool_call_id") in ids
            ):
                e = j
                j += 1
        if messages[e].get("role") == "tool" and (a := owner.get(e)) is not None:
            ids = {tc.get("id") for tc in messages[a].get("tool_calls", [])}
            j = e + 1
            while (
                j < len(messages)
                and messages[j].get("role") == "tool"
                and messages[j].get("tool_call_id") in ids
            ):
                e = j
                j += 1
        return s, e

    @staticmethod
    def _owners(messages: list[dict]) -> dict[int, int]:
        """tool-result index → index of the assistant message that called it."""
        by_id: dict[str, int] = {}
        owners: dict[int, int] = {}
        for i, m in enumerate(messages):
            if m.get("role") == "assistant":
                for tc in m.get("tool_calls") or []:
                    if tc.get("id"):
                        by_id[tc["id"]] = i
            elif m.get("role") == "tool" and m.get("tool_call_id") in by_id:
                owners[i] = by_id[m["tool_call_id"]]
        return owners

    @staticmethod
    def _tool_names(messages: list[dict]) -> dict[str, str]:
        names: dict[str, str] = {}
        for m in messages:
            for tc in m.get("tool_calls") or []:
                if tc.get("id"):
                    names[tc["id"]] = (tc.get("function") or {}).get("name") or "tool"
        return names

    @staticmethod
    def _is_call_pair_of(msg: dict, call_ids: set[str]) -> bool:
        """Is this message the compress call, or the result, of one of ``call_ids``?"""
        if msg.get("role") == "tool":
            return msg.get("tool_call_id") in call_ids
        calls = msg.get("tool_calls") or []
        return bool(calls) and all(tc.get("id") in call_ids for tc in calls)

    def _children_for(self, s: int, e: int) -> list[Block]:
        """Active blocks that [s, e] spans whole. Refs inside a block are rejected
        by ``_resolve`` and ``_snap`` never widens into one, so a partial overlap
        cannot normally arise; it is still an error rather than a silent fold."""
        children = []
        for b in self.blocks.values():
            if not b.active or e < b.start or s > b.end:
                continue
            if s <= b.start and e >= b.end:
                children.append(b)
            else:
                raise ContextError(
                    f"{ref(s)}–{ref(e)} cuts into {b.label()}; use {b.id} as the boundary to fold it whole"
                )
        return children

    def _make_room(self, messages: list[dict], *, target: int) -> bool:
        """Over the limit: hide the oldest live turns, whole, behind a block the
        harness writes itself, until the view fits ``target``.

        The same mechanism as the model's ``compress`` with a listing for a
        summary, so nothing in the view is left standing per message: the
        block grows at its end as more has to go, and the model can fold it
        into a block of its own later. Blocks the model made are never put
        under a harness block — its summaries are the point — so a harness
        block runs from where the last block ended to where it had to stop.
        Returns whether anything was hidden.
        """
        hid: list[str] = []
        while (est := estimate_messages_tokens(self.view(messages))) > target:
            folded = self._folded_calls()
            hidden_now = False
            for s, e, _ in sorted(self._compressible_ranges(messages)):  # oldest first
                need, freed, end = est - target, 0, e
                for i in range(s, e + 1):
                    freed += self._view_cost(messages, i, folded)
                    if freed >= need and self._ends_turn(messages, i):
                        end = i
                        break
                s, end = self._snap(messages, s, end)
                prev = next(
                    (
                        b
                        for b in self.blocks.values()
                        if b.active and b.by_harness and b.end == s - 1
                    ),
                    None,
                )
                if prev is None:
                    block = Block(
                        id=f"b{len(self.blocks) + 1}",
                        tier=1,
                        start=s,
                        end=end,
                        call_id=HARNESS_CALL,
                        summary="",
                        topic="hidden by the harness",
                        tokens_before=0,
                        tokens_after=0,
                    )
                else:
                    block = prev
                    block.end = end
                block.tokens_before += sum(
                    self._view_cost(messages, i, folded) for i in range(s, end + 1)
                )
                block.summary = self._listing(messages, block)
                self._settle(block)
                if prev is None and block.tokens_after >= block.tokens_before:
                    continue  # a run smaller than its own listing; try the next one
                self.blocks[block.id] = block
                hid.append(f"{ref(s)}–{ref(end)} behind {block.id}")
                hidden_now = True
                break
            if not hidden_now:
                logger.warning(
                    "context: ~%d tokens over the limit with nothing left to hide",
                    est - self.max_context_tokens,
                )
                break
        if hid:
            self._room_note = (
                f"The harness hid {', '.join(hid)} to stay under the limit; nothing was summarized — "
                "decompress or search_context can still reach it. Compress consumed ranges yourself "
                "before this happens again."
            )
            logger.warning(
                "context: harness hid %s to stay under %d tokens",
                ", ".join(hid),
                self.max_context_tokens,
            )
        return bool(hid)

    @staticmethod
    def _ends_turn(messages: list[dict], i: int) -> bool:
        return i + 1 >= len(messages) or messages[i + 1].get("role") != "tool"

    @staticmethod
    def _listing(messages: list[dict], block: Block) -> str:
        """What a harness block says in place of a summary: counts, not content."""
        counts: dict[str, int] = {}
        turns = 0
        for i in range(block.start, block.end + 1):
            m = messages[i]
            if m.get("role") == "assistant":
                turns += 1
                for tc in m.get("tool_calls") or []:
                    name = (tc.get("function") or {}).get("name") or "tool"
                    counts[name] = counts.get(name, 0) + 1
            elif m.get("role") == "user":
                counts["user message"] = counts.get("user message", 0) + 1
        what = ", ".join(
            f"{n} ×{c}"
            for n, c in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
        )
        return (
            f"Hidden by the harness to stay under the context limit; the model never summarized it. "
            f"{turns} turn(s): {what or 'no tool calls'}. decompress {block.id} to read it, or search_context."
        )

    def _compressible_ranges(self, messages: list[dict]) -> list[tuple[int, int, int]]:
        """Contiguous runs of live, unprotected messages, largest first: (start, end, tokens)."""
        hidden = self._hidden_indices()
        protected = self._protected_indices(messages)
        folded = self._folded_calls()
        last_turn = max(
            (i for i, m in enumerate(messages) if m.get("role") == "assistant"),
            default=len(messages),
        )
        runs: list[tuple[int, int, int]] = []
        start: int | None = None
        tokens = 0
        for i in range(len(messages) + 1):
            live = (
                i < len(messages)
                and i not in hidden
                and i not in protected
                and i < last_turn
            )
            if live:
                if start is None:
                    start, tokens = i, 0
                tokens += self._view_cost(messages, i, folded)
            elif start is not None:
                s, e = self._snap(messages, start, i - 1)
                runs.append((s, e, tokens))
                start = None
        runs.sort(key=lambda r: -r[2])
        return runs

    def _settle(self, block: Block) -> None:
        """Set ``tokens_after`` to what the block's render costs. The render
        prints that number, so it is a fixed point: re-render until stable."""
        for _ in range(3):
            n = _message_tokens(self.render(block))
            if n == block.tokens_after:
                return
            block.tokens_after = n

    def _view_cost(self, messages: list[dict], i: int, folded_calls: set[str]) -> int:
        """What ``messages[i]`` costs in the wire view: the tagged/stubbed message
        the view builds, or nothing for a folded compress pair."""
        m = self._view_message(messages, i, folded_calls)
        return _message_tokens(m) if m is not None else 0

    def _append_nudge(
        self, view: list[dict], messages: list[dict], est: int, *, ask: bool = True
    ) -> None:
        """Say what the harness has to say as a message of its own, after the
        latest tool result — not inside it. Models discount instructions found
        in tool output (they are trained to), and one did, every time."""
        if not view or view[-1].get("role") != "tool":
            return
        notes = []
        if self._room_note:
            notes.append(self._room_note)
            self._room_note = ""
        ranges = self._compressible_ranges(messages)
        compressible = sum(t for _, _, t in ranges)
        if (
            ask
            and est >= self.max_context_tokens * NUDGE_AT
            and compressible >= self.max_context_tokens * NUDGE_MIN_COMPRESSIBLE
        ):
            top = ", ".join(f"{ref(s)}–{ref(e)} (~{_fmt(t)})" for s, e, t in ranges[:3])
            notes.append(
                f"{100 * est // max(self.max_context_tokens, 1)}% of the {self.max_context_tokens:,}-token limit used. "
                f"Largest compressible ranges: {top}. Compress consumed ranges before continuing."
            )
        if notes:
            view.append({"role": "user", "content": "[context] " + " ".join(notes)})

    def _where(self, i: int, hidden: set[int]) -> str:
        if i in hidden:
            owner = next(
                b for b in self.blocks.values() if b.active and b.start <= i <= b.end
            )
            return f"hidden in {owner.id}"
        return "visible"

    @staticmethod
    def _describe(msg: dict, names: dict[str, str]) -> str:
        role = msg.get("role", "?")
        if role == "tool":
            return f"tool {names.get(msg.get('tool_call_id') or '', '')}".rstrip()
        if role == "assistant" and msg.get("tool_calls"):
            return "assistant → " + ", ".join(
                (tc.get("function") or {}).get("name", "?") for tc in msg["tool_calls"]
            )
        return role

    @staticmethod
    def _text(msg: dict) -> str:
        parts = []
        if msg.get("content"):
            parts.append(str(msg["content"]))
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function") or {}
            args = fn.get("arguments", "")
            if not isinstance(args, str):
                args = json.dumps(args, default=str)
            parts.append(f"{fn.get('name', '?')}({args})")
        return "\n".join(parts)
