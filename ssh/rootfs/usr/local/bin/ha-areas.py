#!/usr/bin/env python3
"""ha-areas — List, create, rename and delete areas, floors and labels.

Usage:
  ha-areas list [areas|floors|labels]
  ha-areas show <area|floor|label> <name|id>
  ha-areas create area <name> [--floor F] [--icon I] [--alias A ...] [--label L ...]
  ha-areas create floor <name> [--level N] [--icon I] [--alias A ...]
  ha-areas create label <name> [--color C] [--icon I] [--description D]
  ha-areas update area <name|id> [--name N] [--no-keep-alias] [--icon I | --no-icon]
                  [--floor F | --no-floor] [--add-alias A] [--remove-alias A]
                  [--add-label L] [--remove-label L] [--dry-run]
  ha-areas update floor <name|id> [--name N] [--no-keep-alias] [--icon I | --no-icon]
                  [--level N] [--add-alias A] [--remove-alias A] [--dry-run]
  ha-areas update label <name|id> [--name N] [--icon I | --no-icon]
                  [--color C] [--description D] [--dry-run]
  ha-areas delete <area|floor|label> <name|id> [--dry-run]

All commands accept --format yaml|json (default: yaml).

A name or id is accepted wherever one is expected, compared the way Home
Assistant compares names (case and spaces ignored); area and floor aliases
count too. Writes go through the registry WebSocket API, which applies them
live, and are read back.

An id comes from the name at creation and never changes. Renaming an area or
floor keeps its old name as an alias (unless --no-keep-alias), so templates
that look it up by the old name keep working; labels have no aliases, so a
label rename lists the templates that used the old name.

`show` and `delete` list what a thing holds (devices and entities in an area,
areas on a floor, everything carrying a label) and what references it:
`targets` is config that names it (`area_id:` and the like, dashboards, template
calls), `related` is Home Assistant's related-items search, which also finds
automations that only use something inside it. Deleting clears the thing from
every device, entity and area; config that targets it is left pointing at
nothing until something with the same name is created again.
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from ha_lib import (
    FORMAT_PARENT,
    ha_result,
    print_output,
    run_cli,
)

KINDS = ("area", "floor", "label")
# Kinds whose entries carry aliases (labels have none)
ALIASED = ("area", "floor")
# Label colours Home Assistant's frontend theme knows
# (components/config/label_registry.py)
THEME_COLORS = [
    "primary",
    "accent",
    "disabled",
    "red",
    "pink",
    "purple",
    "deep-purple",
    "indigo",
    "blue",
    "light-blue",
    "cyan",
    "teal",
    "green",
    "light-green",
    "lime",
    "yellow",
    "amber",
    "orange",
    "deep-orange",
    "brown",
    "light-grey",
    "grey",
    "dark-grey",
    "blue-grey",
    "black",
    "white",
]
COLOR_HEX_RE = re.compile(r"^#[0-9a-fA-F]{6}$")

HA_CONFIG = "/homeassistant"
# Directories under /homeassistant that never hold hand-written references
SKIP_DIRS = {
    ".git",
    ".cloud",
    "deps",
    "tts",
    "backups",
    "custom_components",
    "node_modules",
    "__pycache__",
}
MAX_SCAN_BYTES = 5 * 1024 * 1024
# Related-item kinds that mean "this uses it"
USED_BY_KINDS = ("automation", "script", "scene")


def normalize(name):
    """Home Assistant's name comparison (normalized_name_base_registry.py)."""
    return name.casefold().replace(" ", "")


def entries(kind):
    return ha_result({"type": f"config/{kind}_registry/list"}) or []


def entry_id(kind, entry):
    return entry[f"{kind}_id"]


def by_id(kind, items, item_id):
    return next((e for e in items if entry_id(kind, e) == item_id), None)


def find(kind, items, value):
    """The entry whose id, name or (area, floor) alias matches value, or None.

    Names win over aliases, as in Home Assistant's own lookups.
    """
    wanted = normalize(value.strip())
    for e in items:
        if entry_id(kind, e).casefold() == value.strip().casefold():
            return e
    for e in items:
        if normalize(e.get("name", "")) == wanted:
            return e
    for e in items:
        if any(normalize(a) == wanted for a in e.get("aliases") or []):
            return e
    return None


