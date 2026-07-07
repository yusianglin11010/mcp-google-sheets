"""Unit tests for opt-in inbound authentication (auth provider + email whitelist)."""

import asyncio
import logging
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from mcp.shared.exceptions import McpError

from mcp_google_sheets import auth


VALID_AUTH_ENV = {
    "AUTH_ENABLED": "true",
    "AUTH_GOOGLE_CLIENT_ID": "123-test.apps.googleusercontent.com",
    "AUTH_GOOGLE_CLIENT_SECRET": "GOCSPX-test-secret",
    "AUTH_BASE_URL": "https://sheets-mcp.example.com",
    "AUTH_ALLOWED_EMAILS": "alice@example.com, Bob@Example.com",
}


class FakeAccessToken(SimpleNamespace):
    pass


def run(coro):
    return asyncio.get_event_loop_policy().new_event_loop().run_until_complete(coro)


class BuildAuthProviderTest(unittest.TestCase):
    def test_disabled_returns_none(self):
        self.assertIsNone(auth.build_auth_provider({}))
        self.assertIsNone(auth.build_auth_provider({"AUTH_ENABLED": "false"}))

    def test_enabled_with_missing_settings_fails_closed(self):
        env = dict(VALID_AUTH_ENV)
        del env["AUTH_GOOGLE_CLIENT_SECRET"]
        with self.assertRaises(auth.AuthConfigError) as cm:
            auth.build_auth_provider(env)
        self.assertIn("AUTH_GOOGLE_CLIENT_SECRET", str(cm.exception))

    def test_enabled_builds_google_provider(self):
        provider = auth.build_auth_provider(VALID_AUTH_ENV)
        from fastmcp.server.auth.providers.google import GoogleProvider

        self.assertIsInstance(provider, GoogleProvider)

    def test_auth_enabled_parsing(self):
        for value in ("true", "TRUE", "1", "yes", "on"):
            self.assertTrue(auth.auth_enabled({"AUTH_ENABLED": value}))
        for value in ("false", "0", "no", "off", ""):
            self.assertFalse(auth.auth_enabled({"AUTH_ENABLED": value}))


class EmailWhitelistConfigTest(unittest.TestCase):
    def test_disabled_returns_none(self):
        self.assertIsNone(auth.build_email_whitelist_middleware({}))

    def test_empty_whitelist_fails_startup(self):
        env = dict(VALID_AUTH_ENV, AUTH_ALLOWED_EMAILS="")
        with self.assertRaises(auth.AuthConfigError):
            auth.build_email_whitelist_middleware(env)

    def test_missing_whitelist_fails_startup(self):
        env = dict(VALID_AUTH_ENV)
        del env["AUTH_ALLOWED_EMAILS"]
        with self.assertRaises(auth.AuthConfigError):
            auth.build_email_whitelist_middleware(env)

    def test_whitespace_only_whitelist_fails_startup(self):
        env = dict(VALID_AUTH_ENV, AUTH_ALLOWED_EMAILS=" , ,")
        with self.assertRaises(auth.AuthConfigError):
            auth.build_email_whitelist_middleware(env)

    def test_parse_allowed_emails_normalizes(self):
        emails = auth.parse_allowed_emails(
            {"AUTH_ALLOWED_EMAILS": " Alice@Example.com ,bob@example.com,, "}
        )
        self.assertEqual(emails, {"alice@example.com", "bob@example.com"})


class EmailWhitelistMiddlewareTest(unittest.TestCase):
    def setUp(self):
        self.middleware = auth.build_email_whitelist_middleware(VALID_AUTH_ENV)
        self.context = SimpleNamespace()

    def _call(self, token):
        async def call_next(context):
            return "passed-through"

        with patch("fastmcp.server.dependencies.get_access_token", return_value=token):
            return run(self.middleware.on_request(self.context, call_next))

    def test_whitelisted_email_passes(self):
        token = FakeAccessToken(claims={"email": "alice@example.com"})
        self.assertEqual(self._call(token), "passed-through")

    def test_whitelist_match_is_case_insensitive(self):
        token = FakeAccessToken(claims={"email": "BOB@example.COM"})
        self.assertEqual(self._call(token), "passed-through")

    def test_non_whitelisted_email_rejected_with_403(self):
        token = FakeAccessToken(claims={"email": "mallory@evil.com"})
        with self.assertLogs("mcp_google_sheets.auth", level=logging.WARNING) as logs:
            with self.assertRaises(McpError) as cm:
                self._call(token)
        self.assertIn("403", str(cm.exception))
        # Rejected email is logged; token material never is.
        joined = "\n".join(logs.output)
        self.assertIn("mallory@evil.com", joined)

    def test_missing_email_claim_rejected(self):
        token = FakeAccessToken(claims={"sub": "12345"})
        with self.assertRaises(McpError) as cm:
            self._call(token)
        self.assertIn("403", str(cm.exception))

    def test_missing_token_rejected(self):
        with self.assertRaises(McpError):
            self._call(None)

    def test_rejection_log_never_contains_token(self):
        token = FakeAccessToken(
            claims={"email": "mallory@evil.com"}, token="SECRET-TOKEN-VALUE"
        )
        with self.assertLogs("mcp_google_sheets.auth", level=logging.WARNING) as logs:
            with self.assertRaises(McpError):
                self._call(token)
        self.assertNotIn("SECRET-TOKEN-VALUE", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
