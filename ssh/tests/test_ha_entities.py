#!/usr/bin/env python3
"""Unit tests for `ha-entities update` and `ha-entities rename`.

The WebSocket layer (ha_lib) is replaced by an in-memory fake registry, so
the tests run anywhere with the standard library only; PyYAML is stubbed if
it is missing, since every call here uses --format json.

Run: python3 ssh/tests/test_ha_entities.py
"""

import copy
import os
import tempfile
import unittest

from toolharness import load_tool, run_tool

AREAS = [
    {"area_id": "kitchen", "name": "Kitchen"},
    {"area_id": "living_room", "name": "Living Room"},
    {"area_id": "storage", "name": "Storage"},
]
LABELS = [
    {"label_id": "night", "name": "Night"},
    {"label_id": "battery", "name": "Battery"},
]
DEVICES = [
    {
        "id": "dev1",
        "name": "Hue Lamp",
        "name_by_user": None,
        "area_id": "kitchen",
        "labels": [],
    }
]
ENTITIES = [
    {
        "entity_id": "light.lamp",
        "device_id": "dev1",
        "name": None,
        "area_id": None,
        "icon": None,
        "hidden_by": None,
        "disabled_by": None,
        "labels": ["night"],
    },
    {"entity_id": "light.lamp_2", "device_id": None, "name": "Other", "labels": []},
    {"entity_id": "sensor.lamp_power", "device_id": "dev1", "name": None},
]
# What HA's search/related returns, including upward relations that refs
# must drop (device, area, config_entry)
RELATED = {
    ("entity", "light.lamp"): {
        "automation": ["automation.evening"],
        "scene": ["scene.movie"],
        "device": ["dev1"],
        "area": ["kitchen"],
        "config_entry": ["abc"],
    },
    ("device", "dev1"): {
        "automation": ["automation.button_press"],
        "entity": ["light.lamp", "sensor.lamp_power"],
    },
}
STATES = [
    {
        "entity_id": "automation.evening",
        "state": "on",
        "attributes": {"friendly_name": "Evening lights"},
    },
    {"entity_id": "light.lamp", "state": "on", "attributes": {}},
    {"entity_id": "light.lamp_2", "state": "off", "attributes": {}},
    {"entity_id": "sensor.yaml_only", "state": "1", "attributes": {}},
]


class FakeHA:
    """Registry-backed stand-in for ha_lib.ha_result."""

    def __init__(self):
        self.entities = {e["entity_id"]: copy.deepcopy(e) for e in ENTITIES}
        self.devices = {d["id"]: copy.deepcopy(d) for d in DEVICES}
        self.updates = []
        self.ignore_fields = set()

    def __call__(self, command):
        kind = command["type"]
        if kind == "get_states":
            return copy.deepcopy(STATES)
        if kind == "config/area_registry/list":
            return copy.deepcopy(AREAS)
        if kind == "config/label_registry/list":
            return copy.deepcopy(LABELS)
        if kind == "config/device_registry/list":
            return list(copy.deepcopy(self.devices).values())
        if kind == "config/entity_registry/list":
            return list(copy.deepcopy(self.entities).values())
        if kind == "search/related":
            return copy.deepcopy(
                RELATED.get((command["item_type"], command["item_id"]), {})
            )
        if kind == "config/entity_registry/get":
            if command["entity_id"] not in self.entities:
                raise RuntimeError(
                    "'config/entity_registry/get' failed: Entity not found (not_found)"
                )
            return copy.deepcopy(self.entities[command["entity_id"]])
        if kind == "config/entity_registry/update":
            self.updates.append(command)
            entry = self.entities.pop(command["entity_id"])
            for field, value in command.items():
                if field in ("type", "entity_id") or field in self.ignore_fields:
                    continue
                if field == "new_entity_id":
                    entry["entity_id"] = value
                else:
                    entry[field] = value
            self.entities[entry["entity_id"]] = entry
            return {"entity_entry": copy.deepcopy(entry)}
        if kind == "config/device_registry/update":
            self.updates.append(command)
            device = self.devices[command["device_id"]]
            for field, value in command.items():
                if field not in ("type", "device_id"):
                    device[field] = value
            return copy.deepcopy(device)
        raise AssertionError(f"unexpected command {kind}")


