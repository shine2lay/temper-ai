"""
Authentication module for coordination service.

Provides token-based authentication for Unix socket connections.
"""

import hmac
import logging
import os
import secrets
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class TokenManager:
    """Manages authentication tokens with secure file operations."""

    def __init__(self, coord_dir: Path):
        """Initialize token manager.

        Args:
            coord_dir: Coordination directory (.claude-coord)
        """
        self.coord_dir = coord_dir
        self.token_file = coord_dir / '.auth_token'
        self._token: Optional[str] = None

    def load_or_generate(self) -> str:
        """Load existing token or generate new one (atomic, race-safe).

        Returns:
            Authentication token

        Raises:
            PermissionError: If token file has insecure permissions
            ValueError: If token file is corrupted
        """
        # Try to read existing token
        try:
            # Verify permissions before reading (defense in depth)
            stat_info = os.stat(self.token_file)
            if stat_info.st_mode & 0o077:  # Check if group/other have any permissions
                logger.error(
                    f"Token file has insecure permissions: {oct(stat_info.st_mode)}. "
                    "Expected 0o600 (user read/write only)"
                )
                raise PermissionError(
                    f"Token file has insecure permissions: {oct(stat_info.st_mode)}"
                )

            token = self.token_file.read_text().strip()

            if len(token) < 32:
                raise ValueError(f"Token file corrupted (too short: {len(token)} bytes)")

            logger.debug(f"Loaded existing auth token from {self.token_file}")
            self._token = token
            return token

        except FileNotFoundError:
            pass  # Token doesn't exist - generate new one

        # Generate new token atomically with correct permissions
        token = secrets.token_urlsafe(32)  # 256 bits of entropy

        # Use unique temporary file per process/thread to avoid temp file collisions
        import threading
        temp_file = f"{self.token_file}.tmp.{os.getpid()}.{threading.get_ident()}"

        fd = None
        try:
            # Create with 0o600 permissions from the start - NO RACE WINDOW
            # This prevents TOCTOU attack where file is created with default perms
            # then chmod'd later (attacker could read in between)
            fd = os.open(
                temp_file,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,  # Exclusive create
                0o600  # Permissions set at creation
            )

            os.write(fd, token.encode('utf-8'))
            os.close(fd)
            fd = None

            # Use link() + unlink() for atomic creation (fails if destination exists)
            # This is safer than rename() which overwrites on Unix
            try:
                os.link(temp_file, str(self.token_file))
                # Success! We won the race
                os.unlink(temp_file)
                logger.info(f"Generated new auth token: {self.token_file}")
                self._token = token
                return token
            except FileExistsError:
                # Another process won the race and created the token file
                # Clean up our temp file and load the existing token
                os.unlink(temp_file)
                logger.debug("Token file created by another process, loading existing")
                # Recursive call to load existing token
                return self.load_or_generate()

        except FileExistsError:
            # Temp file already exists (shouldn't happen with PID+TID but handle anyway)
            if fd is not None:
                os.close(fd)
            # Try again with a different approach
            logger.debug("Temp file collision, retrying")
            return self.load_or_generate()

        except Exception as e:
            # Cleanup temporary file on error
            if fd is not None:
                os.close(fd)
            try:
                os.unlink(temp_file)
            except FileNotFoundError:
                pass
            raise RuntimeError(f"Failed to generate token: {e}") from e

    @property
    def token(self) -> str:
        """Get current token (cached).

        Returns:
            Authentication token

        Raises:
            RuntimeError: If token not loaded
        """
        if self._token is None:
            raise RuntimeError("Token not loaded. Call load_or_generate() first")
        return self._token


class AuthenticationLayer:
    """Verifies client authentication before processing requests."""

    def __init__(self, auth_token: str):
        """Initialize authentication layer.

        Args:
            auth_token: Server's authentication token
        """
        self.auth_token = auth_token

    def verify_token(self, provided_token: str) -> bool:
        """Verify authentication token (constant-time comparison).

        Uses hmac.compare_digest() to prevent timing attacks. Regular string
        comparison (==, !=) short-circuits on first mismatched byte, allowing
        attackers to extract the token through timing analysis.

        Args:
            provided_token: Token from client request

        Returns:
            True if token is valid, False otherwise
        """
        if not provided_token:
            return False

        # CRITICAL: Must use constant-time comparison to prevent timing attacks
        # hmac.compare_digest() runs in constant time regardless of where tokens differ
        return hmac.compare_digest(provided_token, self.auth_token)

    def verify_request(self, request_data: dict) -> Optional[dict]:
        """Verify request has valid authentication.

        Args:
            request_data: Parsed request dictionary

        Returns:
            None if authenticated (proceed with request)
            Error dict if authentication fails
        """
        # Extract auth token from request
        provided_token = request_data.get('auth_token', '')

        # Verify token
        if not self.verify_token(provided_token):
            # Determine specific error
            if not provided_token:
                logger.warning(
                    f"Authentication failed: missing token "
                    f"(method={request_data.get('method')})"
                )
                return {
                    "code": "AUTH_REQUIRED",
                    "message": "Authentication token required",
                    "data": {
                        "hint": "Include 'auth_token' field in request. "
                                "Token is generated at .claude-coord/.auth_token when daemon starts."
                    }
                }
            else:
                # Log partial token for debugging (first 8 chars only)
                token_prefix = provided_token[:8] if len(provided_token) >= 8 else "???"
                logger.warning(
                    f"Authentication failed: invalid token "
                    f"(method={request_data.get('method')}, "
                    f"token_prefix={token_prefix}...)"
                )
                return {
                    "code": "AUTH_INVALID",
                    "message": "Invalid authentication token",
                    "data": {
                        "hint": "Token mismatch. Server may have been restarted with new token. "
                                "Check .claude-coord/.auth_token and reload."
                    }
                }

        # Authentication successful
        return None
