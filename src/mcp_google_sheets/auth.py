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
"""

import logging
import os
from typing import Mapping, Optional

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
            "AUTH_ENABLED=true but required settings are missing: "
            + ", ".join(missing)
        )

    # Imported lazily so the AUTH_ENABLED=false path never touches fastmcp auth
    # modules and stays byte-for-byte compatible with upstream behavior.
    from fastmcp.server.auth.providers.google import GoogleProvider

    jwt_signing_key = env.get("AUTH_JWT_SIGNING_KEY", "").strip() or None
    if jwt_signing_key is None:
        logger.warning(
            "AUTH_JWT_SIGNING_KEY is not set: issued tokens will be invalidated "
            "on every server restart"
        )

    provider_kwargs = {
        "client_id": client_id,
        "client_secret": client_secret,
        "base_url": base_url,
        "required_scopes": INBOUND_SCOPES,
    }
    if jwt_signing_key:
        provider_kwargs["jwt_signing_key"] = jwt_signing_key

    logger.info("Inbound MCP OAuth enabled (GoogleProvider, base_url=%s)", base_url)
    return GoogleProvider(**provider_kwargs)
