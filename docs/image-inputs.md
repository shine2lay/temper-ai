# One inline PNG with an LLM agent

`image_input` is an opt-in, **one-image, tool-free, at-most-one-provider-send** mode of `type: llm`. Omitting the field keeps the existing text/tool/memory agent behavior. It uses Temper's existing native Anthropic provider and an **already configured named OAuth subscription token**. It does not use the Claude CLI, a paid API-key route, a new provider or a fallback account.

## Agent configuration

```yaml
name: screenshot-reader
type: llm
provider: anthropic
model: YOUR_EXISTING_MODEL_ID
# A label configured by your operator, NOT a credential or ${secret} expansion.
token: existing-subscription-label
tools: []                         # Mandatory, explicit, empty list
image_input:
  key: screenshot
  media_type: image/png
system_prompt: Describe the supplied screenshot using the stated criteria.
task_template: "{{ task }}"       # Never interpolate screenshot here
max_tokens: 4096                   # Normal native output setting; choose for your task
# total_timeout: 300               # Existing default; may be configured normally
```

The names above are placeholders, not an installed account/model recommendation. Keep your existing authorised model/account/auth route. No model/account entitlement is established by this example.

`image_input` accepts **exactly** `key` (a nonempty input-data key) and `media_type: image/png`. Its presence, including an invalid/null value, opts into validation rather than falling back to text mode.

The node's input is an ordinary mapping:

- `task`: ordinary text used by the Jinja template.
- `screenshot`: one **canonical RFC 4648 base64 string** containing the PNG bytes.
- Other ordinary text/template fields may be supplied. The attachment key is removed before rendering; exact attachment aliases in other fields/templates are redacted too.

No path, URL, data URL, arbitrary nested content block, image list, animated PNG or second attachment is accepted. Validation checks base64 round-trip, PNG signature, IHDR/chunk structure and CRCs, nonanimated compressed scanline shape and filter bytes. It does not render the image or inspect its meaning. No discretionary local image-byte quota is added. The provider's actual request/image/model constraints still apply; a provider rejection fails this operation without another send.

## Caller-owned deterministic preparation

Prepare the attachment in the existing authorised capture/preparation step of your Temper workflow, **not with a model tool**. For example, if that step already holds the authorised screenshot bytes in memory:

```python
import base64

# screenshot_bytes already belongs to the caller's authorised capture step.
node_input = {
    "task": "Describe the screenshot against the supplied criteria.",
    "screenshot": base64.b64encode(screenshot_bytes).decode("ascii"),
}
```

Pass the mapping as this agent node's input through the workflow's normal **explicit** input wiring. For example, these node `input_map` entries select only the intended fields (not a complete workflow):

```yaml
input_map:
  task: workflow.task
  screenshot: capture.structured.screenshot
```

Keep the capture's ordinary storage/outputs qualified for the intended data. Do not omit `input_map` and inherit an entire workflow or predecessor history. Auto-injected `_strategy_context`, `other_agents`, `workspace_path` and `memories` inputs, and the `_receives_strategy_context` configuration override, are refused. The agent does not add the execution context's workspace path. Only the explicitly selected intended image/text and fixed reviewer instructions belong in this mode. Keep website-derived data in user inputs, never `system_prompt` or other instruction roles.

Do not print/echo the attachment, place it in a template, or use a model to read a file/URL and recreate it. This snippet is a data contract, not a registered/runnable workflow or permission to capture/read any site/file.

**Upstream storage is separate:** the opt-in agent records only attachment metadata, never base64, prompts or request/response bodies. It cannot erase data a caller already logged or stored. In particular, the ordinary workflow-start event retains top-level workflow `input_data` for resume. Do **not** submit the inline payload as top-level workflow-start input expecting it to be private. Caller-owned capture outputs, resolved node input, script stdout/logs, checkpoint/resume storage and retention must be qualified separately before real input is used. Neither a preparation stage nor this explicit node wiring proves non-persistence: **no end-to-end private-image path has been verified here**. This feature does not change those stored-data contracts.

## Restrictions and error behavior

