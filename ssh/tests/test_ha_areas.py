#!/usr/bin/env python3
"""Unit tests for ha-areas.

The WebSocket layer (ha_lib) is replaced by an in-memory registry that keeps
the Home Assistant behaviour the tool relies on: ids from the name, duplicate
names refused the way Core compares them, `labels` and `aliases` replacing
the whole set with unknown label ids dropped, and deletes clearing members.

Run: python3 ssh/tests/test_ha_areas.py
"""

import copy
import json
import os
import re
import tempfile
import unittest

from toolharness import load_tool, run_tool

AREAS = [
    {
        "area_id": "kitchen",
        "name": "Kitchen",
        "aliases": [],
        "floor_id": "ground",
        "icon": None,
        "labels": ["night"],
    },
    {
        "area_id": "living_room",
        "name": "Living Room",
        "aliases": ["Lounge"],
        "floor_id": None,
        "icon": "mdi:sofa",
        "labels": [],
    },
    {
        "area_id": "storage",
        "name": "Storage",
        "aliases": [],
        "floor_id": None,
        "icon": None,
        "labels": [],
    },
]
FLOORS = [
    {
        "floor_id": "ground",
        "name": "Ground Floor",
        "aliases": [],
        "icon": None,
        "level": 0,
    },
    {
        "floor_id": "first",
        "name": "First Floor",
        "aliases": [],
        "icon": None,
        "level": 1,
    },
]
LABELS = [
    {
        "label_id": "night",
        "name": "Night",
        "color": "indigo",
        "icon": None,
        "description": None,
    },
    {
        "label_id": "battery",
        "name": "Battery",
        "color": None,
        "icon": None,
        "description": None,
    },
]
DEVICES = [
    {
        "id": "dev1",
        "name": "Hue Lamp",
        "name_by_user": None,
        "area_id": "kitchen",
        "labels": [],
    },
    {
        "id": "dev2",
        "name": "Sensor",
        "name_by_user": "Door",
        "area_id": None,
        "labels": ["night"],
    },
]
ENTITIES = [
    {
        "entity_id": "light.lamp",
        "device_id": "dev1",
        "area_id": None,
        "labels": ["night"],
    },
    {"entity_id": "light.spot", "device_id": None, "area_id": "kitchen", "labels": []},
    {"entity_id": "sensor.door", "device_id": "dev2", "area_id": None, "labels": []},
]
RELATED = {
    ("area", "kitchen"): {"automation": ["automation.evening"], "device": ["dev1"]},
}