def resolve(kind, items, value):
    entry = find(kind, items, value)
    if entry is None:
        names = ", ".join(sorted(e.get("name", entry_id(kind, e)) for e in items))
        create = f" Create one with `ha-areas create {kind} <name>`."
        raise RuntimeError(
            f"no {kind} '{value}'. Existing {kind}s: {names or 'none'}.{create}"
        )
    return entry


def check_name_free(kind, items, name, keep_id=None):
    """Refuse a name Home Assistant would reject as already in use."""
    wanted = normalize(name)
    for e in items:
        if entry_id(kind, e) != keep_id and normalize(e.get("name", "")) == wanted:
            raise RuntimeError(
                f"a {kind} named '{e['name']}' ({entry_id(kind, e)}) already exists; "
                "names are compared without case and spaces"
            )


def check_icon(icon):
    if icon is not None and ":" not in icon:
        raise RuntimeError(f"icon '{icon}' needs a prefix, e.g. mdi:{icon}")


def check_color(color):
    if color is None or color in THEME_COLORS or COLOR_HEX_RE.match(color):
        return
    raise RuntimeError(
        f"colour '{color}' is neither #RRGGBB nor a theme colour: "
        + ", ".join(THEME_COLORS)
    )


def names_of(kind, items, ids):
    by_id = {entry_id(kind, e): e.get("name", entry_id(kind, e)) for e in items}
    return sorted(by_id.get(i, i) for i in ids or [])


class Registries:
    """Everything `list`, `show` and `delete` count against, fetched once."""

    def __init__(self):
        self.areas = entries("area")
        self.floors = entries("floor")
        self.labels = entries("label")
        self.devices = ha_result({"type": "config/device_registry/list"}) or []
        self.entities = ha_result({"type": "config/entity_registry/list"}) or []
        device_areas = {d["id"]: d.get("area_id") for d in self.devices}
        # An entity without its own area is in its device's area
        self.entity_area = {}
        self.inherited = set()
        for e in self.entities:
            area = e.get("area_id")
            if not area and e.get("device_id"):
                area = device_areas.get(e["device_id"])
                if area:
                    self.inherited.add(e["entity_id"])
            if area:
                self.entity_area[e["entity_id"]] = area

    def items(self, kind):
        return {"area": self.areas, "floor": self.floors, "label": self.labels}[kind]

    def members(self, kind, item_id):
        """What a deletion would take the thing away from."""
        if kind == "area":
            return {
                "devices": sorted(
                    device_name(d) for d in self.devices if d.get("area_id") == item_id
                ),
                "entities": sorted(
                    eid
                    for eid, area in self.entity_area.items()
                    if area == item_id and eid not in self.inherited
                ),
                "entities_via_device": sorted(
                    eid
                    for eid, area in self.entity_area.items()
                    if area == item_id and eid in self.inherited
                ),
            }
        if kind == "floor":
            return {
                "areas": sorted(
                    a["name"] for a in self.areas if a.get("floor_id") == item_id
                )
            }
        return {
            "entities": sorted(
                e["entity_id"]
                for e in self.entities
                if item_id in (e.get("labels") or [])
            ),
            "devices": sorted(
                device_name(d)
                for d in self.devices
                if item_id in (d.get("labels") or [])
            ),
            "areas": sorted(
                a["name"] for a in self.areas if item_id in (a.get("labels") or [])
            ),
        }


def device_name(device):
    return device.get("name_by_user") or device.get("name") or device["id"]


# ── references ───────────────────────────────────────────────────────────────

# `area_id: kitchen`, `- area_id: [a, b]`, and for dashboards `area: kitchen`
KEY_RE = re.compile(r"^(?P<indent>\s*)(?:-\s+)?(?P<key>[a-z_]+)\s*:\s*(?P<rest>.*)$")
ITEM_RE = re.compile(r"^(?P<indent>\s*)-\s+(?P<value>.*)$")


def target_keys(kind):
    return {f"{kind}_id", "area"} if kind == "area" else {f"{kind}_id"}


def scalar(text):
    """A YAML scalar without its comment and quotes."""
    text = re.sub(r"\s+#.*$", "", text).strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        text = text[1:-1]
    return text


def inline_values(text):
    text = re.sub(r"\s+#.*$", "", text).strip()
    if text.startswith("[") and text.endswith("]"):
        return [scalar(v) for v in text[1:-1].split(",") if v.strip()]
    return [scalar(text)] if text else []


