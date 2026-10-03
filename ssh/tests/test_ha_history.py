#!/usr/bin/env python3
"""Unit tests for `ha-history` window resolution (--last / --from / --to).

ha_result is replaced by a fake that records the WebSocket command and
answers with one state row, so each test can read the window the tool asked
Home Assistant for. Standard library only; PyYAML is stubbed if missing.

Run: python3 ssh/tests/test_ha_history.py
"""

import unittest
from datetime import datetime, timedelta, timezone

from toolharness import load_tool, run_tool

TO = "2026-08-05T12:00:00+00:00"


class Window(unittest.TestCase):
    def setUp(self):
        self.commands = []

        def ha_result(command):
            self.commands.append(command)
            if command["type"] == "history/history_during_period":
                start = datetime.fromisoformat(command["start_time"]).timestamp()
                return {"light.a": [{"s": "on", "lu": start}]}
            return {}

        self.tool = load_tool("ha-history", ha_result=ha_result)

    def window(self, *argv):
        code, _, err = run_tool(self.tool, "ha-history", "changes", "light.a", *argv)
        self.assertEqual(code, 0, err)
        command = self.commands[-1]
        start = datetime.fromisoformat(command["start_time"])
        end = datetime.fromisoformat(command["end_time"])
        return start, end

    def test_last_counts_back_from_to(self):
        start, end = self.window("--last", "2h", "--to", TO)
        self.assertEqual(end, datetime.fromisoformat(TO))
        self.assertEqual(start, datetime.fromisoformat(TO) - timedelta(hours=2))

    def test_to_alone_ends_the_default_window(self):
        start, end = self.window("--to", TO)
        self.assertEqual(end - start, timedelta(hours=24))
        self.assertEqual(end, datetime.fromisoformat(TO))

    def test_last_without_to_ends_now(self):
        start, end = self.window("--last", "30m")
        self.assertLess(abs(datetime.now(timezone.utc) - end), timedelta(minutes=1))
        self.assertEqual(end - start, timedelta(minutes=30))

    def test_from_to_unchanged(self):
        start, end = self.window("--from", "2026-08-04T00:00:00+00:00", "--to", TO)
        self.assertEqual(start, datetime.fromisoformat("2026-08-04T00:00:00+00:00"))
        self.assertEqual(end, datetime.fromisoformat(TO))

    def test_last_and_from_conflict(self):
        argv = ("changes", "light.a", "--last", "2h", "--from", TO)
        code, _, err = run_tool(self.tool, "ha-history", *argv)
        self.assertEqual(code, 1)
        self.assertIn("not both", err)


if __name__ == "__main__":
    unittest.main()
