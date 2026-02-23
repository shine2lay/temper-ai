"""Constants for the HTTP client tool."""

HTTP_DEFAULT_TIMEOUT = 30
HTTP_MAX_RESPONSE_SIZE = 1_048_576  # 1 MB  # scanner: skip-magic
HTTP_BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "127.0.0.1",
        "0.0.0.0",  # noqa: S104  # nosec B104 — SSRF blocklist entry, not a bind address
        "::1",
        "169.254.169.254",  # AWS metadata
        "metadata.google.internal",  # GCP metadata
    }
)
HTTP_ALLOWED_METHODS = frozenset({"GET", "POST", "PUT", "DELETE", "PATCH", "HEAD"})
HTTP_MAX_HEADER_COUNT = 20