def template_patterns(kind):
    # `area_entities('Kitchen')` and `'Kitchen' | area_entities`
    call = re.compile(rf"\b{kind}_\w+\(\s*(['\"])(.*?)\1")
    pipe = re.compile(rf"(['\"])([^'\"]*?)\1\s*\|\s*{kind}_\w+")
    return call, pipe


def scan_yaml(path, kind, item_id, template_names):
    """[(line, text)] where the file targets item_id or names it in a template.

    With item_id None only template calls count.
    """
    keys = target_keys(kind)
    call, pipe = template_patterns(kind)
    hits = []
    list_indent = None  # indent of a `<key>:` whose list items follow
    with open(path, encoding="utf-8", errors="replace") as f:
        for lineno, line in enumerate(f, 1):
            line = line.rstrip("\n")
            hit = False
            item = ITEM_RE.match(line)
            if list_indent is not None:
                if item and len(item["indent"]) >= list_indent:
                    hit = item_id in inline_values(item["value"])
                elif line.strip() and not line.strip().startswith("#"):
                    list_indent = None
            key = KEY_RE.match(line) if item_id else None
            if key and key["key"] in keys:
                if key["rest"].strip():
                    hit = hit or item_id in inline_values(key["rest"])
                else:
                    list_indent = len(key["indent"])
            for pattern in (call, pipe):
                for m in pattern.finditer(line):
                    if normalize(m.group(2)) in template_names:
                        hit = True
            if hit:
                hits.append((lineno, line.strip()[:160]))
    return hits


def scan_storage(path, kind, item_id):
    """JSON paths in a UI-made dashboard where a card or target names item_id."""
    keys = target_keys(kind)
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return []
    hits = []

    def walk(node, where):
        if isinstance(node, dict):
            for k, v in node.items():
                here = f"{where}.{k}"
                if k in keys and (v == item_id or isinstance(v, list) and item_id in v):
                    hits.append(here)
                else:
                    walk(v, here)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{where}[{i}]")

    walk(data, "$")
    return hits


def find_targets(kind, item_id, template_names, root=None):
    """Config that names item_id (YAML keys, dashboards) or, in a template call,
    one of template_names; item_id None scans templates only."""
    root = root or HA_CONFIG
    refs = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        in_storage = rel_dir.split(os.sep)[0] == ".storage"
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for filename in sorted(filenames):
            path = os.path.join(dirpath, filename)
            rel = os.path.relpath(path, root)
            try:
                if os.path.getsize(path) > MAX_SCAN_BYTES:
                    continue
                if in_storage:
                    if item_id and filename.startswith("lovelace"):
                        refs += [
                            {"file": rel, "path": p}
                            for p in scan_storage(path, kind, item_id)
                        ]
                elif filename.endswith((".yaml", ".yml")):
                    refs += [
                        {"file": rel, "line": n, "text": t}
                        for n, t in scan_yaml(path, kind, item_id, template_names)
                    ]
            except OSError:
                continue
    return refs


def related(kind, item_id):
    found = (
        ha_result({"type": "search/related", "item_type": kind, "item_id": item_id})
        or {}
    )
    return {k + "s": sorted(found[k]) for k in USED_BY_KINDS if found.get(k)}


def lookup_names(kind, entry):
    names = {normalize(entry_id(kind, entry)), normalize(entry.get("name", ""))}
    names |= {normalize(a) for a in entry.get("aliases") or []}
    return names - {""}


def describe_entry(kind, entry, regs):
    """The entry as printed: names instead of ids."""
    out = {f"{kind}_id": entry_id(kind, entry), "name": entry.get("name")}
    if kind == "area":
        out["floor"] = shown("floor_id", entry.get("floor_id"), regs)
        out["labels"] = names_of("label", regs.labels, entry.get("labels"))
    if kind == "floor":
        out["level"] = entry.get("level")
    if kind == "label":
        out["color"] = entry.get("color")
        out["description"] = entry.get("description")
    out["icon"] = entry.get("icon")
    if kind in ALIASED:
        out["aliases"] = sorted(entry.get("aliases") or [])
    return out


