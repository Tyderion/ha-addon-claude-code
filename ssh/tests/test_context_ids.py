#!/usr/bin/env python3
"""Unit tests for the context ids `ha-service call` and `ha-trace show` print.

Both are the handle for `ha-history logbook --context <id>`: the call's own
context shows exactly what that call changed, and a trace's context is the
one its logbook run row carries. Standard library only.

Run: python3 ssh/tests/test_context_ids.py
"""

import unittest

from toolharness import load_tool, run_tool

CONTEXT = {"id": "01M7CALL", "parent_id": None, "user_id": "a" * 32}

SERVICES = {"light": {"turn_on": {"fields": {"brightness": {}}}}}
STATES = [
    {"entity_id": "light.kitchen", "state": "off", "attributes": {}},
    {
        "entity_id": "automation.gang_light",
        "state": "on",
        "attributes": {"id": "1700", "friendly_name": "Gang Light"},
    },
]


class ServiceCall(unittest.TestCase):
    def setUp(self):
        self.reply = {"context": CONTEXT}

        def ha_result(command):
            if command["type"] == "get_services":
                return SERVICES
            if command["type"] == "get_states":
                return STATES
            raise AssertionError(f"unexpected command {command}")

        def ha_call(command, timeout=None):
            return {"result": self.reply}

        self.tool = load_tool("ha-service", ha_result=ha_result, ha_call=ha_call)

    def call(self):
        argv = ("call", "light.turn_on", "--entity", "light.kitchen")
        code, out, err = run_tool(self.tool, "ha-service", *argv)
        self.assertEqual(code, 0, err)
        return out

    def test_prints_the_calls_context_id(self):
        self.assertEqual(self.call()["context_id"], "01M7CALL")

    def test_no_context_no_field(self):
        self.reply = {}
        self.assertNotIn("context_id", self.call())


class TraceShow(unittest.TestCase):
    def setUp(self):
        self.trace = {
            "run_id": "r1",
            "timestamp": {"start": "2026-11-11T03:00:00+00:00", "finish": None},
            "script_execution": "finished",
            "last_step": "action/0",
            "trace": {},
            "context": {"id": "01M7RUN", "parent_id": "01M7PARENT", "user_id": None},
        }

        def ha_result(command):
            if command["type"] == "get_states":
                return STATES
            if command["type"] == "trace/list":
                return [self.trace]
            if command["type"] == "trace/get":
                return self.trace
            raise AssertionError(f"unexpected command {command}")

        self.tool = load_tool("ha-trace", ha_result=ha_result)

    def show(self):
        code, out, err = run_tool(
            self.tool, "ha-trace", "show", "automation.gang_light"
        )
        self.assertEqual(code, 0, err)
        return out

    def test_prints_the_runs_context_id(self):
        out = self.show()
        self.assertEqual(out["context_id"], "01M7RUN")
        self.assertEqual(out["run_id"], "r1")

    def test_no_context_no_field(self):
        del self.trace["context"]
        self.assertNotIn("context_id", self.show())


if __name__ == "__main__":
    unittest.main()
