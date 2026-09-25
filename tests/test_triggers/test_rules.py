"""Trigger rules: what a rule file may say, and what an event turns into.

The failure modes pinned here are the quiet ones. A rule with a typo in a
field name must not start a workflow with a blank input; one broken file
must not stop every other rule firing; and text a person typed into Linear
must never be run as a template.
"""

from pathlib import Path

import pytest
import yaml

from temper_ai.triggers.rules import (
    Trigger,
    TriggerConfigError,
    load_triggers,
    parse_trigger,
    render_inputs,
)

RULE = """
trigger:
  name: {name}
  source: linear
  on:
    type: Issue
    label_added: temper
  workflow: linear_reply
  inputs:
    issue_id: "{{{{ data.id }}}}"
"""


def _write(folder: Path, filename: str, text: str) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / filename).write_text(text)


class TestParse:
    def test_a_bare_on_key_is_read_as_the_mapping_not_the_boolean(self):
        # YAML 1.1 turns the key `on` into True; the rule must still see its filter.
        trigger = parse_trigger(yaml.safe_load(RULE.format(name="r")))
        assert trigger.on == {"type": "Issue", "label_added": "temper"}
        assert trigger.source == "linear"
        assert trigger.ignore_self is True
        assert trigger.enabled is True

    @pytest.mark.parametrize("missing", ["name", "source", "workflow"])
    def test_required_fields(self, missing):
        raw = yaml.safe_load(RULE.format(name="r"))
        del raw["trigger"][missing]
        with pytest.raises(TriggerConfigError, match=missing):
            parse_trigger(raw)

    def test_an_empty_filter_is_refused(self):
        # An empty `on:` would match every event Linear sends.
        with pytest.raises(TriggerConfigError, match="'on'"):
            parse_trigger({"trigger": {"name": "r", "source": "linear", "workflow": "w", "on": {}}})

    def test_a_template_that_does_not_parse_is_refused_when_loaded(self):
        raw = yaml.safe_load(RULE.format(name="r"))
        raw["trigger"]["inputs"]["broken"] = "{{ data.id "
        with pytest.raises(TriggerConfigError, match="broken"):
            parse_trigger(raw)


class TestLoad:
    def test_a_broken_file_is_skipped_and_the_rest_still_load(self, tmp_path):
        folder = tmp_path / "triggers"
        _write(folder, "a_good.yaml", RULE.format(name="good"))
        _write(folder, "b_bad.yaml", "trigger: [not, a, mapping]")
        names = [t.name for t in load_triggers(tmp_path)]
        assert names == ["good"]

    def test_local_rules_load_after_tracked_ones_and_cannot_take_a_name(self, tmp_path):
        folder = tmp_path / "triggers"
        _write(folder, "shared.yaml", RULE.format(name="same"))
        _write(folder / "local", "mine.yaml", RULE.format(name="same"))
        _write(folder / "local", "extra.yaml", RULE.format(name="extra"))
        triggers = load_triggers(tmp_path)
        assert [t.name for t in triggers] == ["same", "extra"]
        assert triggers[0].path.endswith("triggers/shared.yaml")

    def test_filtered_by_source(self, tmp_path):
        _write(tmp_path / "triggers", "r.yaml", RULE.format(name="r"))
        assert load_triggers(tmp_path, source="linear")
        assert load_triggers(tmp_path, source="github") == []

    def test_no_folder_means_no_rules(self, tmp_path):
        assert load_triggers(tmp_path) == []

    def test_the_shipped_rules_all_load(self):
        # Every tracked rule must parse: a broken one is only a log line at runtime.
        root = Path(__file__).resolve().parents[2] / "configs" / "triggers"
        files = sorted(root.glob("*.yaml"))
        assert files, "expected at least one tracked rule"
        for path in files:
            parse_trigger(yaml.safe_load(path.read_text()), str(path))


def _trigger(**inputs: str) -> Trigger:
    return Trigger(name="t", source="linear", on={"type": "Issue"}, workflow="w", inputs=inputs)


class TestRender:
    def test_fields_of_the_event(self):
        event = {"data": {"id": "abc", "title": "Fix it"}, "url": "https://linear.app/x"}
        out = render_inputs(_trigger(issue_id="{{ data.id }}", link="{{ url }}"), event)
        assert out == {"issue_id": "abc", "link": "https://linear.app/x"}

    def test_a_field_the_event_does_not_have_is_an_error_not_a_blank(self):
        with pytest.raises(TriggerConfigError, match="issue_id"):
            render_inputs(_trigger(issue_id="{{ data.idd }}"), {"data": {"id": "abc"}})

    def test_a_null_field_is_an_empty_string(self):
        out = render_inputs(_trigger(desc="{{ data.description }}"), {"data": {"description": None}})
        assert out == {"desc": ""}

    def test_text_from_linear_is_data_never_a_template(self):
        title = "{{ 7 * 7 }} {% for x in range(3) %}x{% endfor %}"
        out = render_inputs(_trigger(title="{{ data.title }}"), {"data": {"title": title}})
        assert out == {"title": title}

    def test_the_sandbox_refuses_reaching_into_python(self):
        with pytest.raises(TriggerConfigError):
            render_inputs(_trigger(x="{{ data.__class__.__mro__[1].__subclasses__() }}"), {"data": {}})