def preview(kind, entry, regs):
    item_id = entry_id(kind, entry)
    out = describe_entry(kind, entry, regs)
    out["members"] = regs.members(kind, item_id)
    out["targets"] = find_targets(kind, item_id, lookup_names(kind, entry))
    out["related"] = related(kind, item_id)
    return out


# ── list / show ──────────────────────────────────────────────────────────────


def cmd_list(args):
    regs = Registries()
    what = [args.what] if args.what else ["areas", "floors", "labels"]
    output = {}
    if "areas" in what:
        output["areas"] = []
        for a in sorted(regs.areas, key=lambda a: normalize(a["name"])):
            row = describe_entry("area", a, regs)
            members = regs.members("area", a["area_id"])
            row["devices"] = len(members["devices"])
            row["entities"] = len(members["entities"]) + len(
                members["entities_via_device"]
            )
            output["areas"].append(row)
    if "floors" in what:
        output["floors"] = []
        floors = sorted(
            regs.floors,
            key=lambda f: (f.get("level") is None, f.get("level") or 0, f["name"]),
        )
        for f in floors:
            row = describe_entry("floor", f, regs)
            row["areas"] = regs.members("floor", f["floor_id"])["areas"]
            output["floors"].append(row)
    if "labels" in what:
        output["labels"] = []
        for lab in sorted(regs.labels, key=lambda lab: normalize(lab["name"])):
            row = describe_entry("label", lab, regs)
            row.update(
                {k: len(v) for k, v in regs.members("label", lab["label_id"]).items()}
            )
            output["labels"].append(row)
    print_output(output, args.format)


def cmd_show(args):
    regs = Registries()
    entry = resolve(args.kind, regs.items(args.kind), args.ref)
    print_output(preview(args.kind, entry, regs), args.format)


# ── create / update ──────────────────────────────────────────────────────────


def resolve_ids(kind, values):
    items = entries(kind)
    return [entry_id(kind, resolve(kind, items, v)) for v in values or []]


def cmd_create(args):
    kind = args.kind
    check_name_free(kind, entries(kind), args.name)
    check_icon(args.icon)
    command = {"type": f"config/{kind}_registry/create", "name": args.name}
    if args.icon is not None:
        command["icon"] = args.icon
    if kind in ALIASED and args.alias:
        command["aliases"] = args.alias
    if kind == "area":
        if args.floor is not None:
            command["floor_id"] = resolve_ids("floor", [args.floor])[0]
        if args.label:
            command["labels"] = resolve_ids("label", args.label)
    if kind == "floor" and args.level is not None:
        command["level"] = args.level
    if kind == "label":
        check_color(args.color)
        for field in ("color", "description"):
            if getattr(args, field) is not None:
                command[field] = getattr(args, field)

    try:
        result = ha_result(command) or {}
    except RuntimeError as e:
        if "already in use" in str(e):
            raise RuntimeError(
                f"a {kind} named '{args.name}' already exists "
                "(created in the meantime?); see `ha-areas list`"
            ) from None
        raise
    new_id = result.get(f"{kind}_id")
    regs = Registries()
    entry = by_id(kind, regs.items(kind), new_id)
    output = {"created": kind, f"{kind}_id": new_id, "verified": entry is not None}
    if entry is not None:
        output[kind] = describe_entry(kind, entry, regs)
    print_output(output, args.format)
    if entry is None:
        sys.exit(1)


