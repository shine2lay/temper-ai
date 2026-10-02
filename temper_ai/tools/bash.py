"""Bash tool — execute shell commands in a sandboxed environment.

Security:
- Commands run in a subprocess with a clean environment
- workspace_root config constrains the working directory
- Configurable command allowlist (default: common safe commands)
- Timeout enforcement (default 30s, max 600s)
"""

import codecs
import io
import logging
import os
import re
import selectors
import shlex
import signal
import subprocess  # noqa: B404
import time
from collections.abc import Callable
from typing import Any, NamedTuple

from temper_ai.tools._output_compaction import DEFAULT_MAX_CHARS
from temper_ai.tools._output_compaction import compact as compact_output
from temper_ai.tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)

_DEFAULT_ALLOWED_COMMANDS = [
    # File operations
    "ls", "cat", "find", "mkdir", "pwd", "head", "tail", "wc",
    "grep", "sort", "uniq", "diff", "echo", "cp", "mv", "rm",
    "touch", "chmod", "tee",
    # Shell built-ins (used in scripts)
    "set", "export", "source", "cd", "test", "[", "true", "false",
    "read", "printf", "local", "return", "exit",
    # Text processing
    "sed", "awk", "tr", "cut", "xargs",
    # Path utilities
    "basename", "dirname", "realpath", "readlink", "which",
    # Shell built-ins / safe utilities
    "cd", "test", "true", "false", "sleep", "date", "whoami", "env",
    # Dev tools. `python`, `uv`, `pytest`, `ruff` and `make` are how a Python
    # repo runs its own checks (`make test` -> `uv run pytest`); refusing them
    # cost one epd_task implementer 160 `uv` refusals in a single run, and the
    # capmap implementers gave up on testing altogether. They add no power
    # `python3` did not already grant.
    "python3", "python", "pip", "uv", "pytest", "ruff", "make",
    "node", "npm", "npx", "git", "curl",
    # Process control and scratch files, which the same agents reached for
    # (`timeout 120 uv run pytest`, `nohup uv run rollcall serve &`, `wait`).
    "timeout", "nohup", "wait", "mktemp",
]

_DEFAULT_TIMEOUT = 30
_MAX_TIMEOUT = 600
# An author's script -- a script agent, whose command is its config's and never a
# model's (`_skip_allowlist`) -- may run a repository's whole test suite, which
# does not fit in ten minutes. Models keep the 600 s cap: llm_agent strips every
# `_` parameter from a model's calls, so a model cannot claim this one.
_SCRIPT_MAX_TIMEOUT = 3600
_MAX_OUTPUT_SIZE = 256_000  # 256KB
# Compaction (tools/_output_compaction.py) cuts output to about 40,000 characters, for a model's
# context. A script agent's output is read by code instead: its last JSON is the node's structured
# output. So it passes `_raw_output` (a `_` parameter, which a model can never send) and gets the
# whole of it, up to _MAX_OUTPUT_SIZE. Compacted, the EPD plan stage's hand-off (epd_plan_docs, about
# 130,000 characters of JSON on one line) was cut at 40,050 and never parsed, so its lead ran
# without the pitch, the design, the knowledge core or its own draft (2026-09-25).


class Bash(BaseTool):
    """Execute shell commands in a sandboxed subprocess with timeout enforcement."""

    name = "Bash"
    description = "Execute a shell command and return its output."
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The shell command to execute",
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds (default 30, max 600)",
            },
        },
        "required": ["command"],
    }
    modifies_state = True
    # The run's cancel flag, handed over by the ToolExecutor (see
    # ToolExecutor.cancel_event): a command still running when the run is
    # stopped is killed rather than waited out, which for a test suite or a
    # deploy that waits on CI could be half an hour.
    cancellable = True
    cancel_event: Any = None

    def execute(self, **params: Any) -> ToolResult:
        command = params.get("command", "")
        cap = _SCRIPT_MAX_TIMEOUT if params.get("_skip_allowlist", False) else _MAX_TIMEOUT
        timeout = min(params.get("timeout", _DEFAULT_TIMEOUT), cap)

        if not command or not command.strip():
            return ToolResult(success=False, result="", error="Empty command")

        # Check commands against the allowlist
        # Script agents pass _skip_allowlist=True since their scripts are author-defined, not LLM-generated
        skip_allowlist = params.get("_skip_allowlist", False)
        allowed = self.config.get("allowed_commands", _DEFAULT_ALLOWED_COMMANDS)
        if allowed and not skip_allowlist:
            for base_cmd_name in command_heads(command):
                if base_cmd_name not in allowed:
                    return ToolResult(
                        success=False, result="",
                        error=f"Command '{base_cmd_name}' not in allowed list: {allowed}",
                    )

        cwd = self.config.get("workspace_root") or self.config.get("cwd")
        # `_output_sink`: a script agent's live log (agent/script_log.py), handed the output as it
        # arrives. A `_` parameter, like `_raw_output`: llm_agent strips those from a model's calls,
        # so a model's own Bash calls never take the streaming path. It travels with the call, not
        # on this (shared) tool, so two scripts running at once cannot write into each other's log.
        sink = params.get("_output_sink")
        return _run_subprocess(
            command,
            timeout,
            cwd,
            compact=self.config.get("compact_output", True) and not params.get("_raw_output", False),
            max_output_chars=int(self.config.get("max_output_chars") or DEFAULT_MAX_CHARS),
            extra_env=params.get("env") or None,
            cancel_event=self.cancel_event,
            output_sink=sink if callable(sink) else None,
        )


