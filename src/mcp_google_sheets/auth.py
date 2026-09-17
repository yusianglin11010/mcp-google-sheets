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
    AUTH_ALLOWED_EMAILS_FILE  - Optional path to a live-reloaded whitelist.
                                Accepts comma- or newline-separated emails and
                                takes precedence over AUTH_ALLOWED_EMAILS.
"""

import logging
import os
import re
from pathlib import Path
from typing import Callable, Mapping, Optional

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


def parse_allowed_emails_value(raw: str) -> set[str]:
    """Parse comma- or newline-separated emails into a normalized set."""
    without_comments = "\n".join(line.split("#", 1)[0] for line in raw.splitlines())
    return {
        email.strip().lower()
        for email in re.split(r"[,\n]", without_comments)
        if email.strip()
    }


def parse_allowed_emails(environ: Optional[Mapping[str, str]] = None) -> set[str]:
    """Parse AUTH_ALLOWED_EMAILS into a normalized (lowercase) set."""
    env = os.environ if environ is None else environ
    return parse_allowed_emails_value(env.get("AUTH_ALLOWED_EMAILS", ""))


def load_allowed_emails_file(path: str) -> set[str]:
    """Read and parse a whitelist file, raising a config error if unavailable."""
    try:
        raw = Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        raise AuthConfigError(
            f"Unable to read AUTH_ALLOWED_EMAILS_FILE: {path}"
        ) from exc
    return parse_allowed_emails_value(raw)


def _build_allowed_emails_provider(
    environ: Mapping[str, str],
) -> Callable[[], set[str]]:
    file_path = environ.get("AUTH_ALLOWED_EMAILS_FILE", "").strip()
    if file_path:
        return lambda: load_allowed_emails_file(file_path)

    allowed = parse_allowed_emails(environ)
    return lambda: set(allowed)


def build_email_whitelist_middleware(environ: Optional[Mapping[str, str]] = None):
    """
    Build the email whitelist middleware, or None when AUTH_ENABLED is off.

    Fail-closed: auth enabled with an empty whitelist aborts startup, so a
    forgotten setting can never turn into "any Google account may log in".
    """
    env = os.environ if environ is None else environ
    if not auth_enabled(env):
        return None

    allowed_emails_provider = _build_allowed_emails_provider(env)
    allowed = allowed_emails_provider()
    if not allowed:
        raise AuthConfigError(
            "AUTH_ENABLED=true requires a non-empty AUTH_ALLOWED_EMAILS or "
            "AUTH_ALLOWED_EMAILS_FILE whitelist"
        )
    return EmailWhitelistMiddleware(allowed_emails_provider)


def _forbidden(message: str):
    """Create the MCP error raised for non-whitelisted identities."""
    from mcp.shared.exceptions import McpError
    from mcp.types import ErrorData

    return McpError(ErrorData(code=-32003, message=f"403 Forbidden: {message}"))


class EmailWhitelistMiddleware(Middleware):
    """Reject authenticated requests whose Google account email is not whitelisted."""

    def __init__(self, allowed_emails_provider: Callable[[], set[str]]):
        self._allowed_emails_provider = allowed_emails_provider

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

        try:
            allowed_emails = self._allowed_emails_provider()
        except AuthConfigError as exc:
            logger.error("Email whitelist reload failed: %s", exc)
            raise _forbidden("email allowlist is unavailable") from exc

        if not allowed_emails:
            logger.error("Email whitelist reload produced an empty list")
            raise _forbidden("email allowlist is empty")

        if email.strip().lower() not in allowed_emails:
            logger.warning("Rejected non-whitelisted email: %s", email)
            raise _forbidden("account is not on the allowed list")

        return await call_next(context)
