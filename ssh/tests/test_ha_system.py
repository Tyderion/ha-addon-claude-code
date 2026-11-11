#!/usr/bin/env python3
"""Unit tests for ha-system (updates, repairs). Standard library only.

Run: python3 ssh/tests/test_ha_system.py
"""

import unittest

from toolharness import load_tool, run_tool


def update(entity_id, state, **attrs):
    return {"entity_id": entity_id, "state": state, "attributes": attrs}


STATES = [
    update(
        "update.home_assistant_core_update",
        "on",
        title="Home Assistant Core",
        installed_version="2026.9.2",
        latest_version="2026.11.1",
        release_url="https://www.home-assistant.io/latest-release-notes/",
    ),
    update(
        "update.home_assistant_supervisor_update",
        "off",
        title="Home Assistant Supervisor",
        installed_version="2026.10.5",
        latest_version="2026.10.5",
        auto_update=True,
    ),
    update(
        "update.zigbee2mqtt_update",
        "on",
        title="Zigbee2MQTT",
        installed_version="2.14.1-1",
        latest_version="2.14.3-1",
    ),
    update(
        "update.tuya_local_update",
        "on",
        friendly_name="Tuya Local Update",
        installed_version="2026.9.2-rel",
        latest_version="2026.10.0",
        in_progress=True,
        update_percentage=40,
    ),
    update(
        "update.mushroom_update",
        "off",
        friendly_name="Mushroom Update",
        installed_version="v5.2.2",
        latest_version="v5.2.3",
        skipped_version="v5.2.3",
    ),
    update(
        "update.shelly4_office_firmware",
        "on",
        friendly_name="shelly4-office Firmware",
        device_class="firmware",
        installed_version="2.0.0",
        latest_version="2.0.3",
    ),
    update(
        "update.philips_sml001_firmware",
        "unknown",
        device_class="firmware",
        installed_version="0x42006bb7",
        latest_version=None,
    ),
    update(
        "update.philips_ltc002_firmware",
        "unknown",
        device_class="firmware",
        installed_version="0x01001900",
        latest_version=None,
    ),
    update("update.black_bo_firmware", "unavailable", device_class="firmware"),
    {"entity_id": "light.kitchen", "state": "on", "attributes": {}},
]

REGISTRY = [
    {
        "entity_id": "update.home_assistant_core_update",
        "platform": "hassio",
        "unique_id": "home_assistant_core_version_latest",
    },
    {
        "entity_id": "update.home_assistant_supervisor_update",
        "platform": "hassio",
        "unique_id": "home_assistant_supervisor_version_latest",
    },
    {
        "entity_id": "update.zigbee2mqtt_update",
        "platform": "hassio",
        "unique_id": "45df7312_zigbee2mqtt_version_latest",
    },
    {"entity_id": "update.tuya_local_update", "platform": "hacs"},
    {"entity_id": "update.mushroom_update", "platform": "hacs"},
    {"entity_id": "update.shelly4_office_firmware", "platform": "shelly"},
]