_SHELL_WORDS = frozenset((
    "then", "else", "elif", "fi", "do", "done", "esac", "in", "}", "{", ")", "(", ";;",
    "!", "if", "while", "until", "for", "case", "time",
))
_SEPARATORS = frozenset(("|", "||", "&&", ";", "&", "(", ")", ";;"))
_REDIRECTS = frozenset((">", ">>", "<", "<<", "<<<", ">&", "<&", "&>", ">|"))
_HEREDOC_DELIM = re.compile(r"'([^']*)'|\"([^\"]*)\"|([^\s;|&<>()]+)")


def strip_heredoc_bodies(command: str) -> str:
    """Drop the body of every here-document: it is the command's input, not commands.

    Lexed as commands, a `python3 - <<'EOF'` script was refused for `with`,
    `def` and `f` (an implementer lost 60 iterations to that), and a
    `cat > file <<EOF` was refused for whatever its first word was. Only a
    `<<` outside quotes opens a heredoc (`echo "<<EOF"` does not), so the
    walk tracks quotes; the body runs from the next line to the delimiter
    line (`<<-` lets the shell strip its leading tabs; so does this), or to
    the end when there is none, which is also what the shell does.

    The one thing a body can execute is `$(...)` or a backtick under an
    unquoted delimiter, where the shell expands it. Such a body is kept, so
    the lexer still sees (and the allowlist still judges) whatever it runs.
    """
    if "<<" not in command:
        return command
    out: list[str] = []
    pending: list[tuple[str, bool]] = []  # (delimiter, body may expand) for the next line(s)
    quote: str | None = None
    i, n = 0, len(command)
    while i < n:
        ch = command[i]
        if quote:
            if ch == "\\" and quote == '"' and i + 1 < n:
                out.append(command[i:i + 2])
                i += 2
                continue
            if ch == quote:
                quote = None
            out.append(ch)
            i += 1
            continue
        if ch == "\\" and i + 1 < n:
            out.append(command[i:i + 2])
            i += 2
            continue
        if ch in ("'", '"'):
            quote = ch
            out.append(ch)
            i += 1
            continue
        if command.startswith("<<<", i):  # a here-string: one word of input, no body
            out.append("<<<")
            i += 3
            continue
        if command.startswith("<<", i):
            j = i + 2
            if j < n and command[j] == "-":
                j += 1
            while j < n and command[j] in " \t":
                j += 1
            escaped = j < n and command[j] == "\\"  # `<<\EOF` quotes the delimiter too
            m = _HEREDOC_DELIM.match(command, j + 1 if escaped else j)
            if m:
                quoted = escaped or m.group(3) is None
                pending.append((m.group(1) or m.group(2) or m.group(3), not quoted))
                out.append(command[i:m.end()])
                i = m.end()
                continue
        out.append(ch)
        i += 1
        if ch == "\n" and pending:
            for delim, may_expand in pending:
                body: list[str] = []
                while i < n:
                    k = command.find("\n", i)
                    line = command[i:k] if k != -1 else command[i:]
                    i = k + 1 if k != -1 else n
                    if line.rstrip("\r").lstrip("\t") == delim:
                        break
                    body.append(line)
                if may_expand and any("$(" in ln or "`" in ln for ln in body):
                    out.append("\n".join(body) + "\n")
            pending = []
    return "".join(out)


