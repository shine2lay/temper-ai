"""Script agent — executes a Jinja-rendered bash script.

No LLM calls. Renders a script template with input_data,
executes via tool_executor (Bash tool), returns stdout as output.
"""

from __future__ import annotations

import json
import logging
import re
import sys
import time
from typing import Any

from jinja2 import BaseLoader, StrictUndefined, Undefined, UndefinedError
from jinja2.sandbox import SandboxedEnvironment

from temper_ai.agent.base import AgentABC
from temper_ai.agent.exceptions import ScriptRenderError
from temper_ai.observability import EventType
from temper_ai.observability import record as _default_record
from temper_ai.shared.types import AgentResult, ExecutionContext, Status

logger = logging.getLogger(__name__)


#: One `{{ ... }}` interpolation. Quoted strings inside the expression are consumed whole so a `}}`
#: within one (`{{ x | default("}}") }}`) does not end the match early.
_INTERP = re.compile(r"\{\{((?:[^'\"}]|'[^']*'|\"[^\"]*\"|\}(?!\}))*)\}\}")
#: Jinja statements and comments emit no shell text, so they must not affect the quote scan
#: (`{% if x == "a" %}` would otherwise look like an opening double quote).
_JINJA_STMT = re.compile(r"\{%.*?%\}|\{#.*?#\}", re.DOTALL)

BARE_FILTER = "_temper_env_bare"
QUOTED_FILTER = "_temper_env_quoted"
ENV_FILTER = "env"

#: `<<EOF`, `<<-EOF`, `<<'EOF'`, `<<"EOF"`, `<<\EOF` -- but not `<<<` (a here-string, which is a word
#: and expands like one). Group 1 is the quoting, group 2 the delimiter.
_HEREDOC = re.compile(r"<<-?[ \t]*(?!<)(['\"\\]?)(\w+)['\"]?")

#: The quote states. The two heredoc states are named by what the shell does inside them: an
#: unquoted body expands `$VAR` the way double quotes do; a quoted body (`<<'EOF'`) expands nothing,
#: the way single quotes do. A heredoc's delimiter closes it, on a line of its own.
HEREDOC_EXPANDS = "heredoc"
HEREDOC_LITERAL = "heredoc-literal"


def _quote_state_after(
    text: str, state: str | None, at_word_start: bool = True, delimiter: str = "",
) -> tuple[str | None, bool, str]:
    """Track shell quoting through literal script text: the open quote, the word position, and the
    delimiter of the heredoc that is open, if one is.

    Counting quote characters is not enough, because three common things are not quotes at all:

        # this script's purpose      an apostrophe in a comment
        echo "it's fine"             an apostrophe inside double quotes
        echo don\'t                  a backslash-escaped quote

    Reading the first as an open quote would refuse a template that is perfectly safe — which it did,
    for `spec_gate` and two others, until this scanner learned the difference.

    And a heredoc body is not shell text at all: it is data, until the delimiter line. Whether the
    shell expands `$VAR` in it is decided by the delimiter's quoting (`<<EOF` yes, `<<'EOF'` no), so
    that is what the state records. Without this, `python3 - <<'PYEOF'` read as Python code with an
    apostrophe here and there, and a value interpolated in it was passed as the reference `$TEMPER_V1`
    -- which Python, of course, took as a string. task_gate judged "temper_v" against "approve" for
    a whole afternoon, requesting changes on every build.
    """
    text = _JINJA_STMT.sub("", text)
    i = 0
    while i < len(text):
        if state in (HEREDOC_EXPANDS, HEREDOC_LITERAL):
            # Data until a line that is exactly the delimiter (leading tabs allowed, as `<<-` does).
            nl = text.find("\n", i)
            line = text[i:] if nl == -1 else text[i:nl]
            if line.lstrip("\t").rstrip(" \t\r") == delimiter:
                state, delimiter, at_word_start = None, "", True
            if nl == -1:
                return state, True, delimiter
            i = nl + 1
            continue
        ch = text[i]
        if state != "'" and ch == "\\":
            i += 2  # a backslash escapes the next character everywhere except inside single quotes
            continue
        if state is None and ch == "#" and at_word_start:
            nl = text.find("\n", i)
            if nl == -1:
                return state, True, delimiter
            i = nl + 1
            at_word_start = True
            continue
        if state is None and ch == "<" and (m := _HEREDOC.match(text, i)):
            # The body starts on the next line; the rest of this line is still shell.
            pending = (HEREDOC_LITERAL if m.group(1) else HEREDOC_EXPANDS, m.group(2))
            nl = text.find("\n", m.end())
            if nl == -1:
                return pending[0], True, pending[1]
            tail_state, _, _ = _quote_state_after(text[m.end():nl], None, False)
            if tail_state is None:
                state, delimiter = pending
                i = nl + 1
                at_word_start = True
                continue
            i = m.end()  # a quote opened after the operator: let the ordinary scan handle the line
            continue
        if state is None and ch in "\"'":
            state = ch
        elif state == ch:
            state = None
        at_word_start = ch.isspace() or (state is None and ch in ";|&()")
        i += 1
    return state, at_word_start, delimiter


