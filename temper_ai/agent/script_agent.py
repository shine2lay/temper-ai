"""Script agent — executes a Jinja-rendered bash script.

No LLM calls. Renders a script template with input_data,
executes via tool_executor (Bash tool), returns stdout as output.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
import sys
import tempfile
import time
from collections.abc import Mapping
from typing import Any

from jinja2 import BaseLoader, StrictUndefined, Undefined, UndefinedError
from jinja2.sandbox import SandboxedEnvironment

from temper_ai.agent.base import AgentABC
from temper_ai.agent.exceptions import ScriptRenderError
from temper_ai.agent.script_log import ScriptLog, log_limit
from temper_ai.observability import EventType
from temper_ai.observability import record as _default_record
from temper_ai.shared.types import AgentResult, ExecutionContext, Status


def _run_key_env(context: ExecutionContext) -> dict[str, str]:
    """TEMPER_RUN_TOKEN for a run that holds its own key (``starts_runs: true``), else nothing.

    Only script steps get it: an agent's own tools build their environment
    without it (shared/agent_env.py), so a model never holds it.
    """
    from temper_ai.api.run_tokens import ENV_NAME, held

    key = held(getattr(context, "run_id", None))
    return {ENV_NAME: key} if key else {}


logger = logging.getLogger(__name__)

#: How long a script may run when its config does not say (``timeout_seconds``).
DEFAULT_TIMEOUT_SECONDS = 30


def declared_timeout_seconds(config: Mapping[str, Any]) -> float:
    """The agent's ``timeout_seconds``, or 30: how long its script runs before it is killed.

    Honoured as declared, with no ceiling: the Bash kill and the executor's wait both take it in
    full (tools/bash.py time_limit). Any finite number of seconds above 0; anything else raises
    ValueError naming the setting, where it used to kill the script at once or end in a TypeError.
    """
    raw = config.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS)
    if isinstance(raw, bool) or not isinstance(raw, (int, float)) or not math.isfinite(raw) or raw <= 0:
        raise ValueError(f"script agent '{config.get('name')}': timeout_seconds must be a finite "
                         f"number of seconds above 0 (got {raw!r})")
    return raw


#: One `{{ ... }}` interpolation. Quoted strings inside the expression are consumed whole so a `}}`
#: within one (`{{ x | default("}}") }}`) does not end the match early.
_INTERP = re.compile(r"\{\{((?:[^'\"}]|'[^']*'|\"[^\"]*\"|\}(?!\}))*)\}\}")
#: Jinja statements and comments emit no shell text, so they must not affect the quote scan
#: (`{% if x == "a" %}` would otherwise look like an opening double quote).
_JINJA_STMT = re.compile(r"\{%.*?%\}|\{#.*?#\}", re.DOTALL)
_JINJA_COMMENT = re.compile(r"\{#.*?#\}", re.DOTALL)
_JINJA_TAG = re.compile(
    r"\{\{((?:[^'\"}]|'[^']*'|\"[^\"]*\"|\}(?!\}))*)\}\}"
    r"|\{%((?:[^'\"}%]|'[^']*'|\"[^\"]*\"|%(?!\}))*?)%\}",
    re.DOTALL,
)
_STRING_LITERAL = re.compile(r"'[^']*'|\"[^\"]*\"")

BARE_FILTER = "_temper_env_bare"
QUOTED_FILTER = "_temper_env_quoted"
PUBLIC_QUOTED_FILTER = "quoted"
ENV_FILTER = "env"
FILE_FILTER = "file"
FILE_BARE_FILTER = "_temper_file_bare"

_FILE_FILTER_IN_TAG = re.compile(
    rf"\|\s*(?:{re.escape(FILE_FILTER)}|{re.escape(FILE_BARE_FILTER)})(?!\w)"
)
_SET_ASSIGN_PREFIX = re.compile(r"^-?\s*set\s+[A-Za-z_][A-Za-z0-9_]*\s*=\s*")

#: Linux MAX_ARG_STRLEN (PAGE_SIZE * 32 = 131072 bytes): the kernel's per-string ceiling
#: for execve() argv/envp entries. Anything larger fails execve with E2BIG (Errno 7).
ENV_MAX_BYTES = 131_072

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
        if _ends_with_file_filter(expr):
            # The author asked for a staged file path (`{{ x | file }}`). When the template
            # already wraps the interpolation in quotes (`"{{ x | file }}"` or `'{{ x | file }}'`),
            # emit the raw path inside those quotes; otherwise emit a single-quoted shell-safe path.
            before_ch = template[m.start() - 1] if m.start() > 0 else ""
            after_ch = template[m.end()] if m.end() < len(template) else ""
            if before_ch in ('"', "'") and after_ch == before_ch:
                bare_expr = re.sub(r"\|\s*" + FILE_FILTER + r"\s*$", "| " + FILE_BARE_FILTER, expr)
                out.append("{{ " + bare_expr + " }}")
            else:
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
        if _ends_with_quoted_filter(expr):
            expr = re.sub(r"\|\s*" + PUBLIC_QUOTED_FILTER + r"\s*$", "", expr).strip()
        filt = BARE_FILTER if state in ('"', HEREDOC_EXPANDS) else QUOTED_FILTER
        out.append("{{ (" + expr + ") | " + filt + " }}")
        pos = m.end()
    out.append(template[pos:])
    return "".join(out)


def _ends_with_env_filter(expr: str) -> bool:
    """`{{ x | env }}`, `{{ x | default('') | env }}`: the last filter is `env`, no arguments."""
    return re.search(r"\|\s*" + ENV_FILTER + r"\s*$", expr) is not None


def _ends_with_file_filter(expr: str) -> bool:
    """`{{ x | file }}`, `{{ x | default('') | file }}`: the last filter is `file`, no arguments."""
    return re.search(r"\|\s*" + FILE_FILTER + r"\s*$", expr) is not None


def _ends_with_quoted_filter(expr: str) -> bool:
    """`{{ x | quoted }}`, `{{ x | default('') | quoted }}`: the last filter is `quoted`, no arguments."""
    return re.search(r"\|\s*" + PUBLIC_QUOTED_FILTER + r"\s*$", expr) is not None


def _extract_file_exprs(template: str) -> list[str]:
    """Return the expressions piped to ``| file`` across ``{{ ... }}`` and ``{% ... %}`` tags."""
    exprs: list[str] = []
    uncommented = _JINJA_COMMENT.sub("", template)
    for match in _JINJA_TAG.finditer(uncommented):
        body = match.group(1) if match.group(1) is not None else match.group(2)
        if body is None:
            continue
        scrubbed = _STRING_LITERAL.sub(lambda m: " " * len(m.group(0)), body)
        filter_match = _FILE_FILTER_IN_TAG.search(scrubbed)
        if filter_match is None:
            continue
        before_file = body[: filter_match.start()]
        if match.group(2) is not None:
            before_file = _SET_ASSIGN_PREFIX.sub("", before_file)
        cleaned = before_file.lstrip("-").strip().lstrip("(").strip()
        exprs.append(cleaned or "input")
    return exprs


def _file_filter_refused_message(agent_name: str, expr: str) -> str:
    """Authoring error message when ``| file`` is used in a P3-protected script launch."""
    return (
        f"script for '{agent_name}' cannot use '{{{{ {expr} | {FILE_FILTER} }}}}' "
        f"in a P3-protected launch; use | env or | quoted instead."
    )


def _shell_quote_path(path: str) -> str:
    """Wrap a path in single quotes so spaces and shell metacharacters are inert."""
    return "'" + path.replace("'", "'\"'\"'") + "'"


class _ValueStash:
    """Collects rendered values into environment variables (or staged 0600 files) and emits a reference.

    This is the whole defence. `shlex.quote` protected a value only where the template author had
    not added quotes of their own: `echo {{ x }}` was safe, `echo "{{ x }}"` executed `$(...)` and
    `echo '{{ x }}'` executed anything at all, because quoting an already-quoted string cancels it.
    Both are the natural way to write a template, and 33 of 69 sites in this repo are written that
    way. Escaping is the wrong tool: it tries to make data survive being parsed as code. Here the
    value never appears in the script text, so there is nothing to parse — the shell reads it from
    the environment, where a `$(...)` is seven characters and not an instruction.

    Whether the reference needs quotes of its own depends on where it lands, which is why
    `_rewrite_interpolations` picks the filter per site rather than this deciding for every site.
    For values over Linux's 131,072-byte per-string environment limit (`MAX_ARG_STRLEN`), `| file`
    writes the value to a `0600` file in the run workspace (or a private `0700` temp directory per
    attempt when there is no workspace) and renders its shell-safe path.
    """

    PREFIX = "TEMPER_V"

    def __init__(
        self,
        *,
        agent_name: str = "script",
        workspace_path: str | None = None,
        inputs: Mapping[str, Any] | None = None,
        expressions: list[str] | None = None,
        file_expressions: list[str] | None = None,
    ) -> None:
        self.env: dict[str, str] = {}
        self.files: list[str] = []
        self.agent_name = agent_name or "script"
        self.workspace_path = (
            workspace_path.strip()
            if isinstance(workspace_path, str) and workspace_path.strip()
            else None
        )
        self._inputs: dict[str, Any] = dict(inputs) if inputs else {}
        self._expressions: list[str] = list(expressions) if expressions else []
        self._file_expressions: list[str] = list(file_expressions) if file_expressions else []
        self._expr_index = 0
        self._file_expr_index = 0
        self._file_count = 0
        self._temp_dir: str | None = None

    @staticmethod
    def _serialize(value: Any) -> str:
        """Serialize a value for `| env` or `| file`: strings as-is, None as empty, others as JSON."""
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        return json.dumps(value)

    def _label_for(self, expr_idx: int, value: Any, text: str) -> tuple[str, str]:
        raw_expr = self._expressions[expr_idx] if 0 <= expr_idx < len(self._expressions) else ""
        base_expr = re.sub(
            r"\|\s*(?:" + ENV_FILTER + "|" + PUBLIC_QUOTED_FILTER + r")\s*$",
            "",
            raw_expr,
        ).strip()
        ident_match = re.match(r"^([A-Za-z_][A-Za-z0-9_]*)", base_expr)
        expr_ident = ident_match.group(1) if ident_match else ""

        input_key = ""
        if expr_ident and expr_ident in self._inputs:
            input_key = expr_ident
        else:
            for k, v in self._inputs.items():
                if k in ("workspace_path", "run_id") or isinstance(v, Undefined):
                    continue
                if v is value or self._serialize(v) == text:
                    input_key = k
                    break

        label = input_key or expr_ident or base_expr or f"{self.PREFIX}{len(self.env) + 1}"
        fix_expr = base_expr or input_key or "value"
        return label, fix_expr

    def _stash(self, value: Any) -> str | None:
        """Store the value, return its variable name — or None for an undefined, so the configured
        undefined policy (record blank, or raise) still decides what happens.

        A value that is there but empty (None: an input the run did not give, a field a step
        did not fill) is stored as empty text, never as the word "None" a script would take for
        real text: a path named None, a repository called None. strict_undefined is not about
        these: it still fails only a name that does not exist."""
        expr_idx = self._expr_index
        self._expr_index += 1
        if isinstance(value, Undefined):
            str(value)
            return None
        text = self._serialize(value)
        nbytes = len(text.encode("utf-8"))
        name = f"{self.PREFIX}{len(self.env) + 1}"
        if nbytes > ENV_MAX_BYTES:
            label, fix_expr = self._label_for(expr_idx, value, text)
            raise ScriptRenderError(
                f"script for '{self.agent_name}' passed {nbytes} bytes for '{label}' via "
                f"environment variable {name}, over the {ENV_MAX_BYTES}-byte limit. "
                f"Pass large values through a file instead: '{{{{ {fix_expr} | {FILE_FILTER} }}}}'."
            )
        self.env[name] = text
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

    def _target_dir(self) -> str:
        if self.workspace_path and os.path.isdir(self.workspace_path):
            return self.workspace_path
        if self._temp_dir is None:
            self._temp_dir = tempfile.mkdtemp(prefix="temper-script-")
            os.chmod(self._temp_dir, 0o700)
        return self._temp_dir

    def _write_file(self, value: Any) -> str:
        self._expr_index += 1
        if isinstance(value, Undefined):
            str(value)
            text = ""
        else:
            text = self._serialize(value)
        self._file_count += 1
        target_dir = self._target_dir()
        fd, path = tempfile.mkstemp(
            prefix=f".temper_v{self._file_count}_",
            dir=target_dir,
        )
        try:
            os.fchmod(fd, 0o600)
            data = text.encode("utf-8")
            view = memoryview(data)
            while view:
                written = os.write(fd, view)
                view = view[written:]
        finally:
            os.close(fd)
        self.files.append(path)
        return path

    def file(self, value: Any) -> str:
        """`{{ x | file }}`: write the value to a 0600 file and return its quoted shell-safe path."""
        return _shell_quote_path(self._write_file(value))

    def file_bare(self, value: Any) -> str:
        """For `\"{{ x | file }}\"` or `'{{ x | file }}'` where the template already supplies quotes."""
        return self._write_file(value)

    def first_file_expr(self) -> str:
        """Return the first template expression piped to ``| file`` without inspecting values."""
        if self._file_expressions:
            return self._file_expressions[0]
        for k in self._inputs:
            if k not in ("workspace_path", "run_id"):
                return k
        return "input"

    def _next_file_expr(self) -> str:
        idx = self._file_expr_index
        self._file_expr_index += 1
        if 0 <= idx < len(self._file_expressions):
            return self._file_expressions[idx]
        return self.first_file_expr()

    def refuse_file(self, _value: Any) -> str:
        """Refuse ``| file`` in a P3-protected launch before any file is written."""
        raise ScriptRenderError(
            _file_filter_refused_message(self.agent_name, self._next_file_expr())
        )

    def register_filters(
        self, env: SandboxedEnvironment, *, p3_protected: bool = False
    ) -> None:
        """Register script interpolation filters, refusing ``| file`` when P3-protected."""
        env.filters[QUOTED_FILTER] = self.quoted
        env.filters[PUBLIC_QUOTED_FILTER] = self.quoted
        env.filters[BARE_FILTER] = self.bare
        env.filters[ENV_FILTER] = self.name
        if p3_protected:
            env.filters[FILE_FILTER] = self.refuse_file
            env.filters[FILE_BARE_FILTER] = self.refuse_file
        else:
            env.filters[FILE_FILTER] = self.file
            env.filters[FILE_BARE_FILTER] = self.file_bare

    def cleanup(self) -> None:
        """Remove the per-attempt 0700 fallback directory when no workspace was set."""
        if self._temp_dir is not None:
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            self._temp_dir = None


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
        2. Execute via context.tool_executor (Bash tool with workspace + timeout), saving what the
           script prints to this attempt's log as it arrives (agent/script_log.py)
        3. Return AgentResult with stdout as output; the log's figures go on the completion
           event beside it, never into it
        """
        from copy import deepcopy

        from temper_ai.agent.admission_use import hooks_for
        admission = hooks_for(context, self)
        checked_vars = None
        checked_template = None
        if admission is not None:
            # Complete final variables, BEFORE input/event logging or rewriting.
            variables = dict(input_data)
            if context.workspace_path and not variables.get("workspace_path"):
                variables["workspace_path"] = context.workspace_path
            if context.run_id and not variables.get("run_id"):
                variables["run_id"] = str(context.run_id)
            checked_template = self.config.get("script_template")
            checked_vars = admission.script_inputs(self, context, checked_template, variables)
            # An owned metadata-only copy also reaches the event sink.
            input_data = deepcopy({k: checked_vars[k] for k in input_data})
        start = time.monotonic()
        _record = context.event_recorder.record if context.event_recorder else _default_record
        agent_event_id = self._record_script_started(_record, input_data, context)

        undefined_refs: list[str] = []
        render_vars = dict(input_data)
        if context.workspace_path and not render_vars.get("workspace_path"):
            render_vars["workspace_path"] = context.workspace_path
        if context.run_id and not render_vars.get("run_id"):
            render_vars["run_id"] = str(context.run_id)
        if checked_vars is not None:
            render_vars = checked_vars
        workspace = render_vars.get("workspace_path")
        raw_template = checked_template if checked_template is not None else self.config["script_template"]
        from temper_ai.agent.admission_use import _declared_attribute

        p3_adapter = _declared_attribute(context, "p3_launch_adapter") or self.config.get(
            "p3_launch_adapter"
        )
        p3_protected = bool(
            _declared_attribute(context, "p3_protected_launch", False)
            or self.config.get("p3_protected_launch", False)
        )
        is_p3_protected = p3_protected or p3_adapter is not None
        env_exprs = [
            m.group(1).strip()
            for m in _INTERP.finditer(raw_template)
            if not _ends_with_file_filter(m.group(1).strip())
        ]
        file_exprs = _extract_file_exprs(raw_template)
        stash = _ValueStash(
            agent_name=self.name,
            workspace_path=workspace if isinstance(workspace, str) and workspace.strip() else None,
            inputs=render_vars,
            expressions=env_exprs,
            file_expressions=file_exprs,
        )
        log: ScriptLog | None = None
        try:
            template_text = _rewrite_interpolations(raw_template, self.name)
            env = SandboxedEnvironment(
                loader=BaseLoader(),
                undefined=StrictUndefined if self.strict_undefined else _recording_undefined(undefined_refs),
            )
            stash.register_filters(env, p3_protected=is_p3_protected)
            template = env.from_string(template_text)
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

            timeout = declared_timeout_seconds(self.config)
            # `env` carries the interpolated values; `command` carries only the author's script.
            # TEMPER_PYTHON is the interpreter temper itself runs on, with its
            # dependencies (PyYAML among them); the image's `python3` has none.
            # `_raw_output`: the output is read by code (its JSON is the structured output), so
            # it is not compacted for a model's context the way a model's own calls are.
            params: dict[str, Any] = {
                "command": script, "_skip_allowlist": True, "_raw_output": True, "timeout": timeout,
                "env": {**stash.env, "TEMPER_PYTHON": sys.executable, **_run_key_env(context)},
            }
            if is_p3_protected:
                if stash.files:
                    raise ScriptRenderError(
                        _file_filter_refused_message(self.name, stash.first_file_expr())
                    )
                from temper_ai.p3_authority.contract import Refusal
                from temper_ai.p3_authority.launch_adapters import (
                    P3ObservationRefusedError,
                    ScriptLaunchObservationAdapter,
                    refuse_missing_launch_provider,
                )

                if not isinstance(p3_adapter, ScriptLaunchObservationAdapter):
                    raise P3ObservationRefusedError(
                        refuse_missing_launch_provider(boundary="C_PRE_EXECUTION")
                    )
                prep_res = p3_adapter.prepare_bash_kwargs(
                    agent_name=self.name,
                    run_id=str(context.run_id) if context.run_id else "",
                    base_kwargs=params,
                )
                if isinstance(prep_res, Refusal):
                    raise P3ObservationRefusedError(prep_res)
                params = prep_res.data
            # The attempt's log: what the script prints, saved and sent to the dashboard while it
            # runs (agent/script_log.py). Only its output goes in it, never the script or its env.
            log = self._open_log(agent_event_id, context)
            if log is not None:
                params["_output_sink"] = log.write
            tool_result = context.tool_executor.execute(
                "Bash",
                params,
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

            # The log ends (saved to its last row, with how the attempt ended) before the agent's
            # completion is recorded, so a viewer who sees the agent done finds its log whole.
            log_summary = _close_log(log, tool_result, timeout)
            duration = round(time.monotonic() - start, 3)
            status = Status.COMPLETED if tool_result.success else Status.FAILED
            output = str(tool_result.result) if tool_result.result else ""
            self._record_script_completed(
                tool_result, output, duration, agent_event_id, context, status,
                undefined_refs=sorted(set(undefined_refs)), log_summary=log_summary,
            )

            # Extract structured output from script's JSON output (if any)
            structured = _extract_json(output)
            if structured is None and output.lstrip().startswith("{"):
                # Every node that reads this one's fields would see "no structured output": say why here.
                logger.warning(
                    "Script agent '%s' printed JSON that does not parse (%d chars): its structured "
                    "output is empty", self.name, len(output),
                )

            return AgentResult(
                status=status,
                output=output,
                structured_output=structured,
                error=tool_result.error,
                duration_seconds=duration,
            )

        except Exception as e:  # noqa: BLE001
            log_summary = None
            if log is not None:
                log.close("failed", detail=f"{type(e).__name__}: {e}")
                log_summary = log.summary()
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
                    **({"log": log_summary} if log_summary else {}),
                },
            )
            return AgentResult(
                status=Status.FAILED,
                output="",
                error=str(e),
                duration_seconds=duration,
            )
        finally:
            stash.cleanup()

    def _open_log(self, attempt_id: Any, context: ExecutionContext) -> ScriptLog | None:
        """This attempt's log, saved under its agent.started event's id; None without one."""
        if not isinstance(attempt_id, str) or not attempt_id:
            return None
        limit = log_limit(self.config)
        recorder = context.event_recorder
        run_id = context.run_id
        if recorder is not None:
            def writer(rows: list[tuple[int, dict]]) -> None:
                recorder.record_script_log_rows(attempt_id, rows, execution_id=run_id)
        else:
            from temper_ai.observability.script_logs import save_script_log_rows

            def writer(rows: list[tuple[int, dict]]) -> None:
                save_script_log_rows(run_id, attempt_id, rows)
        return ScriptLog(attempt_id, writer, limit_bytes=limit)

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
                        "timeout_seconds": self.config.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS),
                        **({"log_max_bytes": self.config["log_max_bytes"]}
                           if "log_max_bytes" in self.config else {}),
                    }
                },
            },
        )

    def _record_script_completed(self, tool_result, output: str, duration: float,
                                 agent_event_id: str, context: ExecutionContext, status,
                                 undefined_refs: list[str] | None = None,
                                 log_summary: dict | None = None) -> None:
        """Emit AGENT_COMPLETED or AGENT_FAILED event after script execution."""
        _record = context.event_recorder.record if context.event_recorder else _default_record
        structured = _extract_json(output)
        unparsed = structured is None and output.lstrip().startswith("{")
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
                **({"structured_output_error": f"the script printed JSON that does not parse "
                                               f"({len(output)} chars)"} if unparsed else {}),
                "duration_seconds": duration,
                "error": tool_result.error,
                **({"undefined_refs": undefined_refs} if undefined_refs else {}),
                # What the attempt's log holds (sizes, limit, whether it is whole): beside the
                # output, never in it or in the structured output a next node reads.
                **({"log": log_summary} if log_summary else {}),
            },
        )

    def validate_config(self) -> list[str]:
        errors = super().validate_config()
        template = self.config.get("script_template")
        if not template:
            errors.append("ScriptAgent requires 'script_template' in config")
        elif isinstance(template, str) and (
            bool(self.config.get("p3_protected_launch", False))
            or self.config.get("p3_launch_adapter") is not None
        ):
            file_exprs = _extract_file_exprs(template)
            if file_exprs:
                errors.append(_file_filter_refused_message(self.name, file_exprs[0]))
        for check in (log_limit, declared_timeout_seconds):
            try:
                check(self.config)
            except ValueError as exc:
                errors.append(str(exc))
        return errors


def _close_log(log: ScriptLog | None, tool_result: Any, timeout: Any) -> dict | None:
    """End the attempt's log with how the script ended, and say what it holds."""
    if log is None:
        return None
    meta = getattr(tool_result, "metadata", None) or {}
    error = str(getattr(tool_result, "error", "") or "")
    stopped = meta.get("stopped")
    if tool_result.success:
        log.close("completed", exit_code=0)
    elif stopped == "timeout" or (stopped is None and error.startswith("Tool 'Bash' timed out")):
        log.close("timed_out", detail=f"after {timeout}s")
    elif stopped == "cancelled" or error.startswith("Cancelled:"):
        log.close("cancelled")
    elif isinstance(meta.get("exit_code"), int):
        log.close("failed", exit_code=meta["exit_code"])
    else:
        log.close("failed", detail=error)
    return log.summary()


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
