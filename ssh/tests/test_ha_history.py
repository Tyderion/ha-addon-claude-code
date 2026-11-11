#!/usr/bin/env python3
"""Unit tests for `ha-history`: window resolution (--last / --from / --to)
and `logbook` (causes, user lookup, filters, ordering, empty answers).

ha_result is replaced by a fake that records each WebSocket command and
answers with canned rows shaped like Home Assistant's, so each test can read
what the tool asked for and what it made of the answer. Standard library only;
PyYAML is stubbed if missing.

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

        self.tool = load_tool("ha-history", ha_result=ha_result, ha_http=None)

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


T0 = datetime.fromisoformat("2026-11-11T03:00:00+00:00").timestamp()

ULID = "01K9ZJ3M4QF7B2R8X5W6N1T0VD"
GABRIEL = "a" * 32
SUPERVISOR = "b" * 32

# Rows shaped like HA's logbook/get_events answer (components/logbook/processor.py)
UI_TOGGLE = {
    "when": T0 + 10,
    "entity_id": "light.kitchen",
    "state": "on",
    "context_user_id": GABRIEL,
    "context_event_type": "call_service",
    "context_domain": "light",
    "context_service": "turn_on",
}
BY_AUTOMATION = {
    "when": T0 + 20,
    "entity_id": "light.hallway",
    "state": "on",
    "context_event_type": "automation_triggered",
    "context_domain": "automation",
    "context_name": "Gang Light",
    "context_message": "triggered by event 'shelly.click'",
    "context_source": "event 'shelly.click'",
    "context_entity_id": "automation.gang_light",
}
AUTOMATION_RUN = {
    "when": T0 + 19,
    "name": "Gang Light",
    "message": "triggered by event 'shelly.click'",
    "source": "event 'shelly.click'",
    "entity_id": "automation.gang_light",
    "context_id": "01M7RUN",
    "domain": "automation",
    "context_event_type": "shelly.click",
    "context_domain": "shelly",
    "context_message": "'single' click event for Hallway Input 0 was fired",
}
BY_SCRIPT = {
    "when": T0 + 30,
    "entity_id": "cover.blinds",
    "state": "closed",
    "context_event_type": "script_started",
    "context_domain": "script",
    "context_name": "Bedtime",
    "context_entity_id": "script.bedtime",
}
BY_SERVICE = {
    "when": T0 + 40,
    "entity_id": "switch.fan",
    "state": "off",
    "context_event_type": "call_service",
    "context_domain": "switch",
    "context_service": "turn_off",
}
BY_ENTITY = {
    "when": T0 + 50,
    "entity_id": "light.group",
    "state": "on",
    "context_entity_id": "light.kitchen",
    "context_state": "on",
}
BY_NOTHING = {"when": T0 + 60, "entity_id": "switch.plug", "state": "on"}
BY_SUPERVISOR = {
    "when": T0 + 70,
    "entity_id": "update.core",
    "state": "off",
    "context_user_id": SUPERVISOR,
}
EVENT_ENTITY = {
    "when": T0 + 80,
    "entity_id": "event.shelly_hallway",
    "state": "2026-11-11T03:01:20.000+00:00",
    "attributes": {"event_type": "single"},
}
MESSAGE = {
    "when": T0 + 90,
    "name": "Home Assistant",
    "message": "started",
    "domain": "homeassistant",
}

ALL_ROWS = [
    UI_TOGGLE,
    BY_AUTOMATION,
    AUTOMATION_RUN,
    BY_SCRIPT,
    BY_SERVICE,
    BY_ENTITY,
    BY_NOTHING,
    BY_SUPERVISOR,
    EVENT_ENTITY,
    MESSAGE,
]

USERS = [
    {"id": GABRIEL, "name": "Gabriel", "system_generated": False},
    {"id": SUPERVISOR, "name": "Supervisor", "system_generated": True},
]


class Logbook(unittest.TestCase):
    def setUp(self):
        self.commands = []
        self.rows = list(ALL_ROWS)
        self.auth_list_fails = False
        self.states = {}
        self.paths = []

        def ha_result(command):
            self.commands.append(command)
            if command["type"] == "logbook/get_events":
                return self.rows
            if command["type"] == "config/auth/list":
                if self.auth_list_fails:
                    raise RuntimeError("Unauthorized")
                return USERS
            if command["type"] == "auth/current_user":
                return {"id": GABRIEL, "name": "Gabriel"}
            raise AssertionError(f"unexpected command {command}")

        def ha_http(method, path, body=None):
            self.paths.append(path)
            return self.states.get(path.rsplit("/", 1)[1])

        self.tool = load_tool("ha-history", ha_result=ha_result, ha_http=ha_http)

    def run_logbook(self, *argv):
        return run_tool(self.tool, "ha-history", "logbook", "--to", TO, *argv)

    def entries(self, *argv):
        code, out, err = self.run_logbook(*argv)
        self.assertEqual(code, 0, err)
        return {e.get("entity_id"): e for e in out["entries"]}

    def types_sent(self):
        return [c["type"] for c in self.commands]

    # --- the command sent ---

    def test_unscoped_sends_only_the_window(self):
        self.run_logbook("--last", "2h")
        command = self.commands[0]
        self.assertEqual(
            set(command), {"type", "start_time", "end_time"}, "no filters when unscoped"
        )
        start = datetime.fromisoformat(command["start_time"])
        end = datetime.fromisoformat(command["end_time"])
        self.assertEqual(end, datetime.fromisoformat(TO))
        self.assertEqual(end - start, timedelta(hours=2))

    def test_scoped_sends_entities_and_devices(self):
        self.run_logbook("light.kitchen", "--device", "d1", "--device", "d2")
        command = self.commands[0]
        self.assertEqual(command["entity_ids"], ["light.kitchen"])
        self.assertEqual(command["device_ids"], ["d1", "d2"])
        self.assertNotIn("context_id", command)

    def test_entity_after_device_is_not_swallowed(self):
        self.run_logbook("--device", "d1", "light.kitchen")
        self.assertEqual(self.commands[0]["entity_ids"], ["light.kitchen"])
        self.assertEqual(self.commands[0]["device_ids"], ["d1"])

    def test_context_alone_defaults_to_ten_days(self):
        self.run_logbook("--context", ULID)
        command = self.commands[0]
        self.assertEqual(command["context_id"], ULID)
        start = datetime.fromisoformat(command["start_time"])
        end = datetime.fromisoformat(command["end_time"])
        self.assertEqual(end - start, timedelta(days=10))

    def test_context_with_entity_or_device_is_refused_before_any_call(self):
        for argv in (
            ("light.kitchen", "--context", "x"),
            ("--device", "d", "--context", "x"),
        ):
            self.commands.clear()
            code, _, err = self.run_logbook(*argv)
            self.assertEqual(code, 1)
            self.assertIn("--context cannot be combined", err)
            self.assertEqual(self.commands, [])

    def test_non_ulid_context_is_refused_before_any_call(self):
        # HA drops a malformed id and returns the whole logbook unfiltered
        for bad in ("r" * 32, GABRIEL, ULID[:-1]):
            self.commands.clear()
            code, _, err = self.run_logbook("--context", bad)
            self.assertEqual(code, 1)
            self.assertIn("not a context id", err)
            self.assertEqual(self.commands, [])

    # --- causes ---

    def test_ui_toggle_is_the_token_user(self):
        cause = self.entries()["light.kitchen"]["cause"]
        self.assertEqual(
            cause,
            {
                "kind": "user",
                "service": "light.turn_on",
                "user": {"name": "Gabriel", "token_user": True},
            },
        )

    def test_automation_cause(self):
        cause = self.entries()["light.hallway"]["cause"]
        self.assertEqual(
            cause,
            {
                "kind": "automation",
                "name": "Gang Light",
                "entity_id": "automation.gang_light",
                "trigger": "event 'shelly.click'",
            },
        )

    def test_run_row_keeps_its_own_cause_and_ids(self):
        entry = self.entries()["automation.gang_light"]
        self.assertEqual(entry["kind"], "run")
        self.assertEqual(entry["context_id"], "01M7RUN")
        self.assertEqual(entry["message"], "triggered by event 'shelly.click'")
        self.assertEqual(entry["cause"]["kind"], "event")
        self.assertEqual(entry["cause"]["event_type"], "shelly.click")
        self.assertEqual(entry["cause"]["domain"], "shelly")

    def test_state_rows_carry_no_context_id(self):
        for eid, entry in self.entries().items():
            if entry["kind"] == "state":
                self.assertNotIn("context_id", entry, eid)

    def test_script_service_entity_and_none_causes(self):
        entries = self.entries()
        self.assertEqual(
            entries["cover.blinds"]["cause"],
            {"kind": "script", "name": "Bedtime", "entity_id": "script.bedtime"},
        )
        self.assertEqual(
            entries["switch.fan"]["cause"],
            {"kind": "service", "service": "switch.turn_off"},
        )
        self.assertEqual(
            entries["light.group"]["cause"],
            {"kind": "entity", "entity_id": "light.kitchen", "state": "on"},
        )
        self.assertEqual(entries["switch.plug"]["cause"], {"kind": "none"})

    def test_system_user_is_marked(self):
        cause = self.entries()["update.core"]["cause"]
        self.assertEqual(
            cause,
            {"kind": "user", "user": {"name": "Supervisor", "system_generated": True}},
        )

    def test_automation_with_user_keeps_both(self):
        self.rows = [dict(BY_AUTOMATION, context_user_id=GABRIEL)]
        cause = self.entries()["light.hallway"]["cause"]
        self.assertEqual(cause["kind"], "automation")
        self.assertEqual(cause["user"], {"name": "Gabriel", "token_user": True})

    def test_unknown_user_keeps_the_raw_id(self):
        self.rows = [dict(BY_NOTHING, context_user_id="c" * 32)]
        cause = self.entries()["switch.plug"]["cause"]
        self.assertEqual(cause["user"], {"name": None, "user_id": "c" * 32})

    def test_refused_user_list_warns_and_keeps_ids(self):
        self.auth_list_fails = True
        self.rows = [UI_TOGGLE]
        code, out, err = self.run_logbook("light.kitchen")
        self.assertEqual(code, 0, err)
        self.assertIn("cannot list users", err)
        user = out["entries"][0]["cause"]["user"]
        self.assertEqual(user["user_id"], GABRIEL)
        self.assertTrue(user["token_user"])

    def test_no_user_lookup_without_a_user(self):
        self.rows = [BY_NOTHING, BY_AUTOMATION]
        self.entries()
        self.assertEqual(self.types_sent(), ["logbook/get_events"])

    def test_event_entity_attributes_and_message_rows(self):
        entries = self.entries()
        self.assertEqual(
            entries["event.shelly_hallway"]["attributes"], {"event_type": "single"}
        )
        message = entries[None]
        self.assertEqual(message["kind"], "message")
        self.assertEqual(message["name"], "Home Assistant")

    def test_when_is_local_iso(self):
        when = self.entries()["switch.plug"]["when"]
        self.assertEqual(datetime.fromisoformat(when).timestamp(), T0 + 60)

    # --- ordering, filters, summary ---

    def test_newest_first_with_limit(self):
        code, out, _ = self.run_logbook("--limit", "3")
        self.assertEqual(code, 0)
        whens = [datetime.fromisoformat(e["when"]).timestamp() for e in out["entries"]]
        self.assertEqual(whens, [T0 + 90, T0 + 80, T0 + 70])
        self.assertEqual(out["returned"], 3)
        self.assertTrue(out["truncated"])

    def test_kind_matches_row_or_cause_kind(self):
        code, out, _ = self.run_logbook("--kind", "user")
        self.assertEqual(
            {e["entity_id"] for e in out["entries"]}, {"light.kitchen", "update.core"}
        )
        code, out, _ = self.run_logbook("--kind", "run", "--kind", "none")
        self.assertEqual(
            {e.get("entity_id") for e in out["entries"]},
            {"automation.gang_light", "switch.plug", "event.shelly_hallway", None},
        )

    def test_exclude_takes_globs(self):
        entries = self.entries(
            "--exclude", "light.*", "--exclude", "automation.gang_light"
        )
        self.assertFalse(any(eid and eid.startswith("light.") for eid in entries))
        self.assertNotIn("automation.gang_light", entries)
        self.assertIn("switch.plug", entries)

    def test_filters_apply_before_the_limit(self):
        code, out, _ = self.run_logbook("--kind", "user", "--limit", "1")
        self.assertEqual(out["entries"][0]["entity_id"], "update.core")
        self.assertTrue(out["truncated"])

    def test_by_entity_only_unscoped_and_before_the_limit(self):
        self.rows = [dict(BY_NOTHING, when=T0 + i) for i in range(5)] + [UI_TOGGLE]
        code, out, _ = self.run_logbook("--limit", "1")
        self.assertEqual(
            out["by_entity"],
            [
                {"entity_id": "switch.plug", "count": 5},
                {"entity_id": "light.kitchen", "count": 1},
            ],
        )
        self.assertEqual(out["returned"], 1)

        code, out, _ = self.run_logbook("switch.plug")
        self.assertNotIn("by_entity", out)

    def test_run_rows_count_under_their_automation(self):
        self.rows = [AUTOMATION_RUN, AUTOMATION_RUN, BY_NOTHING]
        code, out, _ = self.run_logbook()
        self.assertEqual(
            out["by_entity"][0], {"entity_id": "automation.gang_light", "count": 2}
        )

    # --- empty answers ---

    def test_entity_without_entries_fails_naming_both_reasons(self):
        self.rows = []
        code, _, err = self.run_logbook("switch.plug")
        self.assertEqual(code, 1)
        self.assertIn("did not change in this window", err)
        self.assertIn("skips it", err)

    def test_numeric_sensor_is_named_as_the_reason(self):
        self.rows = []
        self.states["sensor.power"] = {"attributes": {"unit_of_measurement": "W"}}
        code, _, err = self.run_logbook("sensor.power")
        self.assertEqual(code, 1)
        self.assertIn("numeric sensor", err)

    def test_device_class_sensor_is_named_as_numeric(self):
        self.rows = []
        self.states["sensor.temp"] = {"attributes": {"device_class": "temperature"}}
        code, _, err = self.run_logbook("sensor.temp")
        self.assertEqual(code, 1)
        self.assertIn("numeric sensor", err)

    def test_non_numeric_device_class_is_not(self):
        self.rows = []
        self.states["sensor.when"] = {"attributes": {"device_class": "timestamp"}}
        code, _, err = self.run_logbook("sensor.when")
        self.assertEqual(code, 1)
        self.assertIn("did not change in this window", err)

    def test_continuous_domain_is_named(self):
        self.rows = []
        code, _, err = self.run_logbook("counter.drinks")
        self.assertEqual(code, 1)
        self.assertIn("never records counter entities", err)

    def test_odd_sensor_id_is_quoted_and_the_rest_still_prints(self):
        self.rows = [BY_NOTHING]
        code, out, err = self.run_logbook("switch.plug", "sensor.living room")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.paths, ["/api/states/sensor.living%20room"])
        self.assertEqual(out["returned"], 1)

    def test_one_missing_entity_only_warns(self):
        self.rows = [BY_NOTHING]
        code, out, err = self.run_logbook("switch.plug", "light.nothing")
        self.assertEqual(code, 0, err)
        self.assertIn("'light.nothing'", err)
        self.assertEqual(out["returned"], 1)

    def test_unknown_context_fails(self):
        self.rows = []
        code, _, err = self.run_logbook("--context", ULID)
        self.assertEqual(code, 1)
        self.assertIn("no logbook entries for context", err)
        self.assertIn("child contexts", err)

    def test_empty_unscoped_window_is_not_an_error(self):
        self.rows = []
        code, out, _ = self.run_logbook()
        self.assertEqual(code, 0)
        self.assertEqual(out["entries"], [])
        self.assertEqual(out["by_entity"], [])


if __name__ == "__main__":
    unittest.main()