def _rewrite_interpolations(template: str, agent_name: str) -> str:
    """Route every interpolation through a filter chosen by its quoting context.

    The emitted reference has to suit where it lands, and the renderer cannot see that — by the time a
    value is rendered, the surrounding text is gone. So the context is decided here, on the source:

        echo {{ x }}      →  echo "$TEMPER_V1"    quotes needed, or the shell splits the value apart
        echo "{{ x }}"    →  echo "$TEMPER_V1"    already inside quotes; adding more would *end* them

    That second line is the one that bites: `""$V""` is two empty strings with the variable bare in
    between, so `line one\nline two` arrives as `lineonelinetwo`. Safe, but quietly wrong, which is
    worse to debug than an error.
    """
    out: list[str] = []
    pos = 0
    state: str | None = None
    at_word_start = True
    delimiter = ""
    for m in _INTERP.finditer(template):
        literal = template[pos:m.start()]
        state, at_word_start, delimiter = _quote_state_after(literal, state, at_word_start, delimiter)
        expr = m.group(1).strip()
        out.append(literal)
        if _ends_with_env_filter(expr):
            # The author asked for the variable's *name*, to read the value from the environment
            # themselves. That works in every context, including the two the shell cannot expand.
            out.append("{{ " + expr + " }}")
            pos = m.end()
            continue
        if state == "'":
            raise ScriptRenderError(
                f"script for '{agent_name}' interpolates inside single quotes: {m.group(0).strip()!r}. "
                f"A shell expands nothing there, so the value cannot be passed — the script would "
                f"receive the variable's name as text. Remove the surrounding single quotes; the "
                f"value is quoted for you."
            )
        if state == HEREDOC_LITERAL:
            raise ScriptRenderError(
                f"script for '{agent_name}' interpolates inside a quoted heredoc (<<'{delimiter}'): "
                f"{m.group(0).strip()!r}. A shell expands nothing there, so the value cannot be "
                f"passed — the script would receive the reference $TEMPER_Vn as text. Either pass "
                f"it on the command line (`python3 - {{{{ x }}}} <<'{delimiter}'`, then sys.argv), "
                f"or read it from the environment by name: os.environ[\"{{{{ x | env }}}}\"]."
            )
        filt = BARE_FILTER if state in ('"', HEREDOC_EXPANDS) else QUOTED_FILTER
        out.append("{{ (" + expr + ") | " + filt + " }}")
        pos = m.end()
    out.append(template[pos:])
    return "".join(out)


def _ends_with_env_filter(expr: str) -> bool:
    """`{{ x | env }}`, `{{ x | default('') | env }}`: the last filter is `env`, no arguments."""
    return re.search(r"\|\s*" + ENV_FILTER + r"\s*$", expr) is not None


class _ValueStash:
    """Collects every rendered value into environment variables and emits a reference in its place.

    This is the whole defence. `shlex.quote` protected a value only where the template author had
    not added quotes of their own: `echo {{ x }}` was safe, `echo "{{ x }}"` executed `$(...)` and
    `echo '{{ x }}'` executed anything at all, because quoting an already-quoted string cancels it.
    Both are the natural way to write a template, and 33 of 69 sites in this repo are written that
    way. Escaping is the wrong tool: it tries to make data survive being parsed as code. Here the
    value never appears in the script text, so there is nothing to parse — the shell reads it from
    the environment, where a `$(...)` is seven characters and not an instruction.

    Whether the reference needs quotes of its own depends on where it lands, which is why
    `_rewrite_interpolations` picks the filter per site rather than this deciding for every site.
    """

    PREFIX = "TEMPER_V"

    def __init__(self) -> None:
        self.env: dict[str, str] = {}

    def _stash(self, value: Any) -> str | None:
        """Store the value, return its variable name — or None for an undefined, so the configured
        undefined policy (record blank, or raise) still decides what happens."""
        if isinstance(value, Undefined):
            str(value)
            return None
        name = f"{self.PREFIX}{len(self.env) + 1}"
        self.env[name] = value if isinstance(value, str) else str(value)
        return name

    def quoted(self, value: Any) -> str:
        """For an interpolation in unquoted text: the reference brings its own quotes."""
        name = self._stash(value)
        return f'"${name}"' if name else ""

    def bare(self, value: Any) -> str:
        """For an interpolation already inside double quotes: adding quotes would close them."""
        name = self._stash(value)
        return f"${name}" if name else ""

    def name(self, value: Any) -> str:
        """`{{ x | env }}`: the variable's name, for a script that reads the environment itself.

        This is the way through the two places the shell expands nothing -- single quotes and a
        quoted heredoc -- where a reference would arrive as text: `os.environ["{{ x | env }}"]`
        in a Python heredoc gets the value, whatever it contains. An undefined value renders as
        a name that is not set, so `os.environ.get(...)` sees None and `[...]` raises, as the
        author chose.
        """
        name = self._stash(value)
        return name or f"{self.PREFIX}UNDEFINED"


