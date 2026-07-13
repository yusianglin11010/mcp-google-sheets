"""Unit tests for outbound identity selection (AUTH_OUTBOUND_MODE)."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from mcp_google_sheets import outbound


class OutboundModeTest(unittest.TestCase):
    def test_default_is_service_account(self):
        self.assertEqual(outbound.outbound_mode({}), "service_account")
        self.assertFalse(outbound.user_mode({}))

    def test_user_mode_parsing_is_normalized(self):
        for value in ("user", "USER", " user "):
            self.assertEqual(
                outbound.outbound_mode({"AUTH_OUTBOUND_MODE": value}), "user"
            )
            self.assertTrue(outbound.user_mode({"AUTH_OUTBOUND_MODE": value}))

    def test_service_account_parsing(self):
        env = {"AUTH_OUTBOUND_MODE": "service_account"}
        self.assertEqual(outbound.outbound_mode(env), "service_account")

    def test_unknown_mode_raises(self):
        with self.assertRaises(outbound.OutboundConfigError):
            outbound.outbound_mode({"AUTH_OUTBOUND_MODE": "foo"})


class ValidateOutboundConfigTest(unittest.TestCase):
    def test_service_account_always_ok(self):
        outbound.validate_outbound_config({})
        outbound.validate_outbound_config({"AUTH_OUTBOUND_MODE": "service_account"})
        outbound.validate_outbound_config(
            {"AUTH_OUTBOUND_MODE": "service_account", "AUTH_ENABLED": "false"}
        )

    def test_user_mode_requires_auth_enabled(self):
        with self.assertRaises(outbound.OutboundConfigError) as cm:
            outbound.validate_outbound_config(
                {"AUTH_OUTBOUND_MODE": "user", "AUTH_ENABLED": "false"}
            )
        self.assertIn("AUTH_ENABLED", str(cm.exception))

    def test_user_mode_with_auth_enabled_ok(self):
        outbound.validate_outbound_config(
            {"AUTH_OUTBOUND_MODE": "user", "AUTH_ENABLED": "true"}
        )


class GetUserServicesTest(unittest.TestCase):
    def setUp(self):
        # Each test starts with a clean memoisation cache.
        outbound._build_user_services.cache_clear()

    def tearDown(self):
        outbound._build_user_services.cache_clear()

    def _patch_token(self, token):
        return patch("fastmcp.server.dependencies.get_access_token", return_value=token)

    def test_builds_services_from_caller_token(self):
        built = {}

        def fake_build(api, version, credentials, cache_discovery):
            built.setdefault(api, credentials)
            return SimpleNamespace(api=api, credentials=credentials)

        token = SimpleNamespace(token="ya29.USER_A", claims={"email": "a@x.com"})
        with self._patch_token(token), patch.object(outbound, "build", fake_build):
            sheets, drive = outbound.get_user_services()

        self.assertEqual(sheets.api, "sheets")
        self.assertEqual(drive.api, "drive")
        # Credentials were constructed from the caller's raw Google token.
        self.assertEqual(built["sheets"].token, "ya29.USER_A")

    def test_memoised_per_token(self):
        def fake_build(api, version, credentials, cache_discovery):
            return SimpleNamespace(api=api, token=credentials.token)

        tok_a = SimpleNamespace(token="ya29.A")
        tok_b = SimpleNamespace(token="ya29.B")
        with patch.object(outbound, "build", fake_build):
            with self._patch_token(tok_a):
                first = outbound.get_user_services()
                again = outbound.get_user_services()
            with self._patch_token(tok_b):
                other = outbound.get_user_services()

        self.assertIs(first[0], again[0])  # same token -> same objects
        self.assertIsNot(first[0], other[0])  # different token -> different objects

    def test_missing_token_raises(self):
        with self._patch_token(None):
            with self.assertRaises(outbound.OutboundConfigError):
                outbound.get_user_services()

    def test_empty_token_raises(self):
        token = SimpleNamespace(token="", claims={})
        with self._patch_token(token):
            with self.assertRaises(outbound.OutboundConfigError):
                outbound.get_user_services()


if __name__ == "__main__":
    unittest.main()