- `provider: anthropic`, an existing `token` label and explicit `tools: []` are mandatory. Invalid input/config fails before provider resolution or credential/request preparation.
- The resolved provider must be the existing native Anthropic OAuth implementation. Unknown token, API-key auth, unavailable subscription/model or auth refusal fails closed. There is no paid-key, CLI, account-rotation or provider fallback.
- `fallback`, provider/auth/tool/CLI/allowance overrides and loop context/compression settings are refused rather than silently ignored. An explicit `max_iterations` must be `1`. Memory calls must be disabled.
- `provider_config`, when used, is closed to `max_tokens`, `temperature`, `effort`, `thinking` and `thinking_budget`. Conflicting top-level/native output settings, conflicting thinking settings and non-native keys are refused. Native thinking/effort belongs in `provider_config`, not an ignored top-level field. Model/default `max_tokens` and the configured/default total timeout retain their ordinary meanings; this is not a new call/spend/runtime quota system.
- `temperature` is sent only when the agent sets it (top level or in `provider_config`); the provider's default is never added. Opus 5 and Sonnet 5 models refuse any `temperature` (HTTP 400, and this mode never resends), so leave it unset for them.
- No tool schemas, executor, compressor, MCP/plugin or delegation surface is constructed. Tools already present in the surrounding execution context are used only for the existing `LLM_CALL` policy check and usage tracking, never exposed/executed by the model. Existing node policy skips retain their normal semantics.
- Transport uses the existing `SingleSendControl`: one request-start hook, no SDK/HTTP retry, no redirect following, owned transport cleanup and cancellation/deadline checks. Its existing five-second cleanup margin is retained. A network failure is not evidence that the provider did no work.
- Native SSE is buffered through `complete`; **live token callbacks are not supported** in this mode. A context stream callback does not select a different transport or receive partial text.
- Tool-use, nonterminal/partial output, truncation, refusal, quota/auth failure, interruption, empty answer or an invalid attempted JSON answer fails. No allowance park/resend, repair library, JSON re-ask, output-limit retry or second provider send occurs. A valid whole JSON object/list is parsed locally; only an object populates the ordinary `structured_output` mapping. Plain text remains plain text.
- Terminal agent/LLM events contain mode, attachment dimensions/byte count, actual transmission count, cleanup status and safe usage/error metadata, not content. Logs within the operation use the existing metadata-only Python logging scope. This is not protection against a separate earlier logging exporter, arbitrary same-process code or upstream workflow storage.
- Usage fields that the provider does not report stay `null` in metadata/events. The ordinary aggregate token total may be the sum of reported input/output counters, and the cost is the existing **list-price estimate**, not subscription billing. No missing cache, timing, model-allocation or historical-cost facts are invented. A zero legacy aggregate with unknown usage is not proof of zero consumption.
- Usage never costs the answer. Usage fields the pinned SDK does not model (Anthropic adds them over time) leave the answer and the modelled counters as they are, and are recorded on the call's terminal LLM and agent events as `usage_fault` `{"reason": "unmodelled", "unmodelled": {place: {field: value}}}`. A value is kept only when it is null, a boolean, a number or a string of at most 64 characters; an object, an array or a longer string is recorded as `{"type": ..., "length": ...}` alone, since nobody knows what such a field holds. Only a count per place is kept when the record passes 4 KB or is not storable JSON. A usage that cannot be read (missing, not an object, a counter that is not a whole number of zero or more, or a null input/output counter) makes every counter `null`, never `0`, with `{"reason": "unreadable", "unreadable": [what]}`; no usage at all is `{"reason": "absent"}`. A call with no counters is also counted as `usage-missing` in the usage rows.

A workflow may intentionally invoke the node again on a later execution; at-most-one-send applies to **this invocation**, not a deduplication service across deliberate workflow retries/resumes.

## What is proven

The dedicated offline tests use fixed synthetic PNGs, the real opt-in agent/native provider path, a fake named OAuth credential and a counting HTTP transport. They check attachment structure in-process using metadata/boolean assertions, one initiated send, refused unsafe configurations/input, cancellation/cleanup, policy veto, safe projections and preserved legacy behavior. They make **no real model call** and inspect no real image or credential.

These tests prove the local mapping/refusal behavior, **not** live model/account acceptance, quality, entitlement, permission for arbitrary sites, or qualification of a real evaluation workflow. A real caller must have ordinary authority for its intended inputs and workflow, retain any applicable storage/privacy approvals, and explicitly authorise its model/account dispatch. Deliberately supplied public image/text does not require an additional Security gate merely because it is real. Private-image storage and end-to-end confidentiality remain unverified. This code example grants none of those permissions.
