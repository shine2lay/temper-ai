# Workflow inputs

_Written by hand, not generated. The code: `temper_ai/stage/input_defaults.py`._

A workflow lists the values a run can be given under `inputs:`. A stage (or a nested workflow)
can list its own the same way.

```yaml
workflow:
  name: release_notes
  inputs:
    repo:
      type: string
      required: true
      description: The repository, owner/name.
    since:
      type: string
      required: false
      default: last-release
      description: Where the notes start.
```

| Key | What it does |
|---|---|
| `type` | The kind of value: `string`, `number`, `integer`, `boolean`, a list, an object. The dashboard's run form uses it (a number field is sent as a number). |
| `required` | The run needs a value. A required input that has a `default` always counts as given. |
| `default` | The value the run gets when it leaves the input out (below). |
| `description` | Shown next to the field in the dashboard's run form and to the Slack picker. |

## When a default applies

A declared `default` takes the place of an input that is:

- left out of the run's inputs,
- sent as null, or
- sent as empty text (`""`).

Any other value is kept exactly as given, including text of only spaces, `0`, `false`, and an
empty list or object. An input with no `default` stays as the run sent it.

Temper fills the defaults in on every way a run's inputs arrive:

- when a run starts, whichever way it comes in: the dashboard, the API, Slack, Telegram, the
  Linear, Notion and GitHub hooks, schedule triggers, MCP, `temper run`. The run's saved inputs
  show the values it used;
- when the run's box starts it, and on a resume or a fork, so a run saved before a default was
  added gets it too;
- before the workflow is built, so `type: template` nodes and the run-start checks (a team's
  `goal`, for one) see the filled values;
- in a stage or nested workflow: its own `inputs:` defaults fill in whatever its `input_map`
  leaves out.

The dashboard's run form starts each field at its default and leaves an optional field you clear
out of the run, so the run gets the default.

## A value that isn't there

When a run leaves out an input that has no default, a step that reads it gets no value (None):

- a script step gets empty text, in all three ways a script can take a value: `{{ name }}`,
  `"{{ name }}"`, and `{{ name | env }}` (the variable is set, to empty text). A script never
  gets the word `None`;
- a model step's prompt shows `None`, as before.

Not the same thing: a name the step was not given at all. A script step renders it as blank and
notes it in the step's record, or fails the step when the agent config says
`strict_undefined: true`. A name that is there without a value is empty text either way.

`configs/workflows/ci_input_defaults.yaml` shows all of it and costs nothing to run: it prints
what its script steps got.