def command_heads(command: str) -> list[str]:
    """The basename of every command a shell line would run, for the allowlist.

    Shell-aware: a `|`, `;` or `&&` inside quotes is text, not a separator
    (`grep -E "cost|invested"` is one grep, not a grep and an `invested"`),
    redirections and their targets are skipped, and leading `VAR=value`
    assignments and shell keywords are not commands. A line the lexer cannot
    parse (an unbalanced quote — the shell would reject it too) yields the
    pseudo-command `<unparseable>`, which no allowlist contains.
    """
    # The whole command is one lexer input, not one per line: a quoted string
    # may span lines (a multi-paragraph `git commit -m "..."`), and lexing
    # each line alone would see an unbalanced quote and refuse it. Newlines
    # outside quotes are command separators, and `#` starts a comment.
    command = strip_heredoc_bodies(command)
    lexer = shlex.shlex(command, posix=True, punctuation_chars="();<>|&\n")
    lexer.whitespace_split = True
    lexer.whitespace = " \t\r"  # \n is punctuation: its own token, a command separator
    lexer.commenters = "#"
    try:
        tokens = list(lexer)
    except ValueError:
        return ["<unparseable>"]
    heads: list[str] = []
    expect_head = True
    skip_next = False
    for tok in tokens:
        if skip_next:
            skip_next = False
            continue
        if tok in _SEPARATORS or tok.strip("\n") == "":
            expect_head = True
            continue
        if tok in _REDIRECTS or (tok and tok[0].isdigit() and tok.lstrip("0123456789") in _REDIRECTS):
            skip_next = True  # the redirection target (`2>&1` lexes as `2`, `>&`, `1`: the `2` was a bare digit word)
            continue
        if not expect_head or tok.isdigit():
            continue  # (a bare digit is a file descriptor: `2>&1` lexes as `2`, `>&`, `1`)
        if tok in ("for", "case", "select", "function"):
            expect_head = False  # `for f in a b;` / `case $x in`: names, not commands, until the next separator
            continue
        if tok in _SHELL_WORDS:
            continue  # keyword: the command comes after it
        if "=" in tok and not tok.startswith("=") and tok.split("=", 1)[0].replace("_", "a").isalnum():
            continue  # VAR=value prefix: the command comes after it
        heads.append(os.path.basename(tok))
        expect_head = False
    return heads


def _run_subprocess(
    command: str,
    timeout: int,
    cwd: str | None,
    compact: bool = True,
    max_output_chars: int = DEFAULT_MAX_CHARS,
    extra_env: dict[str, str] | None = None,
    cancel_event: Any = None,
    output_sink: "OutputSink | None" = None,
) -> "ToolResult":
    """Execute a shell command in a subprocess and return a ToolResult.

    The command runs in its own process group, and a timeout kills the group:
    the shell, and everything the shell started. Killing only the shell (what
    `subprocess.run` does) left every `uv run pytest` that outran its timeout
    running on in the container, and the executor's pool worker waiting on it.
    A run that is cancelled while the command runs kills the group the same way.

    With an ``output_sink`` the pipes are read as the command writes them and
    every piece is handed to the sink as it arrives (see `_run_streaming`);
    the result is built exactly as it is without one.
    """
    try:
        proc = subprocess.Popen(
            command,
            shell=True,  # noqa: B602
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=cwd,
            env=_safe_env(extra_env),
            start_new_session=True,
        )
    except Exception as e:
        return ToolResult(success=False, result="", error=f"{type(e).__name__}: {e}")
    if output_sink is not None:
        return _run_streaming(proc, command, timeout, compact, max_output_chars, cancel_event, output_sink)
    try:
        out, err = _wait(proc, timeout, cancel_event)
    except _Cancelled:
        _kill_group(proc)
        return ToolResult(success=False, result="", error=_CANCELLED_ERROR)
    except subprocess.TimeoutExpired:
        _kill_group(proc)
        return ToolResult(success=False, result="", error=_timeout_error(timeout))
    except Exception as e:
        _kill_group(proc)
        return ToolResult(success=False, result="", error=f"{type(e).__name__}: {e}")
    return _finish(command, _Completed(out or "", err or "", proc.returncode), compact, max_output_chars)


_CANCELLED_ERROR = (
    "Cancelled: the run was stopped while this command was running. "
    "It was killed, with everything it started."
)