class Base(unittest.TestCase):
    def setUp(self):
        self.fake = FakeHA()
        self.tool = load_tool(
            "ha-entities",
            ha_result=self.fake,
        )

    def run_tool(self, *argv):
        """Run main() with argv; return (exit_code, parsed_json_or_None, stderr)."""
        return run_tool(self.tool, "ha-entities", *argv)


class UpdateTest(Base):
    def test_name_and_area_by_name(self):
        code, out, _ = self.run_tool(
            "update", "light.lamp", "--name", "Ceiling", "--area", "living room"
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            self.fake.updates,
            [
                {
                    "type": "config/entity_registry/update",
                    "entity_id": "light.lamp",
                    "name": "Ceiling",
                    "area_id": "living_room",
                }
            ],
        )
        self.assertTrue(out["verified"])
        self.assertEqual(
            out["changes"]["area_id"], {"before": None, "after": "Living Room"}
        )

    def test_unchanged_fields_send_nothing(self):
        self.fake.entities["light.lamp"]["name"] = "Ceiling"
        code, out, _ = self.run_tool("update", "light.lamp", "--name", "Ceiling")
        self.assertEqual(code, 0)
        self.assertEqual(self.fake.updates, [])
        self.assertEqual(out["changes"], {})

    def test_reset_and_clear_send_null(self):
        self.fake.entities["light.lamp"].update(name="X", area_id="kitchen")
        self.run_tool("update", "light.lamp", "--reset-name", "--no-area")
        sent = self.fake.updates[0]
        self.assertIsNone(sent["name"])
        self.assertIsNone(sent["area_id"])

    def test_hidden_icon_disable(self):
        self.run_tool(
            "update", "light.lamp", "--hidden", "--icon", "mdi:lamp", "--disable"
        )
        sent = self.fake.updates[0]
        self.assertEqual(
            (sent["hidden_by"], sent["icon"], sent["disabled_by"]),
            ("user", "mdi:lamp", "user"),
        )

    def test_device_mode_targets_device(self):
        self.fake.entities["light.lamp"]["area_id"] = "kitchen"
        code, out, _ = self.run_tool(
            "update",
            "light.lamp",
            "--device",
            "--name",
            "Lamp",
            "--area",
            "Living Room",
        )
        self.assertEqual(code, 0)
        self.assertEqual(
            self.fake.updates,
            [
                {
                    "type": "config/device_registry/update",
                    "device_id": "dev1",
                    "name_by_user": "Lamp",
                    "area_id": "living_room",
                }
            ],
        )
        self.assertIn("keeps its own area", out["notes"][0])

    def test_device_mode_refuses_entity_only_flags(self):
        code, _, err = self.run_tool("update", "light.lamp", "--device", "--hidden")
        self.assertEqual(code, 1)
        self.assertIn("apply to the entity", err)
        self.assertEqual(self.fake.updates, [])

    def test_dry_run_does_not_write(self):
        code, out, _ = self.run_tool("update", "light.lamp", "--name", "X", "--dry-run")
        self.assertEqual(code, 0)
        self.assertTrue(out["dry_run"])
        self.assertEqual(self.fake.updates, [])

    def test_unknown_area_lists_existing(self):
        code, _, err = self.run_tool("update", "light.lamp", "--area", "Garage")
        self.assertEqual(code, 1)
        self.assertIn("Kitchen, Living Room", err)

    def test_entity_without_unique_id(self):
        code, _, err = self.run_tool("update", "sensor.yaml_only", "--name", "X")
        self.assertEqual(code, 1)
        self.assertIn("no unique_id", err)

    def test_unknown_entity(self):
        code, _, err = self.run_tool("update", "light.nope", "--name", "X")
        self.assertEqual(code, 1)
        self.assertIn("not found", err)

    def test_no_flags(self):
        code, _, err = self.run_tool("update", "light.lamp")
        self.assertEqual(code, 1)
        self.assertIn("nothing to change", err)

    def test_read_back_mismatch_exits_1(self):
        self.fake.ignore_fields = {"name"}
        code, out, _ = self.run_tool("update", "light.lamp", "--name", "X")
        self.assertEqual(code, 1)
        self.assertFalse(out["verified"])

    def test_unknown_area_points_at_ha_areas(self):
        code, _, err = self.run_tool("update", "light.lamp", "--area", "Garage")
        self.assertIn("ha-areas create area", err)