def slugify(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def norm(name):
    return name.casefold().replace(" ", "")


class FakeHA:
    """Registry-backed stand-in for ha_lib.ha_result."""

    def __init__(self):
        self.reg = {
            "area": copy.deepcopy(AREAS),
            "floor": copy.deepcopy(FLOORS),
            "label": copy.deepcopy(LABELS),
        }
        self.devices = copy.deepcopy(DEVICES)
        self.entities = copy.deepcopy(ENTITIES)
        self.writes = []
        self.ignore_fields = set()

    def known_labels(self, labels):
        ids = {lab["label_id"] for lab in self.reg["label"]}
        return [lab for lab in labels if lab in ids]

    def __call__(self, command):
        kind_type = command["type"]
        if kind_type == "config/device_registry/list":
            return copy.deepcopy(self.devices)
        if kind_type == "config/entity_registry/list":
            return copy.deepcopy(self.entities)
        if kind_type == "search/related":
            return copy.deepcopy(
                RELATED.get((command["item_type"], command["item_id"]), {})
            )
        m = re.fullmatch(r"config/(area|floor|label)_registry/(\w+)", kind_type)
        if not m:
            raise AssertionError(f"unexpected command {kind_type}")
        kind, action = m.groups()
        items = self.reg[kind]
        key = f"{kind}_id"
        if action == "list":
            return copy.deepcopy(items)
        self.writes.append(command)
        fields = {k: v for k, v in command.items() if k not in ("type", key)}
        if "labels" in fields:
            fields["labels"] = self.known_labels(fields["labels"])
        if action == "create":
            if any(norm(e["name"]) == norm(fields["name"]) for e in items):
                raise RuntimeError(
                    f"'{kind_type}' failed: The name {fields['name']} is already "
                    "in use (invalid_info)"
                )
            new_id = slugify(fields["name"])
            while any(e[key] == new_id for e in items):
                new_id += "_2"
            entry = {key: new_id, "aliases": [], "labels": [], "icon": None, **fields}
            items.append(entry)
            return copy.deepcopy(entry)
        entry = next(e for e in items if e[key] == command[key])
        if action == "update":
            for field, value in fields.items():
                if field not in self.ignore_fields:
                    entry[field] = value
            return copy.deepcopy(entry)
        if action == "delete":
            items.remove(entry)
            gone = command[key]
            if kind == "area":
                for x in self.devices + self.entities:
                    if x.get("area_id") == gone:
                        x["area_id"] = None
            if kind == "floor":
                for a in self.reg["area"]:
                    if a.get("floor_id") == gone:
                        a["floor_id"] = None
            if kind == "label":
                for x in self.devices + self.entities + self.reg["area"]:
                    x["labels"] = [lab for lab in x["labels"] if lab != gone]
            return None
        raise AssertionError(f"unexpected action {action}")


class Base(unittest.TestCase):
    def setUp(self):
        self.fake = FakeHA()
        self.tool = load_tool("ha-areas", ha_result=self.fake)
        self.root = tempfile.mkdtemp()
        self.tool.HA_CONFIG = self.root

    def write(self, rel, body):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            f.write(body)

    def run_tool(self, *argv):
        return run_tool(self.tool, "ha-areas", *argv)

    def area(self, area_id):
        return next(a for a in self.fake.reg["area"] if a["area_id"] == area_id)


class ListTest(Base):
    def test_lists_every_area_including_empty_ones(self):
        code, out, _ = self.run_tool("list")
        self.assertEqual(code, 0)
        rows = {a["area_id"]: a for a in out["areas"]}
        self.assertEqual(set(rows), {"kitchen", "living_room", "storage"})
        self.assertEqual(rows["storage"]["entities"], 0)
        # light.spot directly, light.lamp through its device
        self.assertEqual(
            (rows["kitchen"]["entities"], rows["kitchen"]["devices"]), (2, 1)
        )
        self.assertEqual(rows["kitchen"]["floor"], "Ground Floor")
        self.assertEqual(rows["kitchen"]["labels"], ["Night"])

    def test_floors_by_level_and_label_counts(self):
        code, out, _ = self.run_tool("list")
        self.assertEqual([f["floor_id"] for f in out["floors"]], ["ground", "first"])
        self.assertEqual(out["floors"][0]["areas"], ["Kitchen"])
        night = next(lab for lab in out["labels"] if lab["label_id"] == "night")
        self.assertEqual(
            (night["entities"], night["devices"], night["areas"]), (1, 1, 1)
        )

    def test_one_section(self):
        code, out, _ = self.run_tool("list", "labels")
        self.assertEqual(list(out), ["labels"])


class CreateTest(Base):
    def test_area_with_floor_and_label_by_name(self):
        code, out, _ = self.run_tool(
            "create",
            "area",
            "Guest Room",
            "--floor",
            "first floor",
            "--label",
            "battery",
        )
        self.assertEqual(code, 0, out)
        self.assertEqual(
            self.fake.writes,
            [
                {
                    "type": "config/area_registry/create",
                    "name": "Guest Room",
                    "floor_id": "first",
                    "labels": ["battery"],
                }
            ],
        )
        self.assertEqual(out["area_id"], "guest_room")
        self.assertTrue(out["verified"])
        self.assertEqual(out["area"]["floor"], "First Floor")

    def test_duplicate_name_ignores_case_and_spaces(self):
        for name in ("kitchen", "LivingRoom"):
            code, _, err = self.run_tool("create", "area", name)
            self.assertEqual(code, 1)
            self.assertIn("already exists", err)
        self.assertEqual(self.fake.writes, [])

    def test_hyphen_is_a_different_name(self):
        code, out, _ = self.run_tool("create", "area", "Living-Room")
        self.assertEqual(code, 0)

    def test_unknown_floor_or_label_sends_nothing(self):
        code, _, err = self.run_tool("create", "area", "Attic", "--floor", "Roof")
        self.assertEqual(code, 1)
        self.assertIn("Existing floors: First Floor, Ground Floor", err)
        code, _, err = self.run_tool("create", "area", "Attic", "--label", "nope")
        self.assertEqual(code, 1)
        self.assertIn("no label 'nope'", err)
        self.assertEqual(self.fake.writes, [])

    def test_label_colour_and_icon_are_checked(self):
        code, _, err = self.run_tool("create", "label", "Low", "--color", "reddish")
        self.assertEqual(code, 1)
        self.assertIn("theme colour", err)
        code, _, err = self.run_tool("create", "label", "Low", "--icon", "battery")
        self.assertEqual(code, 1)
        self.assertIn("mdi:battery", err)
        code, out, _ = self.run_tool(
            "create", "label", "Low", "--color", "#ff0000", "--icon", "mdi:battery"
        )
        self.assertEqual(code, 0)
        self.assertEqual(out["label"]["color"], "#ff0000")

    def test_floor_with_level(self):
        code, out, _ = self.run_tool("create", "floor", "Basement", "--level", "-1")
        self.assertEqual(code, 0)
        self.assertEqual(self.fake.writes[0]["level"], -1)

    def test_race_with_the_ui_is_explained(self):
        def racing(command):
            if command["type"] == "config/area_registry/create":
                raise RuntimeError(
                    "'config/area_registry/create' failed: The name Attic is "
                    "already in use (invalid_info)"
                )
            return self.fake(command)

        self.tool.ha_result = racing
        code, _, err = self.run_tool("create", "area", "Attic")
        self.assertEqual(code, 1)
        self.assertIn("created in the meantime", err)


class UpdateTest(Base):
    def test_rename_keeps_old_name_as_alias_and_id(self):
        self.write(
            "templates.yaml",
            "x: \"{{ area_entities('Kitchen') }}\"\n"
            # The exact id: Home Assistant tries it as an id first, so it survives
            "y: \"{{ area_entities('kitchen') }}\"\n",
        )
        code, out, _ = self.run_tool("update", "area", "Kitchen", "--name", "Pantry")
        self.assertEqual(code, 0, out)
        sent = self.fake.writes[0]
        self.assertEqual(sent["area_id"], "kitchen")
        self.assertEqual((sent["name"], sent["aliases"]), ("Pantry", ["Kitchen"]))
        self.assertTrue(out["verified"])
        # Listed, but no warning: the alias keeps it working
        self.assertEqual(
            [(r["file"], r["line"]) for r in out["templates_using_old_name"]],
            [("templates.yaml", 1)],
        )
        self.assertNotIn("stop finding", " ".join(out["notes"]))

    def test_rename_without_alias_warns(self):
        self.write("t.yaml", "x: \"{{ 'Kitchen' | area_entities }}\"\n")
        code, out, _ = self.run_tool(
            "update", "area", "kitchen", "--name", "Pantry", "--no-keep-alias"
        )
        self.assertEqual(code, 0)
        self.assertNotIn("aliases", self.fake.writes[0])
        self.assertIn("stop finding", " ".join(out["notes"]))

    def test_case_only_rename_adds_no_alias(self):
        code, out, _ = self.run_tool("update", "area", "Storage", "--name", "STORAGE")
        self.assertEqual(code, 0)
        self.assertNotIn("aliases", self.fake.writes[0])

    def test_rename_to_an_existing_alias_moves_it_to_the_name(self):
        code, _, _ = self.run_tool("update", "area", "Living Room", "--name", "Lounge")
        self.assertEqual(self.fake.writes[0]["aliases"], ["Living Room"])

    def test_rename_to_taken_name_refused(self):
        code, _, err = self.run_tool("update", "area", "Storage", "--name", "kitchen")
        self.assertEqual(code, 1)
        self.assertIn("already exists", err)
        self.assertEqual(self.fake.writes, [])

    def test_label_rename_warns_about_templates(self):
        self.write("t.yaml", "x: \"{{ label_entities('Night') }}\"\n")
        code, out, _ = self.run_tool("update", "label", "night", "--name", "Evening")
        self.assertEqual(code, 0)
        self.assertIn("labels have no aliases", " ".join(out["notes"]))

    def test_add_and_remove_keep_the_rest(self):
        code, out, _ = self.run_tool(
            "update", "area", "Kitchen", "--add-label", "Battery", "--remove-alias", "x"
        )
        self.assertEqual(code, 1)  # no alias x: nothing sent
        self.assertEqual(self.fake.writes, [])
        code, out, _ = self.run_tool(
            "update", "area", "Kitchen", "--add-label", "Battery"
        )
        self.assertEqual(code, 0)
        self.assertEqual(self.fake.writes[0]["labels"], ["battery", "night"])
        self.assertEqual(
            out["changes"]["labels"],
            {"before": ["Night"], "after": ["Battery", "Night"]},
        )
        self.run_tool("update", "area", "Living Room", "--add-alias", "Salon")
        self.assertEqual(self.fake.writes[1]["aliases"], ["Lounge", "Salon"])

    def test_flags_take_several_values(self):
        code, out, _ = self.run_tool(
            "update", "area", "Storage", "--add-label", "Battery", "night"
        )
        self.assertEqual(code, 0, out)
        self.assertEqual(self.fake.writes[0]["labels"], ["battery", "night"])
        code, out, _ = self.run_tool(
            "create", "area", "Attic", "--alias", "Loft", "Roof space"
        )
        self.assertEqual(code, 0, out)
        self.assertEqual(self.fake.writes[1]["aliases"], ["Loft", "Roof space"])

    def test_clearing_colour_description_level(self):
        self.fake.reg["label"][0]["description"] = "after dark"
        self.run_tool("update", "label", "Night", "--no-color", "--no-description")
        self.assertEqual(
            self.fake.writes[0],
            {
                "type": "config/label_registry/update",
                "label_id": "night",
                "color": None,
                "description": None,
            },
        )
        self.run_tool("update", "floor", "First Floor", "--no-level")
        self.assertIsNone(self.fake.writes[1]["level"])

    def test_alias_resolves_the_target(self):
        code, out, _ = self.run_tool("update", "area", "lounge", "--icon", "mdi:tv")
        self.assertEqual(out["area_id"], "living_room")

    def test_floor_by_name_and_clearing(self):
        self.run_tool("update", "area", "Storage", "--floor", "First Floor")
        self.assertEqual(self.area("storage")["floor_id"], "first")
        self.run_tool("update", "area", "Storage", "--no-floor")
        self.assertIsNone(self.area("storage")["floor_id"])

    def test_nothing_to_change_sends_nothing(self):
        code, out, _ = self.run_tool(
            "update", "area", "Kitchen", "--add-label", "night"
        )
        self.assertEqual(code, 0)
        self.assertEqual(out["changes"], {})
        self.assertEqual(self.fake.writes, [])

    def test_dry_run_sends_nothing(self):
        code, out, _ = self.run_tool(
            "update", "area", "Kitchen", "--name", "Pantry", "--dry-run"
        )
        self.assertEqual(code, 0)
        self.assertTrue(out["dry_run"])
        self.assertEqual(self.fake.writes, [])

    def test_read_back_mismatch_exits_1(self):
        self.fake.ignore_fields = {"icon"}
        code, out, _ = self.run_tool("update", "area", "Kitchen", "--icon", "mdi:pot")
        self.assertEqual(code, 1)
        self.assertFalse(out["verified"])

    def test_label_set_compared_as_set(self):
        # Core returns labels in any order; a reversed read-back still verifies
        original = self.fake.__call__

        def reversed_labels(command):
            result = original(command)
            if command["type"] == "config/area_registry/list":
                for a in result:
                    a["labels"] = list(reversed(a["labels"]))
            return result

        self.tool.ha_result = reversed_labels
        code, out, _ = self.run_tool(
            "update", "area", "Kitchen", "--add-label", "battery"
        )
        self.assertEqual(code, 0)
        self.assertTrue(out["verified"])


class ReferencesTest(Base):
    def setUp(self):
        super().setUp()
        self.write(
            "automations.yaml",
            "- alias: kitchen lights off\n"
            "  actions:\n"
            "    - target:\n"
            "        area_id: kitchen\n"
            "    - target:\n"
            "        area_id:\n"
            "          - living_room\n"
            "          - kitchen  # both\n"
            "        entity_id: light.kitchen\n"
            "    - target:\n"
            "        area_id: [storage, kitchen]\n"
            "    - target:\n"
            "        area_id: living_room\n",
        )
        self.write("t.yaml", "x: \"{{ area_entities('Kitchen') | count }}\"\n")
        self.write(
            ".storage/lovelace.home",
            json.dumps(
                {"data": {"views": [{"cards": [{"type": "area", "area": "kitchen"}]}]}}
            ),
        )
        self.write(".storage/core.area_registry", '{"area_id": "kitchen"}')

    def test_show_splits_members_targets_related(self):
        code, out, _ = self.run_tool("show", "area", "Kitchen")
        self.assertEqual(code, 0)
        self.assertEqual(
            out["members"],
            {
                "devices": ["Hue Lamp"],
                "entities": ["light.spot"],
                "entities_via_device": ["light.lamp"],
            },
        )
        lines = sorted(
            (t["file"], t.get("line"), t.get("path")) for t in out["targets"]
        )
        self.assertEqual(
            lines,
            [
                (".storage/lovelace.home", None, "$.data.views[0].cards[0].area"),
                ("automations.yaml", 4, None),
                ("automations.yaml", 8, None),
                ("automations.yaml", 11, None),
                ("t.yaml", 1, None),
            ],
        )
        self.assertEqual(out["related"], {"automations": ["automation.evening"]})

    def test_label_members(self):
        code, out, _ = self.run_tool("show", "label", "Night")
        self.assertEqual(
            out["members"],
            {"entities": ["light.lamp"], "devices": ["Door"], "areas": ["Kitchen"]},
        )

    def test_delete_dry_run_sends_nothing(self):
        code, out, _ = self.run_tool("delete", "area", "Kitchen", "--dry-run")
        self.assertEqual(code, 0)
        self.assertTrue(out["dry_run"])
        self.assertEqual(self.fake.writes, [])
        self.assertEqual(len(out["targets"]), 5)

    def test_delete_area_clears_members(self):
        code, out, _ = self.run_tool("delete", "area", "Kitchen")
        self.assertEqual(code, 0)
        self.assertTrue(out["deleted"])
        self.assertEqual(
            self.fake.writes,
            [{"type": "config/area_registry/delete", "area_id": "kitchen"}],
        )
        self.assertIsNone(self.fake.devices[0]["area_id"])

    def test_delete_floor_and_label(self):
        self.run_tool("delete", "floor", "ground floor")
        self.assertIsNone(self.area("kitchen")["floor_id"])
        self.run_tool("delete", "label", "Night")
        self.assertEqual(self.area("kitchen")["labels"], [])

    def test_delete_unknown_lists_existing(self):
        code, _, err = self.run_tool("delete", "area", "Garage")
        self.assertEqual(code, 1)
        self.assertIn("Kitchen, Living Room, Storage", err)
        self.assertEqual(self.fake.writes, [])


if __name__ == "__main__":
    unittest.main(verbosity=1)