def _timeout_error(timeout: float) -> str:
    return (
        f"Command timed out after {timeout}s and was killed, with everything it started. "
        f"Ask for a longer timeout (up to {_MAX_TIMEOUT}s), or, to leave a server running, "
        "start it with its output redirected (`cmd > log 2>&1 &`) so this call can return."
    )


def _finish(command: str, result: "_Completed", compact: bool, max_output_chars: int) -> ToolResult:
    """The ToolResult of a command that ran to its end: its output, ceilinged and joined."""
    try:
        # Hard ceiling first, so a runaway command cannot exhaust memory here.
        stdout = result.stdout[:_MAX_OUTPUT_SIZE] + "\n... (truncated)" if len(result.stdout) > _MAX_OUTPUT_SIZE else result.stdout
        stderr = result.stderr[:_MAX_OUTPUT_SIZE] + "\n... (truncated)" if len(result.stderr) > _MAX_OUTPUT_SIZE else result.stderr

        notes: list[str] = []
        if compact:
            # Compact each stream separately: stderr is usually the short, important
            # one, and windowing the combined text could drop it entirely.
            stdout, out_notes = compact_output(command, stdout, max_output_chars)
            stderr, err_notes = compact_output(command, stderr, max_output_chars)
            notes = out_notes + [n for n in err_notes if n not in out_notes]

        output = stdout
        if stderr:
            output = f"{stdout}\nSTDERR:\n{stderr}" if stdout else f"STDERR:\n{stderr}"
        if notes:
            output = f"{output}\n\n[output compacted: {'; '.join(notes)}]"

        if result.returncode != 0:
            return ToolResult(
                success=False,
                result=output,
                error=f"Command exited with code {result.returncode}",
                metadata={"exit_code": result.returncode, "compacted": bool(notes)},
            )
        return ToolResult(success=True, result=output, metadata={"compacted": bool(notes)})

    except Exception as e:
        return ToolResult(success=False, result="", error=f"{type(e).__name__}: {e}")


class _Completed(NamedTuple):
    stdout: str
    stderr: str
    returncode: int


class _Cancelled(Exception):
    """The run was cancelled while a command was running."""


_CANCEL_POLL_S = 0.5


def _wait(proc: subprocess.Popen, timeout: float, cancel_event: Any) -> tuple[str, str]:
    """``proc.communicate(timeout)``, looking at the run's cancel flag meanwhile.

    communicate() may be called again after a TimeoutExpired without losing
    output, so it is called in short slices; the last slice raises
    TimeoutExpired as one long call would.
    """
    if cancel_event is None:
        return proc.communicate(timeout=timeout)
    deadline = time.monotonic() + timeout
    while True:
        if cancel_event.is_set():
            raise _Cancelled
        remaining = deadline - time.monotonic()
        try:
            return proc.communicate(timeout=max(0.0, min(_CANCEL_POLL_S, remaining)))
        except subprocess.TimeoutExpired:
            if time.monotonic() >= deadline:
                raise


def _kill_group(proc: subprocess.Popen) -> None:
    """Kill the command's whole process group, then reap the shell.

    Under `start_new_session` the shell's pid is the group id, and the group
    outlives the shell: a `cd x && uv run pytest | tail` whose shell has already
    been killed still has `uv` and `pytest` in it, and they are what was eating
    the container. A process that put itself in a new session escapes this,
    which is what a daemon does on purpose.
    """
    _signal_group(proc)
    try:
        proc.communicate(timeout=5)
    except (subprocess.TimeoutExpired, ValueError, OSError):
        proc.kill()


def _signal_group(proc: subprocess.Popen) -> None:
    """SIGKILL the command's process group (see `_kill_group`), without waiting on it."""
    try:
        if hasattr(os, "killpg"):
            os.killpg(proc.pid, signal.SIGKILL)
        else:  # pragma: no cover - not a platform temper runs on
            proc.kill()
    except ProcessLookupError:
        pass


# --------------------------------------------------------------------------- watching the output

#: ``sink(stream, data)``: one piece of what the command wrote, as it arrived: ``"stdout"`` or
#: ``"stderr"``, and the raw bytes, which may end mid-line or in the middle of a character.
OutputSink = Callable[[str, bytes], None]

_READ_SIZE = 65536
#: After a kill, what the command wrote before it died may still be in the pipes: it is read out
#: to the sink for this long at most (a process that escaped the group can hold a pipe open for
#: ever). Well inside the 5 s the executor allows beyond the timeout, so the answer is this call's.
_DRAIN_AFTER_KILL_S = 2.0


