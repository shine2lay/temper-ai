"""A dispatcher that fans out nothing must say so.

`for_each: structured.topics` returns an empty iteration when the agent
produced no structured output — deliberately graceful, so a transient LLM
failure does not crash the phase. But it was silent, so a workflow whose
whole purpose was to fan out could complete green having done none of it.
"""

from temper_ai.stage.dispatch import render_dispatch

CONFIG = {
    "dispatch": [
        {
            "op": "add",
            "for_each": "structured.topics",
            "as": "topic",
            "node": {"name": "research_{{ topic }}", "type": "agent", "agent": "worker"},
        }
    ]
}


def test_missing_structured_output_is_reported():
    notes: list[str] = []
    ops = render_dispatch(CONFIG, agent_structured=None, notes=notes)
    assert ops == []
    assert notes and "fanned out nothing" in notes[0]
    assert "structured.topics" in notes[0]


def test_a_successful_fan_out_reports_nothing():
    notes: list[str] = []
    ops = render_dispatch(CONFIG, agent_structured={"topics": ["a", "b"]}, notes=notes)
    assert len(ops) == 2
    assert notes == []


def test_notes_are_optional():
    assert render_dispatch(CONFIG, agent_structured=None) == []
