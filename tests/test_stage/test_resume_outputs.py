"""A resumed run owes the same outputs as the run it resumes.

`execute_graph_with_state` is the resume path: the API's resume and fork endpoints both go
through it with the outputs already recovered from a checkpoint. It took every argument
`execute_graph` takes except `workflow_outputs`, and quietly dropped it -- so a resumed run
finished with `workflow_output` empty no matter what its nodes produced.

What that cost: the EPD driver reads a finished run's `workflow_output` to record what the bet
did. b004 was resumed from a checkpoint, its PR was merged, deployed and measured, and the run
reported nothing -- so the driver recorded it as "stopped after build=None". The work was fine;
the run just could not say so.
"""

from unittest.mock import patch

from temper_ai.stage.executor import execute_graph_with_state


def _call_args(**kwargs) -> dict:
    """What `execute_graph_with_state` hands down to `execute_graph`."""
    seen: dict = {}

    def fake(nodes, input_data, context, **kw):
        seen.update(kw)
        return "result"

    with patch("temper_ai.stage.executor.execute_graph", side_effect=fake) as inner:
        assert execute_graph_with_state([], {}, object(), **kwargs) == "result"
        assert inner.called
    return seen


def test_the_resume_path_carries_the_workflows_declared_outputs():
    outputs = {"pr": "ship.structured.pr", "shipped": "deploy.structured.status"}
    passed = _call_args(graph_name="epd_loop", is_workflow=True, workflow_outputs=outputs)
    assert passed["workflow_outputs"] == outputs, (
        "a resumed run that maps no outputs reports nothing about what it did"
    )


def test_it_still_carries_what_it_always_carried():
    restored = {"tasks": "a NodeResult in real use"}
    meta = {"resume_of": "evt-1", "restored_node_names": ["tasks"]}
    passed = _call_args(graph_name="epd_loop", is_workflow=True,
                        initial_outputs=restored, resume_metadata=meta)
    assert passed["initial_outputs"] == restored
    assert passed["resume_metadata"] == meta
    assert passed["graph_name"] == "epd_loop" and passed["is_workflow"] is True
    assert passed["workflow_outputs"] is None, "no outputs asked for, none invented"