def _run_streaming(
    proc: subprocess.Popen,
    command: str,
    timeout: float,
    compact: bool,
    max_output_chars: int,
    cancel_event: Any,
    output_sink: OutputSink,
) -> ToolResult:
    """`_run_subprocess` for a caller that watches the output as it is written.

    Both pipes are read as they fill, together, and each piece is handed to the sink before the
    next read, so what a script prints is seen while it runs rather than when it ends. The result
    is built as communicate() would have had it (see `_StreamText`): the script's final output, its
    JSON hand-off and its exit status are what they always were. Stopping is unchanged too, timeout
    or cancel: the whole group is killed and the result is empty. What the command wrote until then
    reached the sink as it came, and what was still in the pipes is read out to it before this
    returns. ``metadata["stopped"]`` says which stop it was.
    """
    sink = _GuardedSink(output_sink)
    streams: dict[int, tuple[str, _StreamText]] = {}
    selector = selectors.DefaultSelector()
    try:
        for name, pipe in (("stdout", proc.stdout), ("stderr", proc.stderr)):
            if not isinstance(pipe, io.TextIOWrapper):  # Popen(text=True) above: always one
                raise TypeError(f"the command's {name} is not a text pipe")
            fd = pipe.fileno()
            streams[fd] = (name, _StreamText(pipe.encoding, pipe.errors or "strict"))
            selector.register(fd, selectors.EVENT_READ)
        stop = _pump(proc, selector, streams, sink, time.monotonic() + timeout, cancel_event)
        if stop is not None:
            _signal_group(proc)
            _drain(selector, streams, sink, time.monotonic() + _DRAIN_AFTER_KILL_S)
            _reap(proc)
            error = _CANCELLED_ERROR if stop == "cancelled" else _timeout_error(timeout)
            return ToolResult(success=False, result="", error=error, metadata={"stopped": stop})
        for _, text in streams.values():
            text.feed(b"", final=True)
        bad = [text.error for _, text in streams.values() if text.error]  # stdout's first, as before
        if bad:
            _signal_group(proc)
            _reap(proc)
            return ToolResult(success=False, result="", error=f"UnicodeDecodeError: {bad[0]}")
        out, err = (text.text() for _, text in streams.values())
        return _finish(command, _Completed(out, err, proc.returncode), compact, max_output_chars)
    except Exception as e:
        _signal_group(proc)
        _reap(proc)
        return ToolResult(success=False, result="", error=f"{type(e).__name__}: {e}")
    finally:
        selector.close()
        for pipe in (proc.stdout, proc.stderr):
            if pipe is None:
                continue
            try:
                pipe.close()
            except Exception:  # noqa: BLE001, S110 - closing a pipe we are done with
                pass


def _pump(
    proc: subprocess.Popen,
    selector: selectors.BaseSelector,
    streams: dict[int, tuple[str, "_StreamText"]],
    sink: "_GuardedSink",
    deadline: float,
    cancel_event: Any,
) -> str | None:
    """Read both pipes to their end, then wait for the shell: None, or why it had to be stopped."""
    while True:
        if cancel_event is not None and cancel_event.is_set():
            return "cancelled"
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return "timeout"
        wait = min(_CANCEL_POLL_S, remaining)
        if selector.get_map():
            for key, _ in selector.select(timeout=wait):
                _read(selector, key.fd, streams, sink, decode=True)
            continue
        try:
            proc.wait(timeout=wait)  # both pipes closed: the shell is ending, or closed them itself
            return None
        except subprocess.TimeoutExpired:
            continue


def _drain(
    selector: selectors.BaseSelector,
    streams: dict[int, tuple[str, "_StreamText"]],
    sink: "_GuardedSink",
    until: float,
) -> None:
    """After a kill: hand the sink whatever is left in the pipes, until they close or time is up."""
    while selector.get_map():
        remaining = until - time.monotonic()
        if remaining <= 0:
            return
        for key, _ in selector.select(timeout=min(_CANCEL_POLL_S, remaining)):
            _read(selector, key.fd, streams, sink, decode=False)


def _read(
    selector: selectors.BaseSelector,
    fd: int,
    streams: dict[int, tuple[str, "_StreamText"]],
    sink: "_GuardedSink",
    decode: bool,
) -> None:
    try:
        data = os.read(fd, _READ_SIZE)
    except (BlockingIOError, InterruptedError):
        return
    except OSError:
        data = b""
    if not data:
        selector.unregister(fd)
        return
    name, text = streams[fd]
    if decode:
        text.feed(data)
    sink(name, data)


