"""Constants for the Git tool."""

GIT_ALLOWED_OPERATIONS = frozenset(
    {
        "clone",
        "status",
        "diff",
        "log",
        "commit",
        "branch",
        "checkout",
        "add",
        "pull",
        "fetch",
        "remote",
        "tag",
        "stash",
        "show",
        "rev-parse",
    }
)
GIT_BLOCKED_FLAGS = frozenset(
    {
        "--force",
        "-f",
        "--hard",
        "--delete",
        "-D",
        "--force-with-lease",
        "--no-verify",
    }
)
GIT_DEFAULT_TIMEOUT = 60
GIT_MAX_DIFF_SIZE = 262144  # 256 KB  # noqa: scanner: skip-magic