def planned_update(kind, entry, args, regs, notes):
    """Return {field: new_value} from the update flags; notes collects warnings."""
    changes = {}
    if args.name is not None and args.name != entry.get("name"):
        check_name_free(kind, regs.items(kind), args.name, entry_id(kind, entry))
        changes["name"] = args.name
    if args.icon is not None or args.no_icon:
        check_icon(args.icon)
        changes["icon"] = None if args.no_icon else args.icon

    if kind in ALIASED:
        aliases = set(entry.get("aliases") or [])
        for a in args.remove_alias or []:
            match = {x for x in aliases if normalize(x) == normalize(a)}
            if not match:
                raise RuntimeError(f"'{entry['name']}' has no alias '{a}'")
            aliases -= match
        aliases |= set(args.add_alias or [])
        renamed = "name" in changes and normalize(changes["name"]) != normalize(
            entry["name"]
        )
        if renamed:
            # The new name is the name now, not an alias of itself
            new = normalize(changes["name"])
            aliases = {a for a in aliases if normalize(a) != new}
        if renamed and args.keep_alias:
            aliases.add(entry["name"])
            notes.append(
                f"'{entry['name']}' stays as an alias, so lookups by that name keep "
                f"finding it; drop it later with --remove-alias '{entry['name']}'"
            )
        if aliases != set(entry.get("aliases") or []):
            changes["aliases"] = sorted(aliases)

    if kind == "area":
        if args.floor is not None or args.no_floor:
            changes["floor_id"] = (
                None
                if args.no_floor
                else entry_id("floor", resolve("floor", regs.floors, args.floor))
            )
        labels = set(entry.get("labels") or [])
        for value in args.add_label or []:
            labels.add(entry_id("label", resolve("label", regs.labels, value)))
        for value in args.remove_label or []:
            labels.discard(entry_id("label", resolve("label", regs.labels, value)))
        if labels != set(entry.get("labels") or []):
            changes["labels"] = sorted(labels)
    if kind == "floor" and args.level is not None:
        changes["level"] = args.level
    if kind == "label":
        check_color(args.color)
        for field in ("color", "description"):
            if getattr(args, field) is not None:
                changes[field] = getattr(args, field)

    return {f: v for f, v in changes.items() if not same(entry.get(f), v)}


def same(a, b):
    if isinstance(a, list) or isinstance(b, list):
        return set(a or []) == set(b or [])
    return a == b


def shown(field, value, regs):
    if field == "floor_id" and value:
        floor = by_id("floor", regs.floors, value)
        return floor["name"] if floor else value
    if field == "labels":
        return names_of("label", regs.labels, value)
    return value


def cmd_update(args):
    kind = args.kind
    regs = Registries()
    entry = resolve(kind, regs.items(kind), args.ref)
    item_id = entry_id(kind, entry)
    notes = []
    wanted = planned_update(kind, entry, args, regs, notes)
    output = {"kind": kind, f"{kind}_id": item_id}
    if not wanted:
        output["changes"] = {}
        output["note"] = "already set; nothing to do"
        print_output(output, args.format)
        return
    output["changes"] = {
        f: {"before": shown(f, entry.get(f), regs), "after": shown(f, v, regs)}
        for f, v in wanted.items()
    }
    if "name" in wanted and normalize(wanted["name"]) != normalize(entry["name"]):
        old_name_refs = find_targets(kind, None, {normalize(entry["name"])})
        if old_name_refs:
            output["templates_using_old_name"] = old_name_refs
            if normalize(entry["name"]) not in map(
                normalize, wanted.get("aliases", entry.get("aliases") or [])
            ):
                notes.append(
                    "these templates look the old name up and stop finding it "
                    "until they use the new name or the id"
                    + ("; labels have no aliases" if kind == "label" else "")
                )
    if args.dry_run:
        output["dry_run"] = True
    else:
        ha_result(
            {"type": f"config/{kind}_registry/update", f"{kind}_id": item_id, **wanted}
        )
        after = by_id(kind, entries(kind), item_id) or {}
        mismatched = [f for f, v in wanted.items() if not same(after.get(f), v)]
        output["verified"] = not mismatched
        if mismatched:
            notes.append(f"read-back differs for: {', '.join(mismatched)}")
    if notes:
        output["notes"] = notes
    print_output(output, args.format)
    if not output.get("verified", True):
        sys.exit(1)


# ── delete ───────────────────────────────────────────────────────────────────


def cmd_delete(args):
    kind = args.kind
    regs = Registries()
    entry = resolve(kind, regs.items(kind), args.ref)
    item_id = entry_id(kind, entry)
    output = preview(kind, entry, regs)
    lost = {
        "area": "the devices and entities above lose this area",
        "floor": "the areas above lose this floor",
        "label": "the entities, devices and areas above lose this label",
    }[kind]
    output["note"] = (
        f"Deleting: {lost}. `targets` keep pointing at '{item_id}' and do nothing "
        f"until a {kind} with the same name is created again (it gets the same id "
        "if it is free); `related` only uses things inside it and keeps working."
    )
    if args.dry_run:
        output["dry_run"] = True
        print_output(output, args.format)
        return
    ha_result({"type": f"config/{kind}_registry/delete", f"{kind}_id": item_id})
    output["deleted"] = by_id(kind, entries(kind), item_id) is None
    print_output(output, args.format)
    if not output["deleted"]:
        sys.exit(1)


