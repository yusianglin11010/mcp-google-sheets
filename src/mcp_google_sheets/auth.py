"""
Inbound authentication for the Google Sheets MCP server.

Opt-in via AUTH_ENABLED (default: false). When disabled, the server behaves
exactly like upstream xing5/mcp-google-sheets. When enabled, the server acts
as an OAuth authorization server towards MCP clients (claude.ai custom
connectors) via FastMCP's GoogleProvider (OAuth proxy), while outbound calls
to the Google Sheets API keep using the configured service account.

Environment variables:
    AUTH_ENABLED              - "true" to enable inbound OAuth (default "false")
    AUTH_GOOGLE_CLIENT_ID     - Google OAuth client ID (Web application)
    AUTH_GOOGLE_CLIENT_SECRET - Google OAuth client secret
    AUTH_BASE_URL             - Public HTTPS base URL of this server
    AUTH_JWT_SIGNING_KEY      - Optional; lets issued tokens survive restarts
    AUTH_ALLOWED_EMAILS       - Comma-separated Google account whitelist.
                                Required (non-empty) when AUTH_ENABLED=true.
"""

import logging
import os
from typing import Mapping, Optional

from fastmcp.server.middleware import Middleware

logger = logging.getLogger(__name__)

# Scopes requested from Google for inbound user login. The email claim is
# required by the email whitelist check.
INBOUND_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
]

_TRUE_VALUES = {"1", "true", "yes", "on"}


class AuthConfigError(ValueError):
    """Raised when AUTH_ENABLED is set but the configuration is unusable."""


def auth_enabled(environ: Optional[Mapping[str, str]] = None) -> bool:
    """Return True when inbound authentication is switched on."""
    env = os.environ if environ is None else environ
    return env.get("AUTH_ENABLED", "false").strip().lower() in _TRUE_VALUES


def build_auth_provider(environ: Optional[Mapping[str, str]] = None):
    """
    Build the GoogleProvider for inbound auth, or None when AUTH_ENABLED is off.

    Fails closed: enabling auth with incomplete settings raises AuthConfigError
    instead of starting an unauthenticated server.
    """
    env = os.environ if environ is None else environ
    if not auth_enabled(env):
        return None

    client_id = env.get("AUTH_GOOGLE_CLIENT_ID", "").strip()
    client_secret = env.get("AUTH_GOOGLE_CLIENT_SECRET", "").strip()
    base_url = env.get("AUTH_BASE_URL", "").strip()

    missing = [
        name
        for name, value in [
            ("AUTH_GOOGLE_CLIENT_ID", client_id),
            ("AUTH_GOOGLE_CLIENT_SECRET", client_secret),
            ("AUTH_BASE_URL", base_url),
        ]
        if not value
    ]
    if missing:
        raise AuthConfigError(
            "AUTH_ENABLED=true but required settings are missing: " + ", ".join(missing)
        )

    # Imported lazily so the AUTH_ENABLED=false path never touches fastmcp auth
    # modules and stays byte-for-byte compatible with upstream behavior.
    from fastmcp.server.auth.providers.google import GoogleProvider

    # Lazy import avoids an import cycle (outbound imports auth_enabled).
    from mcp_google_sheets.outbound import USER_OUTBOUND_SCOPES, user_mode

    jwt_signing_key = env.get("AUTH_JWT_SIGNING_KEY", "").strip() or None
    if jwt_signing_key is None:
        logger.warning(
            "AUTH_JWT_SIGNING_KEY is not set: issued tokens will be invalidated "
            "on every server restart"
        )

    # In user outbound mode the caller's own Google token must carry Sheets/Drive
    # access, so request those scopes at inbound login too.
    required_scopes = list(INBOUND_SCOPES)
    if user_mode(env):
        required_scopes += USER_OUTBOUND_SCOPES

    # Consent interstitial is ON by default (a security feature for real
    # browser flows). It can be disabled for local/headless testing where the
    # extra localhost page is unreachable (e.g. paste-URL OAuth).
    require_consent = (
        env.get("AUTH_REQUIRE_CONSENT", "true").strip().lower() in _TRUE_VALUES
    )
    if not require_consent:
        logger.warning(
            "AUTH_REQUIRE_CONSENT=false: OAuth consent screen disabled "
            "(local/testing only)"
        )

    provider_kwargs = {
        "client_id": client_id,
        "client_secret": client_secret,
        "base_url": base_url,
        "required_scopes": required_scopes,
        "require_authorization_consent": require_consent,
    }
    if jwt_signing_key:
        provider_kwargs["jwt_signing_key"] = jwt_signing_key

    logger.info("Inbound MCP OAuth enabled (GoogleProvider, base_url=%s)", base_url)
    return GoogleProvider(**provider_kwargs)


def parse_allowed_emails(environ: Optional[Mapping[str, str]] = None) -> set:
    """Parse AUTH_ALLOWED_EMAILS into a normalized (lowercase) set."""
    env = os.environ if environ is None else environ
    raw = env.get("AUTH_ALLOWED_EMAILS", "")
    return {email.strip().lower() for email in raw.split(",") if email.strip()}


def build_email_whitelist_middleware(environ: Optional[Mapping[str, str]] = None):
    """
    Build the email whitelist middleware, or None when AUTH_ENABLED is off.

    Fail-closed: auth enabled with an empty whitelist aborts startup, so a
    forgotten setting can never turn into "any Google account may log in".
    """
    env = os.environ if environ is None else environ
    if not auth_enabled(env):
        return None

    allowed = parse_allowed_emails(env)
    if not allowed:
        raise AuthConfigError(
            "AUTH_ENABLED=true requires a non-empty AUTH_ALLOWED_EMAILS "
            "whitelist (comma-separated Google account emails)"
        )
    return EmailWhitelistMiddleware(allowed)


def _forbidden(message: str):
    """Create the MCP error raised for non-whitelisted identities."""
    from mcp.shared.exceptions import McpError
    from mcp.types import ErrorData

    return McpError(ErrorData(code=-32003, message=f"403 Forbidden: {message}"))


class EmailWhitelistMiddleware(Middleware):
    """Reject authenticated requests whose Google account email is not whitelisted."""

    def __init__(self, allowed_emails):
        self._allowed = {
            email.strip().lower() for email in allowed_emails if email.strip()
        }

    async def on_request(self, context, call_next):
        from fastmcp.server.dependencies import get_access_token

        try:
            token = get_access_token()
        except Exception:
            token = None

        claims = getattr(token, "claims", None) or {}
        email = claims.get("email")

        if not email:
            # Fail closed: with auth on, every request must carry an
            # identifiable email claim. Never log the token itself.
            logger.warning("Rejected request without an email claim")
            raise _forbidden("no email identity in access token")

        if email.strip().lower() not in self._allowed:
            logger.warning("Rejected non-whitelisted email: %s", email)
            raise _forbidden("account is not on the allowed list")

        return await call_next(context)
