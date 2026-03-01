# Plan: Prompt Injection Defense

## Problem

Agent prompts are built by concatenating untrusted content with no sanitization.
The injection chain:

```
agent A output / tool result / external content
  → stage output → input_data
  → _inject_input_context() dumps raw into prompt
  → agent B executes manipulated prompt
```

Attack vectors:
- **Agent-to-agent**: agent A's LLM output contains instructions that override agent B's prompt
- **Tool-to-agent**: web scraper, file reader, HTTP client return content with embedded instructions
- **User input**: workspace files or run inputs contain adversarial text

No sanitization exists anywhere in this chain today.

## Design

### 1. Input boundary markers

Wrap injected content in clear delimiters so the LLM can distinguish system
instructions from external data:

```
<input name="design_output" source="stage:vcs_design">
[content here]
</input>
```

This doesn't prevent injection but makes it harder — the LLM sees structure
that separates instructions from data. Replace the current `## Label\nvalue`
format in `_inject_input_context()`.

### 2. Content scanning

Lightweight scanner that flags known injection patterns before they enter
the prompt:

- Instruction override attempts ("ignore previous instructions", "you are now")
- Role injection ("system:", "assistant:")
- Excessive prompt-like formatting in data fields

Scanner runs on each value before injection. Flagged content is:
- Logged as a warning with the source identified
- Optionally escaped or truncated (configurable per agent)
- Not silently passed through

```python
def scan_input_content(value: str, source: str) -> ScanResult:
    """Scan input content for injection patterns."""
    ...
```

### 3. Output guardrails on producing agents

The existing `output_guardrails` config can be extended to check that an
agent's output doesn't contain prompt injection patterns before it flows
downstream. This catches the agent-to-agent vector at the source.

### 4. Tool output sandboxing

Tool results (especially web scraper, HTTP client, file reader) should be
treated as untrusted by default. Wrap tool outputs in boundary markers
before they enter the conversation history in `inject_results()`.

## Scope

Phase 1 (minimal viable):
- Input boundary markers in `_inject_input_context()`
- Tool output boundary markers in `inject_results()`

Phase 2:
- Content scanner with configurable strictness
- Output guardrails for producing agents

Phase 3:
- Per-agent trust levels (internal agent output vs external tool output vs user input)
- Audit logging of flagged content

## File Changes

| File | Change |
|---|---|
| `temper_ai/agent/base_agent.py` | `_inject_input_context()` uses boundary markers |
| `temper_ai/llm/_prompt.py` | `inject_results()` wraps tool outputs in boundary markers |
| `temper_ai/agent/utils/content_scanner.py` | **New** — injection pattern scanner |
| `temper_ai/agent/standard_agent.py` | `_build_prompt()` runs scanner on inputs before injection |

## Verification

- Boundary markers present in rendered prompts around all injected content
- Scanner flags "ignore previous instructions" in input data
- Tool outputs wrapped in boundary markers in conversation history
- Existing agent behavior unchanged (markers are additive)
- No false positives on normal business content
