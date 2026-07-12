"""
Outbound identity for the Google Sheets MCP server.

Selects *whose* Google identity is used when the server calls the Google Sheets /
Drive APIs, via AUTH_OUTBOUND_MODE:

    service_account (default) - one shared service account for every request.
                                Byte-for-byte the upstream behaviour.
    user                      - each request uses the calling user's OWN Google
                                token (obtained from the inbound OAuth layer),
                                so users reach their own spreadsheets.

user mode has no meaning without inbound auth (there is no user token without
it), so it is fail-closed: enabling user mode with AUTH_ENABLED=false aborts
startup.

Environment variables:
    AUTH_OUTBOUND_MODE - "service_account" (default) or "user"
"""

import logging
import os
from functools import lru_cache
from typing import Mapping, Optional, Tuple

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

logger = logging.getLogger(__name__)

OUTBOUND_MODE_SA = "service_account"
OUTBOUND_MODE_USER = "user"
_VALID_MODES = {OUTBOUND_MODE_SA, OUTBOUND_MODE_USER}

# Extra Google scopes the inbound OAuth must request in user mode so the user's
# token can drive the Sheets/Drive APIs. drive.readonly powers list/search tools.
USER_OUTBOUND_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.readonly",
]


class OutboundConfigError(ValueError):
    """Raised when AUTH_OUTBOUND_MODE is invalid or unusable for the config."""


def outbound_mode(environ: Optional[Mapping[str, str]] = None) -> str:
    """Return the normalized outbound mode (default: service_account)."""
    env = os.environ if environ is None else environ
    raw = (env.get("AUTH_OUTBOUND_MODE") or OUTBOUND_MODE_SA).strip().lower()
    if raw not in _VALID_MODES:
        raise OutboundConfigError(
            f"AUTH_OUTBOUND_MODE must be one of {sorted(_VALID_MODES)}, got {raw!r}"
        )
    return raw


def user_mode(environ: Optional[Mapping[str, str]] = None) -> bool:
    """True when outbound calls should use the caller's own Google token."""
    return outbound_mode(environ) == OUTBOUND_MODE_USER


def validate_outbound_config(environ: Optional[Mapping[str, str]] = None) -> None:
    """
    Fail-closed startup check: user mode is meaningless (and unsafe to silently
    downgrade) without inbound auth, so require AUTH_ENABLED when it is on.
    """
    env = os.environ if environ is None else environ
    if not user_mode(env):
        return
    # Lazy import avoids an import cycle with auth (which imports this module).
    from mcp_google_sheets.auth import auth_enabled

    if not auth_enabled(env):
        raise OutboundConfigError(
            "AUTH_OUTBOUND_MODE=user requires AUTH_ENABLED=true "
            "(user identity comes from the inbound OAuth token)"
        )
    logger.info("Outbound mode: user (per-request Google identity)")


@lru_cache(maxsize=32)
def _build_user_services(token: str) -> Tuple[object, object]:
    """
    Build (sheets, drive) services for one user access token. Memoised by token
    so the API discovery document is not re-fetched on every tool call; a token
    rotation produces a new cache key (old entries evicted by maxsize).
    """
    creds = Credentials(token=token, scopes=USER_OUTBOUND_SCOPES)
    sheets = build("sheets", "v4", credentials=creds, cache_discovery=False)
    drive = build("drive", "v3", credentials=creds, cache_discovery=False)
    return sheets, drive


def get_user_services() -> Tuple[object, object]:
    """
    Return (sheets_service, drive_service) for the CURRENT request's user, built
    from their inbound OAuth Google token. Must be called within a request.
    """
    from fastmcp.server.dependencies import get_access_token

    token = get_access_token()
    raw = getattr(token, "token", None) if token is not None else None
    if not raw:
        raise OutboundConfigError(
            "user outbound mode requires an authenticated access token, but none "
            "was present on this request"
        )
    return _build_user_services(raw)