def _reap(proc: subprocess.Popen) -> None:
    try:
        proc.wait(timeout=1)
    except subprocess.TimeoutExpired:
        proc.kill()


class _GuardedSink:
    """The caller's sink, which can never stop the command being read: one that raises is let go."""

    def __init__(self, sink: OutputSink) -> None:
        self._sink: OutputSink | None = sink

    def __call__(self, stream: str, data: bytes) -> None:
        if self._sink is None:
            return
        try:
            self._sink(stream, data)
        except Exception:  # noqa: BLE001 - the command must be read to its end regardless
            logger.warning("Output sink failed; the rest of this command's output is not passed to it",
                           exc_info=True)
            self._sink = None


class _StreamText:
    """One pipe's text for the result, decoded as ``Popen(text=True).communicate()`` decodes it.

    communicate() decodes a whole stream at its end, strictly, then turns ``\\r\\n`` and ``\\r``
    into ``\\n``. This does the same a piece at a time (a character or a ``\\r\\n`` split across two
    reads is put back together) and keeps only what the result can hold, _MAX_OUTPUT_SIZE and one
    character more to know there was more, so a runaway command costs no memory here. Decoding goes
    on to the end regardless: output that is not valid text fails the call, as it always did,
    wherever the bad byte is, and with the same message.
    """

    def __init__(self, encoding: str, errors: str) -> None:
        self._bytes = codecs.getincrementaldecoder(encoding)(errors)
        self._text = io.IncrementalNewlineDecoder(self._bytes, translate=True)
        self._parts: list[str] = []
        self._size = 0
        self._fed = 0
        self.error: str | None = None

    def feed(self, data: bytes, final: bool = False) -> None:
        if self.error is not None:
            return
        held = len(self._bytes.getstate()[0])  # bytes of a character still waiting for the rest
        try:
            text = self._text.decode(data, final=final)
        except UnicodeDecodeError as e:
            self.error = _decode_error_text(e, self._fed - held)
            return
        self._fed += len(data)
        if text and self._size <= _MAX_OUTPUT_SIZE:
            keep = text[: _MAX_OUTPUT_SIZE + 1 - self._size]
            self._parts.append(keep)
            self._size += len(keep)

    def text(self) -> str:
        return "".join(self._parts)


def _decode_error_text(e: UnicodeDecodeError, offset: int) -> str:
    """``str(e)`` as one decode of the whole stream would have put it: positions from its start."""
    start, end = offset + e.start, offset + e.end
    if e.end - e.start == 1:
        return f"'{e.encoding}' codec can't decode byte 0x{e.object[e.start]:02x} in position {start}: {e.reason}"
    return f"'{e.encoding}' codec can't decode bytes in position {start}-{end - 1}: {e.reason}"


def _safe_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Build a restricted environment for subprocess execution.

    Strips secrets, API keys, and tokens to prevent LLM agents from
    exfiltrating credentials via commands like `env | grep KEY`.
    """
    env = os.environ.copy()
    # Remove keys matching sensitive patterns
    sensitive_suffixes = ("_API_KEY", "_SECRET", "_SECRET_KEY", "_TOKEN", "_PASSWORD", "_PRIVATE_KEY")
    sensitive_exact = {
        "SUDO_ASKPASS", "SSH_AUTH_SOCK", "DATABASE_URL", "TEMPER_DATABASE_URL",
        "TEMPER_DASHBOARD_TOKEN", "CLAUDE_CONFIG_DIR",
        # The GitHub app's keys: with them anyone can act as the app (integrations.github).
        "GITHUB_APP_PRIVATE_KEY", "GITHUB_APP_WEBHOOK_SECRET", "GITHUB_APP_CLIENT_SECRET",
    }
    to_remove = set()
    for key in env:
        if key in sensitive_exact:
            to_remove.add(key)
        elif any(key.endswith(s) for s in sensitive_suffixes):
            to_remove.add(key)
    for key in to_remove:
        env.pop(key, None)
    if extra:
        # Caller-supplied values, applied after stripping so they are never mistaken for inherited
        # secrets and removed. This is how script agents pass data to a script: a value in the
        # environment is data the shell will never parse as code, whoever wrote it.
        env.update({str(k): str(v) for k, v in extra.items()})
    return env