class Updates(unittest.TestCase):
    def setUp(self):
        def ha_result(command):
            if command["type"] == "get_states":
                return STATES
            if command["type"] == "config/entity_registry/list":
                return REGISTRY
            raise AssertionError(f"unexpected command {command}")

        self.tool = load_tool("ha-system", ha_result=ha_result)

    def run_updates(self, *argv):
        code, out, err = run_tool(self.tool, "ha-system", "updates", *argv)
        self.assertEqual(code, 0, err)
        return out

    def by_id(self, out):
        return {r["entity_id"]: r for r in out["updates"]}

    def test_lists_only_pending_updates(self):
        out = self.run_updates()
        self.assertEqual(
            set(self.by_id(out)),
            {
                "update.home_assistant_core_update",
                "update.zigbee2mqtt_update",
                "update.tuya_local_update",
                "update.shelly4_office_firmware",
            },
        )
        self.assertEqual(out["pending"], 4)

    def test_kind_and_slug_come_from_the_registry(self):
        rows = self.by_id(self.run_updates())
        self.assertEqual(rows["update.home_assistant_core_update"]["kind"], "core")
        self.assertEqual(rows["update.zigbee2mqtt_update"]["kind"], "app")
        self.assertEqual(
            rows["update.zigbee2mqtt_update"]["slug"], "45df7312_zigbee2mqtt"
        )
        self.assertEqual(rows["update.tuya_local_update"]["kind"], "hacs")
        self.assertEqual(rows["update.shelly4_office_firmware"]["kind"], "firmware")

    def test_sorted_by_kind(self):
        kinds = [r["kind"] for r in self.run_updates()["updates"]]
        self.assertEqual(kinds, ["core", "app", "hacs", "firmware"])

    def test_in_progress_is_shown(self):
        row = self.by_id(self.run_updates())["update.tuya_local_update"]
        self.assertTrue(row["in_progress"])
        self.assertEqual(row["update_percentage"], 40)

    def test_noise_becomes_notes(self):
        notes = self.run_updates()["notes"]
        self.assertTrue(any(n.startswith("2 firmware update entities") for n in notes))
        self.assertIn("1 update entities are unavailable", notes)
        self.assertTrue(any(n.startswith("1 updates were skipped") for n in notes))

    def test_all_adds_current_and_skipped(self):
        rows = self.by_id(self.run_updates("--all"))
        self.assertEqual(rows["update.mushroom_update"]["state"], "skipped")
        self.assertEqual(
            rows["update.home_assistant_supervisor_update"]["state"], "off"
        )
        self.assertTrue(rows["update.home_assistant_supervisor_update"]["auto_update"])
        self.assertNotIn("update.philips_sml001_firmware", rows)


SUP_UUID = "0b5c2a1e-1111-4222-8333-944455556666"
MIRRORED_UUID = "aaaabbbb-cccc-4ddd-8eee-ffff00001111"

CORE_ISSUES = [
    {
        "domain": "tuya_local",
        "issue_domain": "tuya_local",
        "issue_id": "deprecated_yaml",
        "severity": "warning",
        "is_fixable": False,
        "ignored": False,
        "translation_key": "deprecated_yaml",
        "translation_placeholders": {"integration": "Tuya Local"},
        "breaks_in_ha_version": "2026.12.0",
        "learn_more_url": None,
        "created": "2026-11-01T10:00:00+00:00",
    },
    {
        "domain": "hassio",
        "issue_domain": None,
        "issue_id": MIRRORED_UUID.replace("-", ""),
        "severity": "critical",
        "is_fixable": True,
        "ignored": False,
        "translation_key": "issue_system_free_space",
        "translation_placeholders": None,
    },
    {
        "domain": "zha",
        "issue_id": "old_firmware",
        "severity": "error",
        "is_fixable": True,
        "ignored": True,
        "translation_key": "old_firmware",
        "translation_placeholders": None,
    },
]

RESOURCES = {
    "component.tuya_local.issues.deprecated_yaml.title": "The {integration} YAML configuration is being removed",
    "component.tuya_local.issues.deprecated_yaml.description": "Remove the block for {integration} and {missing}.",
    "component.hassio.issues.issue_system_free_space.title": "Data disk is running low on free space",
    "component.hassio.issues.issue_system_free_space.fix_flow.step.system_clear_full_backup.description": "Free some space.",
    "component.hassio.issues.issue_addon_pwned.title": "Insecure secrets in {reference}",
}

SUP_INFO = {
    "issues": [
        {
            "uuid": MIRRORED_UUID,
            "type": "free_space",
            "context": "system",
            "reference": None,
        },
        {
            "uuid": SUP_UUID,
            "type": "pwned",
            "context": "addon",
            "reference": "core_ssh",
        },
    ],
    "unsupported": ["privileged"],
    "unhealthy": [],
}


