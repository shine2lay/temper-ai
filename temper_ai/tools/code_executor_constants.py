"""Constants for the code executor tool."""

CODE_EXEC_DEFAULT_TIMEOUT = 30
CODE_EXEC_MAX_OUTPUT = 65536  # 64 KB  # noqa: scanner: skip-magic
CODE_EXEC_BLOCKED_MODULES = frozenset(
    {
        "os",
        "sys",
        "subprocess",
        "shutil",
        "socket",
        "http",
        "urllib",
        "requests",
        "ftplib",
        "smtplib",
        "ctypes",
        "importlib",
        "builtins",
        "code",
        "codeop",
        "compile",
        "compileall",
        "pickle",
        "shelve",
    }
)
CODE_EXEC_LANGUAGE = "python"