class LabelTest(Base):
    def test_add_keeps_existing_labels_and_shows_names(self):
        code, out, _ = self.run_tool("update", "light.lamp", "--add-label", "battery")
        self.assertEqual(code, 0)
        self.assertEqual(self.fake.updates[0]["labels"], ["battery", "night"])
        self.assertEqual(
            out["changes"]["labels"],
            {"before": ["Night"], "after": ["Battery", "Night"]},
        )
        self.assertTrue(out["verified"])

    def test_several_entities_in_one_call(self):
        code, out, _ = self.run_tool(
            "update", "light.lamp", "light.lamp_2", "--add-label", "Night"
        )
        self.assertEqual(code, 0)
        reports = {r["entity_id"]: r for r in out["updated"]}
        self.assertEqual(reports["light.lamp"]["note"], "already set; nothing to do")
        self.assertEqual(
            self.fake.updates,
            [
                {
                    "type": "config/entity_registry/update",
                    "entity_id": "light.lamp_2",
                    "labels": ["night"],
                }
            ],
        )

    def test_remove(self):
        self.run_tool("update", "light.lamp", "--remove-label", "night")
        self.assertEqual(self.fake.updates[0]["labels"], [])

    def test_device_labels(self):
        self.run_tool("update", "light.lamp", "--device", "--add-label", "night")
        self.assertEqual(
            self.fake.updates[0],
            {
                "type": "config/device_registry/update",
                "device_id": "dev1",
                "labels": ["night"],
            },
        )

    def test_unknown_label_or_entity_sends_nothing(self):
        code, _, err = self.run_tool("update", "light.lamp", "--add-label", "nope")
        self.assertEqual(code, 1)
        self.assertIn("Existing labels: Battery, Night", err)
        code, _, err = self.run_tool(
            "update", "light.lamp", "light.nope", "--add-label", "night"
        )
        self.assertEqual(code, 1)
        self.assertEqual(self.fake.updates, [])

    def test_several_entities_only_with_label_flags(self):
        code, _, err = self.run_tool(
            "update", "light.lamp", "light.lamp_2", "--name", "X"
        )
        self.assertEqual(code, 1)
        self.assertIn("one entity at a time", err)
        self.assertEqual(self.fake.updates, [])

    def test_labels_compared_as_a_set(self):
        original = self.fake.__call__

        def reversed_labels(command):
            result = original(command)
            if command["type"] == "config/entity_registry/update":
                entry = result["entity_entry"]
                entry["labels"] = list(reversed(entry["labels"]))
            return result

        self.tool.ha_result = reversed_labels
        code, out, _ = self.run_tool("update", "light.lamp", "--add-label", "battery")
        self.assertEqual(code, 0)
        self.assertTrue(out["verified"])

    def test_get_and_list_show_labels(self):
        code, out, _ = self.run_tool("get", "light.lamp")
        self.assertEqual(out[0]["labels"], ["Night"])
        code, out, _ = self.run_tool("list", "--label", "night")
        self.assertEqual([e["entity_id"] for e in out["entities"]], ["light.lamp"])

    def test_areas_lists_empty_ones(self):
        code, out, _ = self.run_tool("areas")
        self.assertEqual(
            [(a["area_id"], a["entity_count"]) for a in out["areas"]],
            [("kitchen", 1), ("living_room", 0), ("storage", 0)],
        )


class ConfigTree(Base):
    """A throwaway /homeassistant with references in every kind of place."""

    def setUp(self):
        super().setUp()
        self.root = tempfile.mkdtemp()
        self.tool.HA_CONFIG = self.root
        files = {
            "automations.yaml": "- trigger:\n    entity_id: light.lamp\n",
            "packages/x.yaml": "a: light.lamp_2\nb: sensor.light.lamp\n",
            ".storage/lovelace.main": '{"entity": "light.lamp"}\n',
            ".storage/core.entity_registry": '{"entity_id": "light.lamp"}\n',
            "custom_components/foo/x.yaml": "light.lamp\n",
            "notes.txt": "light.lamp\n",
            "scripts.yaml": "x:\n  sequence:\n    - device_id: dev1\n",
            "template.yaml": "- sensor:\n    state: \"{{ states('sensor.lamp_power') }}\"\n",
            "attr.yaml": 'x: "{{ states.light.lamp.state }}"\n',
        }
        for rel, body in files.items():
            path = os.path.join(self.root, rel)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as f:
                f.write(body)

    def refs(self, out):
        return sorted((r["file"], r["line"]) for r in out["references"])


