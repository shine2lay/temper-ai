"""What a run spent, read from its recorded events: one rule for every reader.

A run's workflow event carries its totals (``cost_usd``, ``total_tokens``) once the executor
has written them: at a normal end (``_build_final_result``), a stand-down, or a graph thrown
out (``_end_graph``). Runs whose event has none (every run cancelled or failed before the end
wrote them, a run whose box died before any ending) are read here instead, by the rule the
executor uses for a completed run: everything its steps spent, rewound (retired) attempts
included, plus what a step in flight had spent when the run was thrown out.

A park writes totals too, in its ``parked`` note, but of the finished steps only
(``_note_parked``): the step that parked is still in flight, and what it spent so far is only
in its recorded calls. ``cancel_parked`` ends such a run without new totals. So a note's
figure is a floor (``stored_totals`` says which kind a figure is): a run waiting on the owner,
or cancelled while it waited, is read here as well, and the larger of the two counts, cost
and tokens each (queue #104).

Per agent the spend is the larger of what its end event says and what its model calls
(``llm.call.completed`` / ``llm.call.failed``) add up to: an agent that finished says what it
spent; one thrown out mid-step (no end event, or a failed one with no cost) is known only by
its calls. A completed run's stored cost equals the sum of its model-call costs. Pi's
stored token total can differ: its call counts are nullable observations, while numeric
agent-end/mapper/stored-run totals keep legacy aggregation. Without a numeric agent end
(in flight, a parked run's in-flight step, or a lost/cancelled/failed agent), an unknown
call total adds zero here, so this token floor can be lower than before. Dollar spend is
unchanged. Only figures are read (JSON fields in the query), never prompts or answers.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import select
from sqlmodel import col

from temper_ai.database import get_session
from temper_ai.observability.event_types import EventType
from temper_ai.observability.models import Event

_LLM_ENDS = (EventType.LLM_CALL_COMPLETED.value, EventType.LLM_CALL_FAILED.value)
_AGENT_ENDS = (EventType.AGENT_COMPLETED.value, EventType.AGENT_FAILED.value)


@dataclass
class Spend:
    """Money and tokens."""

    cost_usd: float = 0.0
    total_tokens: int = 0

    def __add__(self, other: Spend) -> Spend:
        return Spend(self.cost_usd + other.cost_usd, self.total_tokens + other.total_tokens)


@dataclass
class _AgentSpend:
    llm: Spend
    end: Spend | None  # what the agent's end event says, when it says what it cost

    def spent(self) -> Spend:
        end = self.end or Spend()
        return Spend(max(end.cost_usd, self.llm.cost_usd), max(end.total_tokens, self.llm.total_tokens))


END_TOTALS = "end_totals"
PARKED_NOTE = "parked_note"


@dataclass(frozen=True)
class StoredTotals:
    """Totals a workflow event carries itself, and where they came from.

    ``END_TOTALS``: top-level, written when the run ended; the run's figure.
    ``PARKED_NOTE``: the ``parked`` note's, the finished steps only; a floor under what the
    run's recorded events say it spent (see the module's docstring).
    """

    spend: Spend
    source: str

    @property
    def is_floor(self) -> bool:
        return self.source == PARKED_NOTE


def stored_totals(data: dict | None) -> StoredTotals | None:
    """The totals a workflow event carries itself and where they came from, or None.

    Top-level ``cost_usd`` / ``total_tokens`` (a run that ended: ``END_TOTALS``), else the
    ``parked`` note's (a run waiting on a person, or cancelled while it waited:
    ``PARKED_NOTE``, a floor).
    """
    data = data or {}
    for source, totals in ((END_TOTALS, data), (PARKED_NOTE, data.get("parked") or {})):
        if isinstance(totals, dict) and totals.get("cost_usd") is not None:
            spend = Spend(float(totals.get("cost_usd") or 0), int(totals.get("total_tokens") or 0))
            return StoredTotals(spend, source)
    return None


def _spend_rows(execution_ids: Iterable[str]) -> list[tuple]:
    """``(execution_id, type, parent_id, cost_usd, total_tokens, tokens)`` of the runs' agent
    and model-call ends, in one query; the figures are read out of the JSON in the database."""
    ids = list(dict.fromkeys(execution_ids))
    if not ids:
        return []
    data = col(Event.data)
    with get_session() as session:
        return [tuple(row) for row in session.execute(
            select(
                col(Event.execution_id), col(Event.type), col(Event.parent_id),
                data["cost_usd"].as_float(), data["total_tokens"].as_float(), data["tokens"].as_float(),
            ).where(
                col(Event.execution_id).in_(ids),
                col(Event.type).in_((*_LLM_ENDS, *_AGENT_ENDS)),
            )
        ).all()]


def _agents_by_run(rows: list[tuple]) -> dict[str, dict[str | None, _AgentSpend]]:
    """Each run's spend per agent event id (the parent of its calls and of its end event)."""
    runs: dict[str, dict[str | None, _AgentSpend]] = defaultdict(dict)
    for execution_id, etype, parent_id, cost, total_tokens, tokens in rows:
        agent = runs[execution_id].setdefault(parent_id, _AgentSpend(Spend(), None))
        if etype in _LLM_ENDS:
            agent.llm = agent.llm + Spend(float(cost or 0), int(total_tokens or 0))
        elif cost is not None:
            ended = Spend(float(cost), int(tokens or total_tokens or 0))
            agent.end = ended if agent.end is None else agent.end + ended
    return runs


def run_spend(execution_ids: Iterable[str]) -> dict[str, Spend]:
    """What each run spent by its recorded events, by the rule above (one query for all).

    Runs with no spend recorded are missing from the result (read them as zero).
    """
    return {
        execution_id: sum((a.spent() for a in agents.values()), Spend())
        for execution_id, agents in _agents_by_run(_spend_rows(execution_ids)).items()
    }


def attempt_spend(execution_id: str, root_event_id: str, parents: dict[str, str | None]) -> Spend:
    """What the agents under one graph event (one attempt of a run) spent, by the rule above.

    ``parents`` is ``{event id: parent id}`` of the run's events (``event_parents``), which
    places each agent under the graph; an earlier attempt's agents hang under its own event.
    """
    def under_root(event_id: str | None) -> bool:
        seen: set[str] = set()
        while event_id and event_id not in seen:
            if event_id == root_event_id:
                return True
            seen.add(event_id)
            event_id = parents.get(event_id)
        return False

    agents = _agents_by_run(_spend_rows([execution_id])).get(execution_id, {})
    return sum((a.spent() for agent_id, a in agents.items() if under_root(agent_id)), Spend())