class Repairs(unittest.TestCase):
    def setUp(self):
        self.commands = []
        self.sup_info = SUP_INFO

        def ha_result(command):
            self.commands.append(command)
            if command["type"] == "repairs/list_issues":
                return {"issues": CORE_ISSUES}
            if command["type"] == "get_config":
                return {"language": "de"}
            if command["type"] == "frontend/get_translations":
                return {"resources": RESOURCES}
            if command["type"] == "supervisor/api":
                return supervisor(command)
            raise AssertionError(f"unexpected command {command}")

        def supervisor(command):
            self.assertEqual(command["method"], "get")
            if self.sup_info is None:
                raise RuntimeError("Unauthorized")
            if command["endpoint"] == "/resolution/info":
                return self.sup_info
            if command["endpoint"] == f"/resolution/issue/{SUP_UUID}/suggestions":
                return {"suggestions": [{"type": "execute_stop", "uuid": "s1"}]}
            raise AssertionError(f"unexpected endpoint {command}")

        self.tool = load_tool("ha-system", ha_result=ha_result)

    def run_repairs(self, *argv):
        code, out, err = run_tool(self.tool, "ha-system", "repairs", *argv)
        self.assertEqual(code, 0, err)
        return out, err

    def test_texts_are_translated_with_placeholders(self):
        out, _ = self.run_repairs()
        tuya = next(r for r in out["repairs"] if r.get("domain") == "tuya_local")
        self.assertEqual(
            tuya["title"], "The Tuya Local YAML configuration is being removed"
        )
        self.assertEqual(
            tuya["description"], "Remove the block for Tuya Local and {missing}."
        )
        self.assertEqual(tuya["breaks_in"], "2026.12.0")
        self.assertNotIn("issue_domain", tuya)

    def test_translations_use_the_configured_language(self):
        self.run_repairs()
        request = next(
            c for c in self.commands if c["type"] == "frontend/get_translations"
        )
        self.assertEqual(request["language"], "de")
        self.assertEqual(request["category"], "issues")
        self.assertIn("hassio", request["integration"])

    def test_fix_flow_text_stands_in_for_a_missing_description(self):
        out, _ = self.run_repairs()
        hassio = next(r for r in out["repairs"] if r.get("domain") == "hassio")
        self.assertEqual(hassio["description"], "Free some space.")

    def test_critical_first(self):
        out, _ = self.run_repairs()
        self.assertEqual(out["repairs"][0]["severity"], "critical")

    def test_ignored_hidden_unless_all(self):
        out, _ = self.run_repairs()
        self.assertNotIn("old_firmware", [r.get("issue_id") for r in out["repairs"]])
        self.assertEqual(out["ignored_hidden"], 1)
        out, _ = self.run_repairs("--all")
        zha = next(r for r in out["repairs"] if r.get("issue_id") == "old_firmware")
        self.assertTrue(zha["ignored"])
        self.assertEqual(zha["title"], "old_firmware")
        self.assertNotIn("ignored_hidden", out)

    def test_supervisor_issue_core_mirrors_appears_once(self):
        out, _ = self.run_repairs()
        sup = [r for r in out["repairs"] if r["source"] == "supervisor"]
        self.assertEqual([r["uuid"] for r in sup], [SUP_UUID])
        self.assertEqual(sup[0]["key"], "issue_addon_pwned")
        self.assertEqual(sup[0]["title"], "Insecure secrets in core_ssh")
        self.assertEqual(
            sup[0]["suggestions"], [{"type": "execute_stop", "uuid": "s1"}]
        )

    def test_system_state_from_the_supervisor(self):
        out, _ = self.run_repairs()
        self.assertEqual(out["system"], {"unsupported": ["privileged"]})

    def test_unreachable_supervisor_warns_and_keeps_core(self):
        self.sup_info = None
        out, err = self.run_repairs()
        self.assertIn("Supervisor", err)
        self.assertEqual({r["source"] for r in out["repairs"]}, {"core"})

    def test_render_survives_odd_braces(self):
        self.assertEqual(self.tool.render("a {b", {}), "a {b")
        self.assertEqual(self.tool.render("{0} x", {}), "{0} x")


if __name__ == "__main__":
    unittest.main()