class RenameTest(ConfigTree):
    def test_rename_and_references(self):
        code, out, _ = self.run_tool("rename", "light.lamp", "light.ceiling")
        self.assertEqual(code, 0)
        self.assertTrue(out["verified"])
        self.assertEqual(
            self.refs(out),
            [(".storage/lovelace.main", 1), ("attr.yaml", 1), ("automations.yaml", 2)],
        )
        self.assertEqual(self.fake.updates[0]["new_entity_id"], "light.ceiling")
        self.assertIn("ha-dashboard", " ".join(out["notes"]))
        self.assertEqual(
            out["used_by"]["automations"],
            [{"entity_id": "automation.evening", "name": "Evening lights"}],
        )

    def test_dry_run(self):
        code, out, _ = self.run_tool(
            "rename", "light.lamp", "light.ceiling", "--dry-run"
        )
        self.assertEqual(code, 0)
        self.assertEqual(self.fake.updates, [])
        self.assertEqual(len(out["references"]), 3)

    def test_refuses_domain_change(self):
        code, _, err = self.run_tool("rename", "light.lamp", "switch.lamp")
        self.assertEqual(code, 1)
        self.assertIn("domain cannot change", err)

    def test_refuses_existing_target(self):
        code, _, err = self.run_tool("rename", "light.lamp", "light.lamp_2")
        self.assertEqual(code, 1)
        self.assertIn("already exists", err)

    def test_refuses_invalid_id(self):
        code, _, err = self.run_tool("rename", "light.lamp", "light.Ceiling Lamp")
        self.assertEqual(code, 1)
        self.assertIn("not a valid entity_id", err)


class RefsTest(ConfigTree):
    def test_entity_refs_merge_search_and_files(self):
        code, out, _ = self.run_tool("refs", "light.lamp")
        self.assertEqual(code, 0)
        refs = out["entities"]["light.lamp"]
        self.assertEqual(set(refs), {"automations", "scenes", "files"})
        self.assertEqual(
            refs["scenes"], [{"entity_id": "scene.movie", "name": "scene.movie"}]
        )
        self.assertEqual(
            sorted(f["file"] for f in refs["files"]),
            [".storage/lovelace.main", "attr.yaml", "automations.yaml"],
        )
        self.assertEqual(out["total_references"], 5)

    def test_unreferenced_yaml_only_entity(self):
        # Not in the registry (no unique_id) but still searchable
        code, out, _ = self.run_tool("refs", "sensor.yaml_only")
        self.assertEqual(code, 0)
        self.assertEqual(out["entities"]["sensor.yaml_only"], {})
        self.assertEqual(out["total_references"], 0)

    def test_word_boundary(self):
        code, out, _ = self.run_tool("refs", "light.lamp_2")
        self.assertEqual(
            [f["file"] for f in out["entities"]["light.lamp_2"]["files"]],
            ["packages/x.yaml"],
        )

    def test_unknown_entity(self):
        code, _, err = self.run_tool("refs", "light.nope")
        self.assertEqual(code, 1)
        self.assertIn("not found", err)

    def test_device_expands_to_all_entities_and_device_id(self):
        code, out, _ = self.run_tool("refs", "light.lamp", "--device")
        self.assertEqual(code, 0)
        (device,) = out["devices"]
        self.assertEqual(device["name"], "Hue Lamp")
        self.assertEqual(
            sorted(device["entities"]), ["light.lamp", "sensor.lamp_power"]
        )
        self.assertEqual(
            device["references"]["automations"][0]["entity_id"],
            "automation.button_press",
        )
        self.assertEqual(device["references"]["files"][0]["file"], "scripts.yaml")
        self.assertEqual(
            device["entities"]["sensor.lamp_power"]["files"][0]["file"], "template.yaml"
        )

    def test_device_refuses_entity_without_device(self):
        code, _, err = self.run_tool("refs", "light.lamp_2", "--device")
        self.assertEqual(code, 1)
        self.assertIn("does not belong to a device", err)


if __name__ == "__main__":
    unittest.main(verbosity=1)
