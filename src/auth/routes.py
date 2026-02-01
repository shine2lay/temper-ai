"""OAuth authentication route handlers.

Provides secure OAuth 2.0 authentication endpoints with:
- CSRF protection via state parameter
- PKCE for authorization code security
- Session fixation prevention
- Secure token handling (never exposed to client)
- Rate limiting
- Comprehensive security headers

SECURITY NOTES:
- Tokens are NEVER exposed in HTTP responses
- Session IDs are regenerated after authentication
- All cookies use HttpOnly, Secure, SameSite flags
- Referrer-Policy prevents code leakage
"""
from typing import Optional, Dict, Any, Tuple
from datetime import datetime
from pathlib import Path
import secrets
import logging
import uuid

from src.auth.oauth.service import OAuthService, OAuthError, OAuthStateError, OAuthProviderError
from src.auth.oauth.config import OAuthConfig
from src.auth.oauth.rate_limiter import RateLimitExceeded
from src.auth.session import SessionStore, UserStore
from src.auth.models import User, Session

logger = logging.getLogger(__name__)


class OAuthRouteHandlers:
    """OAuth route handlers with security best practices.

    This class provides framework-agnostic OAuth route logic that can be
    integrated with any web framework (FastAPI, Flask, Starlette, etc.).

    Security Features:
    - Session fixation prevention (regenerate session ID after auth)
    - Token protection (never expose tokens in response)
    - CSRF protection (state parameter validation)
    - Secure cookies (HttpOnly, Secure, SameSite)
    - Referrer policy (prevent code leakage)
    - Rate limiting (prevent abuse)

    Example Integration with FastAPI:
        >>> from fastapi import FastAPI, Request, Response
        >>> from fastapi.responses import RedirectResponse
        >>>
        >>> app = FastAPI()
        >>> handlers = OAuthRouteHandlers.from_config_file("config/oauth.yaml")
        >>>
        >>> @app.get("/auth/oauth/google")
        >>> async def login(request: Request):
        >>>     redirect_url, headers = await handlers.handle_login_redirect(
        >>>         provider="google",
        >>>         client_ip=request.client.host,
        >>>         redirect_after="/dashboard"
        >>>     )
        >>>     return RedirectResponse(redirect_url, headers=headers)
    """

    def __init__(
        self,
        oauth_service: OAuthService,
        session_store: Optional[SessionStore] = None,
        user_store: Optional[UserStore] = None,
        allowed_redirect_urls: Optional[list] = None,
    ):
        """Initialize OAuth route handlers.

        Args:
            oauth_service: OAuth service for authentication
            session_store: Session storage (default: in-memory)
            user_store: User storage (default: in-memory)
            allowed_redirect_urls: Whitelist of allowed redirect URLs after login
        """
        self.oauth_service = oauth_service
        self.session_store = session_store or SessionStore()
        self.user_store = user_store or UserStore()
        self.allowed_redirect_urls = allowed_redirect_urls or ["/", "/dashboard"]

    @classmethod
    def from_config_file(cls, config_path: Path) -> "OAuthRouteHandlers":
        """Create handlers from OAuth config file.

        Args:
            config_path: Path to oauth.yaml configuration file

        Returns:
            Configured OAuth route handlers
        """
        config = OAuthConfig.from_yaml_file(config_path)
        oauth_service = OAuthService(config)
        return cls(oauth_service)

    def _validate_redirect_url(self, url: str) -> bool:
        """Validate redirect URL against whitelist.

        SECURITY: Prevents open redirect attacks.

        Args:
            url: URL to validate

        Returns:
            True if URL is allowed, False otherwise
        """
        if not url:
            return False

        # Allow relative URLs that don't start with //
        if url.startswith('/') and not url.startswith('//'):
            return url in self.allowed_redirect_urls

        # Block all absolute URLs for security
        # (in production, you could allow specific domains)
        return False

    def _create_secure_cookie(
        self,
        name: str,
        value: str,
        max_age: int = 3600,
        path: str = "/",
    ) -> str:
        """Create secure cookie header.

        SECURITY FLAGS:
        - HttpOnly: Prevents JavaScript access (XSS protection)
        - Secure: HTTPS only (production)
        - SameSite=Lax: CSRF protection
        - Max-Age: Session lifetime

        Args:
            name: Cookie name
            value: Cookie value
            max_age: Cookie lifetime in seconds
            path: Cookie path

        Returns:
            Set-Cookie header value
        """
        return (
            f"{name}={value}; "
            f"Path={path}; "
            f"HttpOnly; "
            f"Secure; "
            f"SameSite=Lax; "
            f"Max-Age={max_age}"
        )

    def _get_security_headers(self) -> Dict[str, str]:
        """Get security headers for OAuth responses.

        SECURITY: Defense-in-depth headers to prevent various attacks.

        Returns:
            Dictionary of security headers
        """
        return {
            # Prevent referrer leakage (CRITICAL for OAuth)
            "Referrer-Policy": "no-referrer",
            # HTTPS enforcement
            "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
            # Clickjacking protection
            "X-Frame-Options": "DENY",
            # MIME sniffing protection
            "X-Content-Type-Options": "nosniff",
            # XSS protection (legacy browsers)
            "X-XSS-Protection": "1; mode=block",
            # Cache control (don't cache OAuth responses)
            "Cache-Control": "no-store, no-cache, must-revalidate, private",
            "Pragma": "no-cache",
        }

    async def handle_login_redirect(
        self,
        provider: str,
        client_ip: str,
        redirect_after: Optional[str] = None,
    ) -> Tuple[str, Dict[str, str]]:
        """Handle OAuth login initiation.

        Generates authorization URL and redirects user to OAuth provider.

        SECURITY:
        - Validates redirect URL against whitelist
        - Generates secure state parameter
        - Stores state server-side with TTL
        - Rate limits per IP

        Args:
            provider: OAuth provider name (e.g., "google")
            client_ip: Client IP address (for rate limiting)
            redirect_after: URL to redirect after successful login

        Returns:
            Tuple of (authorization_url, response_headers)

        Raises:
            RateLimitExceeded: If rate limit exceeded
            OAuthError: If OAuth configuration error
        """
        # Validate redirect URL
        if redirect_after and not self._validate_redirect_url(redirect_after):
            logger.warning(
                f"Invalid redirect URL rejected: {redirect_after}, IP={client_ip}"
            )
            redirect_after = None

        redirect_after = redirect_after or "/dashboard"

        # Generate authorization URL (includes CSRF state and PKCE)
        try:
            auth_url, state = await self.oauth_service.get_authorization_url(
                provider=provider,
                user_id="anonymous",  # No user yet (not authenticated)
                ip_address=client_ip,
            )

            # Build response headers
            headers = self._get_security_headers()

            # Store redirect URL in cookie (short TTL: 10 minutes)
            headers["Set-Cookie"] = self._create_secure_cookie(
                name="oauth_redirect",
                value=redirect_after,
                max_age=600,  # 10 minutes
            )

            logger.info(
                f"OAuth flow initiated: provider={provider}, IP={client_ip}"
            )

            return auth_url, headers

        except RateLimitExceeded as e:
            logger.warning(f"Rate limit exceeded on login: IP={client_ip}")
            raise

        except OAuthError as e:
            logger.error(f"OAuth configuration error: {e}")
            raise

    async def handle_oauth_callback(
        self,
        provider: str,
        code: str,
        state: str,
        client_ip: str,
        user_agent: Optional[str] = None,
        error: Optional[str] = None,
        error_description: Optional[str] = None,
    ) -> Tuple[str, Dict[str, str]]:
        """Handle OAuth callback from provider.

        Exchanges authorization code for tokens, creates/updates user,
        and creates authenticated session.

        SECURITY CRITICAL:
        - Validates state parameter (CSRF protection)
        - Regenerates session ID (session fixation prevention)
        - NEVER exposes tokens in response
        - Stores tokens server-side only
        - Sets secure session cookie

        Args:
            provider: OAuth provider name
            code: Authorization code from provider
            state: State parameter (CSRF protection)
            client_ip: Client IP address
            user_agent: Client user agent string
            oauth_redirect_cookie: Redirect URL from cookie
            error: Error code from provider (if any)
            error_description: Error description from provider

        Returns:
            Tuple of (redirect_url, response_headers)

        Raises:
            OAuthStateError: If state validation fails
            OAuthProviderError: If provider returns error
            OAuthError: If token exchange fails
        """
        # Handle OAuth errors from provider
        if error:
            logger.warning(
                f"OAuth error from provider: {error}, description={error_description}, IP={client_ip}"
            )
            # Redirect to login with error message
            return "/login?error=oauth_denied", self._get_security_headers()

        try:
            # Exchange code for tokens (validates state internally)
            # SECURITY: State is validated and deleted (single-use)
            tokens = await self.oauth_service.exchange_code_for_tokens(
                provider=provider,
                code=code,
                state=state,
                ip_address=client_ip,
            )

            # Get user info from provider
            # SECURITY: Tokens used internally, never exposed
            # Use temporary ID for first-time user info fetch
            user_info = await self.oauth_service.get_user_info(
                user_id="temp_user",
                provider=provider,
            )

            # Check for existing user by OAuth subject first (prevents duplicate accounts)
            existing_user = await self.user_store.get_user_by_oauth(
                provider=provider,
                oauth_subject=user_info["sub"],
            )

            # Reuse existing user_id or create new one
            if existing_user:
                user_id = existing_user.user_id
            else:
                user_id = str(uuid.uuid4())

            # Create or update user in database
            user = await self.user_store.create_or_update_user(
                user_id=user_id,
                email=user_info["email"],
                name=user_info.get("name", user_info["email"]),
                provider=provider,
                oauth_subject=user_info["sub"],  # Google's user ID
                picture=user_info.get("picture"),
            )

            # CRITICAL: Create new session (session fixation prevention)
            # Old session is NOT reused - new session ID generated
            session = await self.session_store.create_session(
                user=user,
                ip_address=client_ip,
                user_agent=user_agent,
                session_max_age=3600,  # 1 hour
            )

            # Get redirect URL from state data (bound to OAuth flow)
            # Note: In production, update OAuth service to store redirect_after in state
            redirect_url = "/dashboard"  # TODO: Get from state_data when service updated

            if not self._validate_redirect_url(redirect_url):
                redirect_url = "/dashboard"

            # Build response headers with security headers
            headers = self._get_security_headers()

            # SECURITY CRITICAL: Set secure session cookie
            # HttpOnly: Prevent JavaScript access
            # Secure: HTTPS only
            # SameSite=Lax: CSRF protection
            session_cookie = self._create_secure_cookie(
                name="session_id",
                value=session.session_id,
                max_age=3600,  # 1 hour
            )

            # Add session cookie to headers
            # Note: Multiple Set-Cookie headers require special handling
            # This will be handled by the web framework (FastAPI/Flask/etc)
            headers["Set-Cookie"] = session_cookie

            logger.info(
                f"OAuth login successful: user={user.user_id}, IP={client_ip}"
            )

            # SECURITY: Return redirect only, NO tokens in response
            return redirect_url, headers

        except OAuthStateError as e:
            logger.warning(
                f"OAuth state validation failed: {e}, IP={client_ip}. "
                f"Possible CSRF attack."
            )
            return "/login?error=invalid_state", self._get_security_headers()

        except OAuthProviderError as e:
            logger.error(f"OAuth provider error: {e}, IP={client_ip}")
            return "/login?error=oauth_error", self._get_security_headers()

        except RateLimitExceeded as e:
            logger.warning(f"Rate limit exceeded on callback: IP={client_ip}")
            # Don't redirect, return error status (handled by framework)
            raise

        except Exception as e:
            logger.error(
                f"Unexpected error in OAuth callback: {e}", exc_info=True
            )
            return "/login?error=oauth_error", self._get_security_headers()

    async def handle_logout(
        self,
        session_id: Optional[str],
        client_ip: str,
        revoke_tokens: bool = True,
    ) -> Tuple[str, Dict[str, str]]:
        """Handle user logout.

        Terminates session, optionally revokes OAuth tokens, and clears cookies.

        SECURITY:
        - Deletes session server-side
        - Optionally revokes tokens with provider
        - Clears session cookie
        - Fail-safe: logout succeeds even if token revocation fails

        Args:
            session_id: Session identifier from cookie
            client_ip: Client IP address
            revoke_tokens: Whether to revoke OAuth tokens

        Returns:
            Tuple of (redirect_url, response_headers)
        """
        if not session_id:
            logger.info(f"Logout attempt with no session: IP={client_ip}")
            # Already logged out, redirect to login
            return "/login", self._get_security_headers()

        # Get session to retrieve user_id
        session = await self.session_store.get_session(session_id)

        if session:
            user_id = session.user_id

            # Attempt to revoke tokens (best-effort, don't fail logout)
            if revoke_tokens:
                try:
                    await self.oauth_service.revoke_tokens(user_id)
                    logger.info(f"OAuth tokens revoked: user={user_id}")
                except Exception as e:
                    logger.warning(
                        f"Token revocation failed (continuing with logout): {e}"
                    )

            # Delete session
            await self.session_store.delete_session(session_id)

            logger.info(f"User logged out: user={user_id}, IP={client_ip}")
        else:
            logger.info(f"Logout with invalid/expired session: IP={client_ip}")

        # Build response headers
        headers = self._get_security_headers()

        # SECURITY: Clear session cookie
        headers["Set-Cookie"] = "session_id=; Path=/; Max-Age=0; HttpOnly; Secure"

        return "/login", headers

    async def get_current_user(self, session_id: Optional[str]) -> Optional[User]:
        """Get currently authenticated user from session.

        Args:
            session_id: Session identifier from cookie

        Returns:
            User if authenticated, None otherwise
        """
        if not session_id:
            return None

        # Get session
        session = await self.session_store.get_session(session_id)
        if not session:
            return None

        # Get user
        user = await self.user_store.get_user_by_id(session.user_id)
        if not user or not user.is_active:
            return None

        return user