def _recording_undefined(sink: list[str]) -> type[Undefined]:
    """An Undefined that renders empty — as it always has — but says so afterwards.

    A reference the inputs never supplied renders as nothing, and the script runs anyway: `rm -rf
    {{ worktree }}/build` with no `worktree` is `rm -rf /build`. Until now that left no trace at all.
    Recording the names costs nothing and turns a silent wrong-target into a visible one, which is the
    same bargain the executor already strikes for unresolved `input_map` entries.

    Note that `{{ a.b }}` with `a` undefined raises even here — attribute access on Undefined is an
    error in Jinja itself — so strictness is already half-present; this only covers the flat case.
    """

    class RecordingUndefined(Undefined):
        def __str__(self) -> str:
            if self._undefined_name:
                sink.append(str(self._undefined_name))
            return ""

    return RecordingUndefined


class ScriptAgent(AgentABC):
    """Agent that executes a Jinja-rendered bash script.

    `strict_undefined: true` in the agent config turns an undefined reference into a failed node
    instead of a blank. It is opt-in rather than the default because 82 configs use this agent type
    with 26 distinct bare references between them: flipping the default would fail those nodes at run
    time, deep in a pipeline, after the stages before them had already been paid for. New glue — where
    a blank argument is dangerous — should set it.
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self.strict_undefined = bool(config.get("strict_undefined", False))
        self.env = SandboxedEnvironment(loader=BaseLoader())

    def run(self, input_data: dict, context: ExecutionContext) -> AgentResult:
        """Execute the script agent pipeline.

        1. Render Jinja template from config["script_template"] with input_data
        2. Execute via context.tool_executor (Bash tool with workspace + timeout)
        3. Return AgentResult with stdout as output
        """
        start = time.monotonic()
        _record = context.event_recorder.record if context.event_recorder else _default_record
        agent_event_id = self._record_script_started(_record, input_data, context)

        undefined_refs: list[str] = []
        stash = _ValueStash()
        try:
            template_text = _rewrite_interpolations(self.config["script_template"], self.name)
            env = SandboxedEnvironment(
                loader=BaseLoader(),
                undefined=StrictUndefined if self.strict_undefined else _recording_undefined(undefined_refs),
            )
            env.filters[QUOTED_FILTER] = stash.quoted
            env.filters[BARE_FILTER] = stash.bare
            env.filters[ENV_FILTER] = stash.name
            template = env.from_string(template_text)
            # `{{ workspace_path }}` is the documented way for a script to
            # address the run's workspace, but it only ever resolved when a
            # caller happened to pass it as a workflow input — otherwise it
            # rendered empty and scripts silently wrote to `/`. Provide it
            # from the execution context, without shadowing an explicit input.
            render_vars = dict(input_data)
            if context.workspace_path and not render_vars.get("workspace_path"):
                render_vars["workspace_path"] = context.workspace_path
            # Same for `{{ run_id }}`: scripts that leave a durable record
            # (a claim file, a branch) want to say which run made it.
            if context.run_id and not render_vars.get("run_id"):
                render_vars["run_id"] = str(context.run_id)
            # No escaping here any more: `finalize` moves each value into the environment and writes a
            # reference in its place, so nothing that came from a model is ever parsed as shell code.
            try:
                script = template.render(**render_vars)
            except UndefinedError as exc:
                # Only reachable under strict_undefined; named so the fix is obvious from the run.
                raise ScriptRenderError(
                    f"script for '{self.name}' referenced an undefined value: {exc}. "
                    f"Supply it via input_map, or give the template a `| default(...)`."
                ) from exc
            if undefined_refs:
                # Visible in the log and on the event, the way unresolved input_map entries are:
                # the script ran, so the run can be green and still have done the wrong thing.
                logger.warning(
                    "Script agent '%s' rendered undefined reference(s) as empty: %s",
                    self.name, sorted(set(undefined_refs)),
                )

            timeout = self.config.get("timeout_seconds", 30)
            workspace = render_vars.get("workspace_path")
            tool_result = context.tool_executor.execute(
                "Bash",
                # `env` carries the interpolated values; `command` carries only the author's script.
                # TEMPER_PYTHON is the interpreter temper itself runs on, with its
                # dependencies (PyYAML among them); the image's `python3` has none.
                {"command": script, "_skip_allowlist": True, "timeout": timeout,
                 "env": {**stash.env, "TEMPER_PYTHON": sys.executable}},
                # A script agent runs the script ITS OWN config declares — the
                # command is rendered from the template here, not chosen by a
                # model — so it declares exactly the one tool it uses.
                allowed_tools=("Bash",),
                # … and runs it in the node's workspace when it has one (the
                # same `{{ workspace_path }}` the template sees).
                workspace=workspace if isinstance(workspace, str) and workspace.strip() else None,
                timeout=timeout,
                context={
                    "parent_id": agent_event_id,
                    "execution_id": context.run_id,
                    "skip_policies": context.skip_policies,
                    "agent_name": self.name,
                },
            )

            duration = round(time.monotonic() - start, 3)
            status = Status.COMPLETED if tool_result.success else Status.FAILED
            output = str(tool_result.result) if tool_result.result else ""
            self._record_script_completed(
                tool_result, output, duration, agent_event_id, context, status,
                undefined_refs=sorted(set(undefined_refs)),
            )

            # Extract structured output from script's JSON output (if any)
            structured = _extract_json(output)

            return AgentResult(
                status=status,
                output=output,
                structured_output=structured,
                error=tool_result.error,
                duration_seconds=duration,
            )

        except Exception as e:  # noqa: BLE001
            duration = round(time.monotonic() - start, 3)
            _record(
                EventType.AGENT_FAILED,
                parent_id=agent_event_id,
                execution_id=context.run_id,
                status="failed",
                data={
                    "agent_name": self.name,
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "duration_seconds": duration,
                },
            )
            return AgentResult(
                status=Status.FAILED,
                output="",
                error=str(e),
                duration_seconds=duration,
            )

    def _record_script_started(self, _record, input_data: dict, context: ExecutionContext) -> str:
        """Emit AGENT_STARTED event and return the event id."""
        return _record(
            EventType.AGENT_STARTED,
            parent_id=context.parent_event_id,
            execution_id=context.run_id,
            status="running",
            data={
                "agent_name": self.name,
                "node_path": context.node_path,
                "type": "script",
                "input_data": input_data,
                "agent_config": {
                    "agent": {
                        "type": "script",
                        "name": self.name,
                        "script_template": self.config.get("script_template", "")[:2000],
                        "timeout_seconds": self.config.get("timeout_seconds", 30),
                    }
                },
            },
        )

    def _record_script_completed(self, tool_result, output: str, duration: float,
                                 agent_event_id: str, context: ExecutionContext, status,
                                 undefined_refs: list[str] | None = None) -> None:
        """Emit AGENT_COMPLETED or AGENT_FAILED event after script execution."""
        _record = context.event_recorder.record if context.event_recorder else _default_record
        structured = _extract_json(output)
        _record(
            EventType.AGENT_COMPLETED if tool_result.success else EventType.AGENT_FAILED,
            parent_id=agent_event_id,
            execution_id=context.run_id,
            status=status.value,
            data={
                "agent_name": self.name,
                "output": output[:20000] if output else "",  # Script output is the primary artifact — allow more
                "output_length": len(output),
                "structured_output": structured,
                "has_structured_output": structured is not None,
                "duration_seconds": duration,
                "error": tool_result.error,
                **({"undefined_refs": undefined_refs} if undefined_refs else {}),
            },
        )

    def validate_config(self) -> list[str]:
        errors = super().validate_config()
        if not self.config.get("script_template"):
            errors.append("ScriptAgent requires 'script_template' in config")
        return errors


def _extract_json(text: str) -> dict | None:
    """Extract JSON from script output: the whole of it, else its last JSON line.

    The whole output comes first because a pretty-printed document is the
    obvious way to write one and the line scan mis-reads it: scanning
    backwards, the first *line* that happens to parse wins, so a nested
    one-line object (``{"label": "..."}``) is returned as if it were the
    document. Scripts that print prose and end with a JSON line still take
    the line-scan path below.
    """
    if not text:
        return None
    stripped = text.strip()
    if stripped.startswith("{"):
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    # Scripts typically output JSON as the final line
    for line in reversed(stripped.split("\n")):
        line = line.strip()
        if line.startswith("{"):
            try:
                parsed = json.loads(line)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                continue
    return None
