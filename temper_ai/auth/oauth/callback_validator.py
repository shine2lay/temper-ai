"""OAuth Callback URL Validator.

SECURITY: Prevents open redirect and CSRF attacks by validating
redirect_uri parameter against whitelist.

Defense-in-Depth Layers:
1. Exact match against whitelist (no fuzzy matching)
2. Protocol validation (HTTPS only in production)
3. Host validation (prevent subdomain takeover)
4. Path validation (prevent path traversal)
5. Query parameter stripping (prevent parameter pollution)

References:
- OWASP: https://cheatsheetseries.owasp.org/cheatsheets/Unvalidated_Redirects_and_Forwards_Cheat_Sheet.html
- OAuth 2.0 Security: https://datatracker.ietf.org/doc/html/rfc6749#section-10.15
"""
import ipaddress
import os
from typing import List, Optional, Tuple
from urllib.parse import urlparse, urlunparse

# RFC 1035 maximum hostname length
MAX_HOSTNAME_LENGTH = 253


class CallbackURLValidator:
    """Validates OAuth callback URLs against whitelist.

    SECURITY NOTICE:
    This validator prevents open redirect attacks where an attacker could
    redirect users to a malicious site after authentication. All callback
    URLs must be explicitly whitelisted.

    Example:
        >>> validator = CallbackURLValidator([
        ...     "https://app.example.com/auth/callback",
        ...     "http://localhost:8000/auth/callback"  # Dev only
        ... ])
        >>> validator.validate("https://app.example.com/auth/callback")
        (True, None)
        >>> validator.validate("https://evil.com/steal")
        (False, "URL not in whitelist")
    """

    # SECURITY: Only allow http/https schemes (blocks javascript:, file:, data:, etc.)
    ALLOWED_SCHEMES = {'http', 'https'}
    MAX_HOSTNAME_LENGTH = MAX_HOSTNAME_LENGTH

    def __init__(self, allowed_urls: List[str], allow_localhost: Optional[bool] = None):
        """Initialize validator with whitelist.

        Args:
            allowed_urls: List of allowed callback URLs (exact match required)
            allow_localhost: Allow localhost URLs (default: True in dev, False in prod)
        """
        self.allowed_urls = set(allowed_urls)

        # Auto-detect environment if not specified
        if allow_localhost is None:
            env = os.getenv("ENVIRONMENT", "development")
            allow_localhost = env in ["development", "local", "dev"]

        self.allow_localhost = allow_localhost

    def _normalize_url(self, url: str) -> str:
        """Normalize URL for case-insensitive comparison (RFC 3986 compliant).

        Args:
            url: URL to normalize

        Returns:
            Normalized URL with lowercase scheme and hostname
        """
        parsed = urlparse(url.rstrip('/'))
        # Lowercase scheme and hostname, preserve path case
        normalized = parsed._replace(
            scheme=parsed.scheme.lower(),
            netloc=parsed.netloc.lower()
        )
        return urlunparse(normalized)

    def _is_localhost(self, hostname: str) -> bool:
        """Check if hostname is localhost/loopback (IPv4/IPv6).

        Handles all valid localhost representations including:
        - localhost, localhost.localdomain
        - 127.0.0.1, 127.0.0.2, etc. (any 127.x.x.x)
        - ::1, 0:0:0:0:0:0:0:1, ::ffff:127.0.0.1 (IPv6 loopback variations)

        Args:
            hostname: Hostname to check

        Returns:
            True if localhost/loopback, False otherwise
        """
        if not hostname:
            return False

        # Remove brackets for IPv6 addresses
        hostname = hostname.strip('[]')

        # Check common localhost names
        if hostname in ['localhost', 'localhost.localdomain']:
            return True

        # Validate IP addresses (handles all IPv4/IPv6 loopback variations)
        try:
            ip = ipaddress.ip_address(hostname)
            return ip.is_loopback
        except ValueError:
            return False

    def validate(self, callback_url: str) -> Tuple[bool, Optional[str]]:
        """Validate callback URL against whitelist.

        Args:
            callback_url: URL to validate

        Returns:
            (is_valid, error_message) tuple

        Security Checks:
        1. URL scheme validation (only http/https)
        2. Hostname validation and length check
        3. HTTPS enforcement (production only)
        4. Localhost validation (IPv4/IPv6, dev only)
        5. No query parameters (prevents pollution)
        6. No fragments (prevents injection)
        7. Case-insensitive exact match against whitelist
        """
        if not callback_url:
            return False, "Callback URL is required"

        # Parse URL (only catch expected exceptions)
        try:
            parsed = urlparse(callback_url)
        except ValueError as e:
            return False, f"Invalid URL format: {e}"

        # 1. SECURITY: Validate URL scheme (blocks javascript:, file:, data:, etc.)
        if parsed.scheme not in self.ALLOWED_SCHEMES:
            return False, f"Invalid URL scheme '{parsed.scheme}'. Only http/https allowed."

        # 2. SECURITY: Validate hostname exists
        if not parsed.hostname:
            return False, "URL must have a valid hostname"

        # 3. SECURITY: Validate hostname length (RFC 1035)
        if len(parsed.hostname) > self.MAX_HOSTNAME_LENGTH:
            return False, f"Hostname too long (max {self.MAX_HOSTNAME_LENGTH} chars)"

        # 4. SECURITY: HTTPS enforcement in production
        if not self.allow_localhost and parsed.scheme != "https":
            return False, "HTTPS required for callback URLs in production"

        # 5. SECURITY: Localhost validation (handles all IPv4/IPv6 loopback variations)
        is_localhost = self._is_localhost(parsed.hostname)
        if is_localhost and not self.allow_localhost:
            return False, "Localhost URLs not allowed in production"

        # 6. SECURITY: Reject URLs with query parameters or fragments
        # OAuth providers should send these as separate parameters
        if parsed.query:
            return False, "Callback URL must not contain query parameters"
        if parsed.fragment:
            return False, "Callback URL must not contain fragments"

        # 7. SECURITY: Case-insensitive exact match against whitelist
        normalized_url = self._normalize_url(callback_url)
        normalized_allowed = {self._normalize_url(url) for url in self.allowed_urls}

        if normalized_url not in normalized_allowed:
            return False, "Callback URL not in whitelist"

        return True, None

    def get_allowed_urls(self) -> List[str]:
        """Get list of allowed URLs (for display/debugging).

        Returns:
            Sorted list of allowed callback URLs
        """
        return sorted(self.allowed_urls)

    def add_allowed_url(self, url: str) -> None:
        """Add URL to whitelist.

        SECURITY: Use with caution. Only add trusted URLs.

        Args:
            url: URL to add to whitelist
        """
        self.allowed_urls.add(url)

    def remove_allowed_url(self, url: str) -> bool:
        """Remove URL from whitelist.

        Args:
            url: URL to remove

        Returns:
            True if removed, False if not found
        """
        if url in self.allowed_urls:
            self.allowed_urls.remove(url)
            return True
        return False
