"""Tests for ENABLED_TOOLS filtering and the share_spreadsheet safety warning."""

import json
import logging
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from mcp_google_sheets import server

# Recommended whitelist for internet-facing deployments (see README).
DEFAULT_ENABLED_TOOLS = (
    "list_sheets, get_sheet_data, get_sheet_formulas, update_cells, "
    "batch_update_cells, add_rows, list_spreadsheets"
)

_LIST_REGISTERED_TOOLS = """
import asyncio, json
from mcp_google_sheets import server
tools = asyncio.run(server.mcp.get_tools())
print(json.dumps(sorted(tools)))
"""


class EnabledToolsFilteringTest(unittest.TestCase):
    def _registered_tools(self, enabled_tools):
        env = {k: v for k, v in os.environ.items() if k != "ENABLED_TOOLS"}
        if enabled_tools is not None:
            env["ENABLED_TOOLS"] = enabled_tools
        result = subprocess.run(
            [sys.executable, "-c", _LIST_REGISTERED_TOOLS],
            capture_output=True,
            text=True,
            env=env,
            check=True,
        )
        return json.loads(result.stdout)

    def test_default_whitelist_excludes_share_spreadsheet(self):
        tools = self._registered_tools(DEFAULT_ENABLED_TOOLS)
        expected = sorted(
            name.strip() for name in DEFAULT_ENABLED_TOOLS.split(",")
        )
        self.assertEqual(tools, expected)
        self.assertNotIn("share_spreadsheet", tools)

    def test_no_filter_registers_share_spreadsheet(self):
        tools = self._registered_tools(None)
        self.assertIn("share_spreadsheet", tools)


class ShareSpreadsheetWarningTest(unittest.TestCase):
    def _run(self, auth_enabled_value, enabled_tools):
        with patch.dict(os.environ, {"AUTH_ENABLED": auth_enabled_value}, clear=False):
            with patch.object(server, "ENABLED_TOOLS", enabled_tools):
                server._warn_if_share_spreadsheet_enabled()

    def test_warns_when_auth_on_and_share_spreadsheet_enabled(self):
        with self.assertLogs("mcp_google_sheets.server", level=logging.WARNING) as logs:
            self._run("true", {"list_sheets", "share_spreadsheet"})
        self.assertIn("share_spreadsheet", "\n".join(logs.output))

    def test_warns_when_auth_on_and_no_filter(self):
        with self.assertLogs("mcp_google_sheets.server", level=logging.WARNING) as logs:
            self._run("true", None)
        self.assertIn("ALL tools", "\n".join(logs.output))

    def test_silent_when_share_spreadsheet_filtered_out(self):
        with self.assertNoLogs("mcp_google_sheets.server", level=logging.WARNING):
            self._run("true", {"list_sheets", "update_cells"})

    def test_silent_when_auth_disabled(self):
        with self.assertNoLogs("mcp_google_sheets.server", level=logging.WARNING):
            self._run("false", None)


if __name__ == "__main__":
    unittest.main()