# ── CLI ──────────────────────────────────────────────────────────────────────


def add_icon(p, update):
    if update:
        group = p.add_mutually_exclusive_group()
        group.add_argument("--icon", help="Icon, e.g. mdi:sofa")
        group.add_argument("--no-icon", action="store_true", help="Drop the icon")
    else:
        p.add_argument("--icon", help="Icon, e.g. mdi:sofa")


def add_rename(p, aliased):
    p.add_argument("--name", help="New name; the id stays")
    if aliased:
        p.add_argument(
            "--no-keep-alias",
            dest="keep_alias",
            action="store_false",
            help="Do not keep the old name as an alias",
        )
        p.add_argument("--add-alias", action="append", metavar="ALIAS")
        p.add_argument("--remove-alias", action="append", metavar="ALIAS")


def main():
    parser = argparse.ArgumentParser(
        prog="ha-areas",
        description="List, create, rename and delete areas, floors and labels.",
    )
    sub = parser.add_subparsers(dest="command", metavar="command", required=True)

    p_list = sub.add_parser(
        "list", parents=[FORMAT_PARENT], help="List areas, floors and labels"
    )
    p_list.add_argument("what", nargs="?", choices=["areas", "floors", "labels"])
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser(
        "show",
        parents=[FORMAT_PARENT],
        help="Show one area, floor or label: members and references",
    )
    p_show.add_argument("kind", choices=KINDS)
    p_show.add_argument("ref", metavar="name_or_id")
    p_show.set_defaults(func=cmd_show)

    p_create = sub.add_parser("create", help="Create an area, floor or label")
    create = p_create.add_subparsers(dest="kind", metavar="kind", required=True)
    c_area = create.add_parser("area", parents=[FORMAT_PARENT])
    c_area.add_argument("--floor", help="Floor name or id")
    c_area.add_argument("--label", action="append", metavar="LABEL")
    c_area.add_argument("--alias", action="append", metavar="ALIAS")
    c_floor = create.add_parser("floor", parents=[FORMAT_PARENT])
    c_floor.add_argument("--level", type=int, help="0 ground, 1 first, -1 basement")
    c_floor.add_argument("--alias", action="append", metavar="ALIAS")
    c_label = create.add_parser("label", parents=[FORMAT_PARENT])
    c_label.add_argument("--color", help="#RRGGBB or a theme colour such as red")
    c_label.add_argument("--description")
    for p in (c_area, c_floor, c_label):
        p.add_argument("name")
        add_icon(p, update=False)
        p.set_defaults(func=cmd_create)

    p_update = sub.add_parser("update", help="Rename or change an area, floor or label")
    update = p_update.add_subparsers(dest="kind", metavar="kind", required=True)
    u_area = update.add_parser("area", parents=[FORMAT_PARENT])
    floor = u_area.add_mutually_exclusive_group()
    floor.add_argument("--floor", help="Floor name or id")
    floor.add_argument("--no-floor", action="store_true", help="Take it off its floor")
    u_area.add_argument("--add-label", action="append", metavar="LABEL")
    u_area.add_argument("--remove-label", action="append", metavar="LABEL")
    u_floor = update.add_parser("floor", parents=[FORMAT_PARENT])
    u_floor.add_argument("--level", type=int)
    u_label = update.add_parser("label", parents=[FORMAT_PARENT])
    u_label.add_argument("--color", help="#RRGGBB or a theme colour such as red")
    u_label.add_argument("--description")
    for p, aliased in ((u_area, True), (u_floor, True), (u_label, False)):
        p.add_argument("ref", metavar="name_or_id")
        add_rename(p, aliased)
        add_icon(p, update=True)
        p.add_argument(
            "--dry-run", action="store_true", help="Show the changes without applying"
        )
        p.set_defaults(func=cmd_update)

    p_delete = sub.add_parser(
        "delete",
        parents=[FORMAT_PARENT],
        help="Delete an area, floor or label after listing what it takes along",
    )
    p_delete.add_argument("kind", choices=KINDS)
    p_delete.add_argument("ref", metavar="name_or_id")
    p_delete.add_argument(
        "--dry-run", action="store_true", help="Only list what would be lost"
    )
    p_delete.set_defaults(func=cmd_delete)

    run_cli(parser)


if __name__ == "__main__":
    main()
