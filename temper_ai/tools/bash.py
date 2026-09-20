"""Bash tool — execute shell commands in a sandboxed environment.

Security:
- Commands run in a subprocess with a clean environment
- workspace_root config constrains the working directory
- Configurable command allowlist (default: common safe commands)
- Timeout enforcement (default 30s, max 600s)
"""

import logging
import os
import re
import shlex
import subprocess  # noqa: B404
from typing import Any

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
_MAX_OUTPUT_SIZE = 256_000  # 256KB


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

    def execute(self, **params: Any) -> ToolResult:
        command = params.get("command", "")
        timeout = min(params.get("timeout", _DEFAULT_TIMEOUT), _MAX_TIMEOUT)

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
        return _run_subprocess(
            command,
            timeout,
            cwd,
            compact=self.config.get("compact_output", True),
            max_output_chars=int(self.config.get("max_output_chars") or DEFAULT_MAX_CHARS),
            extra_env=params.get("env") or None,
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
) -> "ToolResult":
    """Execute a shell command in a subprocess and return a ToolResult."""
    try:
        result = subprocess.run(
            command,
            shell=True,  # noqa: B602
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=_safe_env(extra_env),
        )

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

    except subprocess.TimeoutExpired:
        return ToolResult(success=False, result="", error=f"Command timed out after {timeout}s")
    except Exception as e:
        return ToolResult(success=False, result="", error=f"{type(e).__name__}: {e}")


def _safe_env(extra: dict[str, str] | None = None) -> dict[str, str]:
    """Build a restricted environment for subprocess execution.

    Strips secrets, API keys, and tokens to prevent LLM agents from
    exfiltrating credentials via commands like `env | grep KEY`.
    """
    env = os.environ.copy()
    # Remove keys matching sensitive patterns
    sensitive_suffixes = ("_API_KEY", "_SECRET", "_SECRET_KEY", "_TOKEN", "_PASSWORD")
    sensitive_exact = {
        "SUDO_ASKPASS", "SSH_AUTH_SOCK", "DATABASE_URL", "TEMPER_DATABASE_URL",
        "TEMPER_DASHBOARD_TOKEN", "CLAUDE_CONFIG_DIR",
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
