[Home](../index.md) | [Tools](../tools/index.md) | [LLM Providers](../providers/index.md) | **Agent Types** | [Safety Policies](../policies/index.md) | [Topology Strategies](../strategies/index.md)

# `jev` Agent

[Back to Agent Types](index.md)

Jev agent — asks TypeSafe AI's Jev model typed questions about the node's inputs.

Jev is not an LLM, so this is not an LLMAgent with another provider behind it. It writes no text.
It is given some content (the *state*) and a set of named questions, each of a declared type, and
returns every answer at once, with its probabilities:

    noul     yes or no: the probability of yes             {"type": "noul", "noul": 0.02}
    choice   one of the options named in `criteria`        {"type": "choice", "choice": "blocking",
                                                             "confidence": 0.91, "probabilities": {...}}
    score    a level of the ordered rubric in `criteria`   {"type": "score", "score": 1.7,
                                                             "confidence": 0.8, "legend": {...}, ...}

The answers are structured already, so they become the node's structured_output as they arrive,
keyed by question name: there is no prompt to build and no reply to parse. A condition routes on
them the way it routes on any node's output (`triage.structured.severity.choice`).

    name: triage_finding
    type: jev
    model: jev-1.13.0                  # default jev-latest, which moves; pin it
    state_template: "{{ finding }}"    # Jinja over the node's inputs; a mapping renders to an object
    questions:
      severity:
        type: choice
        instructions: How serious is this review finding?
        criteria:
          blocking: Breaks behaviour or loses data
          minor: Style, naming or a nit

The API key is read from TYPESAFE_API_KEY in temper's own process. Scripts never see it: the Bash
tool strips every *_API_KEY from the environment it gives them. TYPESAFE_BASE_URL overrides the
endpoint (the same two variables TypeSafe's SDK reads).

Agent that answers typed questions about its inputs with TypeSafe AI's Jev model.

## Execution Pipeline

Render the state, ask the questions, return the answers as structured output.

Every failure (bad config, a state rendered from nothing, no key, a refused request)
is a failed node with the reason in `error`, never an exception: AgentNode would retry an
exception, and none of these is fixed by asking again. Transient trouble (429, 5xx, a
dropped connection) is retried here instead, before the node gives up.

## Validation

Return list of config validation errors. Empty = valid.

## Config Options

```yaml
agent:
  name: "my_agent"
  type: "jev"
```

## Related

