#!/usr/bin/env python3
"""Unit tests for ha-service's --unsafe gate. Standard library only.

Run: python3 ssh/tests/test_ha_service.py
"""

import unittest

from toolharness import load_tool, run_tool

SERVICES = {
    "update": {"install": {"fields": {"backup": {}, "version": {}}}},
    "light": {"turn_on": {"fields": {}}},
}
STATES = [
    {"entity_id": "update.home_assistant_core_update", "state": "on"},
    {"entity_id": "light.kitchen", "state": "off"},
]


class UnsafeGate(unittest.TestCase):
    def setUp(self):
        self.calls = []

        def ha_result(command):
            if command["type"] == "get_services":
                return SERVICES
            if command["type"] == "get_states":
                return STATES
            raise AssertionError(f"unexpected command {command}")

        def ha_call(command, timeout=None):
            self.calls.append(command)
            return {"result": {}}

        self.tool = load_tool("ha-service", ha_result=ha_result, ha_call=ha_call)

    def call(self, *argv):
        return run_tool(self.tool, "ha-service", "call", *argv)

    def test_update_install_is_refused_without_unsafe(self):
        code, _, err = self.call(
            "update.install", "--entity", "update.home_assistant_core_update"
        )
        self.assertNotEqual(code, 0)
        self.assertIn("--unsafe", err)
        self.assertEqual(self.calls, [])

    def test_update_install_runs_with_unsafe(self):
        code, _, err = self.call(
            "update.install",
            "--entity",
            "update.home_assistant_core_update",
            "--unsafe",
        )
        self.assertEqual(code, 0, err)
        self.assertEqual(len(self.calls), 1)

    def test_ordinary_call_needs_no_flag(self):
        code, _, err = self.call("light.turn_on", "--entity", "light.kitchen")
        self.assertEqual(code, 0, err)


if __name__ == "__main__":
    unittest.main()
