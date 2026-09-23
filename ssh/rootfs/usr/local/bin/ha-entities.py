#!/usr/bin/env python3
"""ha-entities — Query and update Home Assistant entities, areas, domains, scripts, and automations.

Usage:
  ha-entities list [--domain DOMAIN ...] [--area AREA] [--state STATE]
                   [--search TEXT] [--exclude-unavailable] [--limit N]
  ha-entities get <entity_id> [<entity_id> ...]
  ha-entities domains
  ha-entities areas
  ha-entities scripts
  ha-entities automations
  ha-entities update <entity_id> [--device] [--name NAME | --reset-name]
                     [--area AREA | --no-area] [--icon ICON | --reset-icon]
                     [--hidden | --visible] [--disable | --enable] [--dry-run]
  ha-entities rename <entity_id> <new_entity_id> [--dry-run]
  ha-entities refs <entity_id> [<entity_id> ...] [--device]

All commands accept --format yaml|json (default: yaml).

`update` and `rename` go through the entity/device registry WebSocket API,
which Home Assistant applies live; they never touch .storage files. Both
print each changed field before and after and exit 1 if the read-back
differs. `rename` lists every file that still references the old entity_id,
since Home Assistant does not rewrite YAML.

`refs` answers "what uses this entity?" from two sources: Home Assistant's
own related-items search (the UI's Related tab: automations, scripts,
scenes, groups, persons, including device triggers) and a text scan of the
YAML config plus UI-made dashboards and helpers, which also catches
templates. `--device` widens it to every entity of the device and to
references by device_id.
"""

import argparse
import json
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from ha_lib import ha_result


def print_output(data, fmt):
    if fmt == "json":
        print(json.dumps(data, indent=2, default=str))
    else:
        print(
            yaml.safe_dump(
                data, sort_keys=False, allow_unicode=True, default_flow_style=False
            ),
            end="",
        )


# Key attributes to extract per domain (token-efficient output)
KEY_ATTR_MAP = {
    "light": ["brightness"],
    "climate": ["current_temperature"],
    "cover": ["current_position"],
    "sensor": ["unit_of_measurement", "device_class"],
    "media_player": ["source"],
    "vacuum": ["fan_speed"],
    "fan": ["percentage"],
    "binary_sensor": ["device_class"],
    "automation": ["current"],
    "script": ["current"],
    "input_select": ["options"],
    "input_number": ["min", "max", "unit_of_measurement"],
    "number": ["min", "max", "unit_of_measurement"],
    "select": ["options"],
    "update": ["installed_version", "latest_version", "in_progress"],
    "event": ["event_type", "device_class"],
    "button": ["device_class"],
    "switch": [],
    "time": [],
    "image": [],
    "scene": [],
}

# Attributes kept for domains not in KEY_ATTR_MAP
FALLBACK_ATTRS = ("device_class", "unit_of_measurement", "state_class")


def fetch_all_data():
    """Fetch states + 3 registries over the singleton connection."""
    states = ha_result({"type": "get_states"}) or []
    entity_reg = ha_result({"type": "config/entity_registry/list"}) or []
    device_reg = ha_result({"type": "config/device_registry/list"}) or []
    area_reg = ha_result({"type": "config/area_registry/list"}) or []

    return states, entity_reg, device_reg, area_reg


def build_area_lookup(entity_reg, device_reg, area_reg):
    """Build entity_id -> area_name lookup.

    Resolution order:
    1. Entity has direct area_id in entity registry
    2. Entity's device has area_id in device registry
    """
    # area_id -> area_name
    area_names = {}
    for a in area_reg:
        area_names[a["area_id"]] = a.get("name", a["area_id"])

    # device_id -> area_id
    device_areas = {}
    for d in device_reg:
        if d.get("area_id"):
            device_areas[d["id"]] = d["area_id"]

    # entity_id -> area_name
    entity_areas = {}
    for e in entity_reg:
        eid = e.get("entity_id", "")
        area_id = e.get("area_id")
        if not area_id and e.get("device_id"):
            area_id = device_areas.get(e["device_id"])
        if area_id:
            entity_areas[eid] = area_names.get(area_id, area_id)

    return entity_areas, area_names


def build_entity_names(entity_reg):
    """Build entity_id -> registry name lookup."""
    names = {}
    for e in entity_reg:
        eid = e.get("entity_id", "")
        name = e.get("name") or e.get("original_name")
        if name:
            names[eid] = name
    return names


def get_key_attr(domain, attributes):
    """Extract key attributes for a domain."""
    if domain in KEY_ATTR_MAP:
        keys = KEY_ATTR_MAP[domain]
        result = {}
        for k in keys:
            if k in attributes:
                result[k] = attributes[k]
        return result
    # Unknown domain: return a fixed set of common scalar attributes only
    result = {}
    for k in FALLBACK_ATTRS:
        v = attributes.get(k)
        if isinstance(v, (str, int, float, bool)):
            result[k] = v
    return result


def get_name(state_obj, entity_names):
    """Get the best display name for an entity."""
    eid = state_obj["entity_id"]
    # Registry name takes priority
    if eid in entity_names:
        return entity_names[eid]
    # Fall back to friendly_name attribute
    return state_obj.get("attributes", {}).get("friendly_name", eid)


def cmd_list(args):
    states, entity_reg, device_reg, area_reg = fetch_all_data()
    entity_areas, area_names = build_area_lookup(entity_reg, device_reg, area_reg)
    entity_names = build_entity_names(entity_reg)

    total_count = len(states)
    filtered = states

    # Apply filters (all case-insensitive)
    if args.domain:
        domains = {d.lower() for d in args.domain}
        filtered = [s for s in filtered if s["entity_id"].split(".")[0] in domains]
    if args.area:
        area_lower = args.area.lower()
        filtered = [
            s
            for s in filtered
            if entity_areas.get(s["entity_id"], "").lower() == area_lower
        ]
    if args.state:
        state_lower = args.state.lower()
        filtered = [s for s in filtered if s["state"].lower() == state_lower]
    if args.search:
        needle = args.search.lower()
        filtered = [
            s
            for s in filtered
            if needle in s["entity_id"].lower()
            or needle in get_name(s, entity_names).lower()
        ]
    if args.exclude_unavailable:
        filtered = [s for s in filtered if s["state"] not in ("unavailable", "unknown")]

    filtered_count = len(filtered)

    # Sort by entity_id for consistent output
    filtered.sort(key=lambda s: s["entity_id"])

    # Apply limit (--limit 0 means unlimited)
    if args.limit > 0:
        filtered = filtered[: args.limit]

    entities = []
    for s in filtered:
        eid = s["entity_id"]
        domain = eid.split(".")[0]
        attrs = s.get("attributes", {})
        entry = {
            "entity_id": eid,
            "name": get_name(s, entity_names),
            "state": s["state"],
        }
        area = entity_areas.get(eid)
        if area:
            entry["area"] = area
        key_attr = get_key_attr(domain, attrs)
        if key_attr:
            entry["key_attr"] = key_attr
        entities.append(entry)

    output = {
        "total": total_count,
        "filtered_count": filtered_count,
        "returned": len(entities),
        "truncated": len(entities) < filtered_count,
        "entities": entities,
    }
    if filtered_count == 0:
        hints = []
        if args.domain:
            available = sorted({s["entity_id"].split(".")[0] for s in states})
            hints.append(f"available domains: {', '.join(available)}")
        if args.area:
            hints.append(f"available areas: {', '.join(sorted(area_names.values()))}")
        if hints:
            output["hint"] = "; ".join(hints)
    print_output(output, args.format)


def cmd_get(args):
    states, entity_reg, device_reg, area_reg = fetch_all_data()
    entity_areas, _ = build_area_lookup(entity_reg, device_reg, area_reg)
    entity_names = build_entity_names(entity_reg)

    # Build state lookup
    state_map = {s["entity_id"]: s for s in states}

    results = []
    missing = []
    for eid in args.entity_ids:
        s = state_map.get(eid)
        if not s:
            missing.append(eid)
            print(f"Warning: entity '{eid}' not found", file=sys.stderr)
            continue
        domain = eid.split(".")[0]
        entry = {
            "entity_id": eid,
            "state": s["state"],
            "name": get_name(s, entity_names),
            "area": entity_areas.get(eid),
            "domain": domain,
            "last_changed": s.get("last_changed"),
            "last_updated": s.get("last_updated"),
            "attributes": s.get("attributes", {}),
        }
        results.append(entry)

    if not results:
        print(
            f"Error: no matching entities: {', '.join(missing)} "
            "(try `ha-entities list --search TEXT`)",
            file=sys.stderr,
        )
        sys.exit(1)
    print_output(results, args.format)


def cmd_domains(args):
    states = ha_result({"type": "get_states"}) or []

    domain_counts = {}
    for s in states:
        domain = s["entity_id"].split(".")[0]
        domain_counts[domain] = domain_counts.get(domain, 0) + 1

    domains = sorted(domain_counts.items(), key=lambda x: -x[1])
    output = {"domains": [{"domain": d, "count": c} for d, c in domains]}
    print_output(output, args.format)


def cmd_areas(args):
    states, entity_reg, device_reg, area_reg = fetch_all_data()
    entity_areas, area_names = build_area_lookup(entity_reg, device_reg, area_reg)

    # Count entities per area
    area_counts = {}
    for s in states:
        area = entity_areas.get(s["entity_id"])
        if area:
            area_counts[area] = area_counts.get(area, 0) + 1

    # Build output with area_id
    area_id_map = {a.get("name", a["area_id"]): a["area_id"] for a in area_reg}

    areas = sorted(area_counts.items(), key=lambda x: -x[1])
    output = {
        "areas": [
            {
                "area_id": area_id_map.get(name, name),
                "name": name,
                "entity_count": count,
            }
            for name, count in areas
        ]
    }
    print_output(output, args.format)


def cmd_scripts(args):
    states = ha_result({"type": "get_states"}) or []

    # Filter to script entities only
    scripts = [s for s in states if s["entity_id"].startswith("script.")]

    # Sort by friendly_name/alias for easier reading
    scripts.sort(
        key=lambda s: (
            s.get("attributes", {}).get("friendly_name", s["entity_id"]).lower()
        )
    )

    output_scripts = []
    for s in scripts:
        attrs = s.get("attributes", {})
        output_scripts.append(
            {
                "entity_id": s["entity_id"],
                "alias": attrs.get("friendly_name", s["entity_id"]),
                "state": s["state"],  # 'on' = running, 'off' = idle
                "mode": attrs.get("mode"),
                "last_triggered": attrs.get("last_triggered"),
            }
        )

    output = {
        "count": len(output_scripts),
        "scripts": output_scripts,
    }
    print_output(output, args.format)


def cmd_automations(args):
    states = ha_result({"type": "get_states"}) or []

    # Filter to automation entities only
    automations = [s for s in states if s["entity_id"].startswith("automation.")]

    # Sort by friendly_name/alias for easier reading
    automations.sort(
        key=lambda s: (
            s.get("attributes", {}).get("friendly_name", s["entity_id"]).lower()
        )
    )

    output_automations = []
    for s in automations:
        attrs = s.get("attributes", {})
        output_automations.append(
            {
                "entity_id": s["entity_id"],
                "alias": attrs.get("friendly_name", s["entity_id"]),
                "state": s["state"],  # 'on' = enabled, 'off' = disabled
                "mode": attrs.get("mode"),
                "last_triggered": attrs.get("last_triggered"),
            }
        )

    output = {
        "count": len(output_automations),
        "automations": output_automations,
    }
    print_output(output, args.format)


# ── update / rename ──────────────────────────────────────────────────────────

HA_CONFIG = "/homeassistant"
ENTITY_ID_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
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
# .storage files worth scanning: UI-made dashboards and helpers (groups,
# template sensors, ...) reference entity_ids there
STORAGE_PREFIXES = ("lovelace", "core.config_entries")
MAX_SCAN_BYTES = 5 * 1024 * 1024


def get_registry_entry(entity_id):
    """Return the entity registry entry, or exit with an explanation."""
    try:
        return ha_result({"type": "config/entity_registry/get", "entity_id": entity_id})
    except RuntimeError as e:
        if "not_found" not in str(e) and "not found" not in str(e).lower():
            raise
    states = ha_result({"type": "get_states"}) or []
    if any(s["entity_id"] == entity_id for s in states):
        raise RuntimeError(
            f"'{entity_id}' has no unique_id, so it is not in the entity registry and "
            "cannot be changed here. Change it where it is defined (its YAML, or "
            "customize.yaml for friendly_name/icon)."
        )
    raise RuntimeError(
        f"entity '{entity_id}' not found (try `ha-entities list --search TEXT`)"
    )


def resolve_area(area_reg, value):
    """Map an area name or area_id (case-insensitive) to its area_id."""
    wanted = value.strip().lower()
    for a in area_reg:
        if a["area_id"].lower() == wanted or a.get("name", "").lower() == wanted:
            return a["area_id"]
    names = ", ".join(sorted(a.get("name", a["area_id"]) for a in area_reg))
    raise RuntimeError(
        f"no area '{value}'. Existing areas: {names}. "
        "Create new areas in Settings → Areas."
    )


def area_label(area_reg, area_id):
    for a in area_reg:
        if a["area_id"] == area_id:
            return a.get("name", area_id)
    return area_id


def planned_changes(args, area_reg, device_mode):
    """Return {registry_field: new_value} from the command-line flags."""
    changes = {}
    if args.name is not None or args.reset_name:
        field = "name_by_user" if device_mode else "name"
        changes[field] = None if args.reset_name else args.name
    if args.area is not None or args.no_area:
        changes["area_id"] = None if args.no_area else resolve_area(area_reg, args.area)
    entity_only = {
        "icon": args.icon is not None or args.reset_icon,
        "hidden_by": args.hidden or args.visible,
        "disabled_by": args.disable or args.enable,
    }
    if device_mode and any(entity_only.values()):
        raise RuntimeError(
            "--icon/--hidden/--visible/--disable/--enable apply to the entity; "
            "drop --device for those"
        )
    if entity_only["icon"]:
        changes["icon"] = None if args.reset_icon else args.icon
    if entity_only["hidden_by"]:
        changes["hidden_by"] = "user" if args.hidden else None
    if entity_only["disabled_by"]:
        changes["disabled_by"] = "user" if args.disable else None
    if not changes:
        raise RuntimeError("nothing to change: pass at least one of the update flags")
    return changes


def describe(field, value, area_reg):
    if field == "area_id" and value:
        return area_label(area_reg, value)
    return value


def cmd_update(args):
    entry = get_registry_entry(args.entity_id)
    area_reg = ha_result({"type": "config/area_registry/list"}) or []
    device_mode = args.device

    if device_mode:
        if not entry.get("device_id"):
            raise RuntimeError(f"'{args.entity_id}' does not belong to a device")
        devices = ha_result({"type": "config/device_registry/list"}) or []
        target = next((d for d in devices if d["id"] == entry["device_id"]), None)
        if target is None:
            raise RuntimeError(f"device {entry['device_id']} not found")
        command = {"type": "config/device_registry/update", "device_id": target["id"]}
    else:
        target = entry
        command = {"type": "config/entity_registry/update", "entity_id": args.entity_id}

    wanted = planned_changes(args, area_reg, device_mode)
    changes = {}
    for field, value in wanted.items():
        before = target.get(field)
        if before == value:
            continue
        changes[field] = {
            "before": describe(field, before, area_reg),
            "after": describe(field, value, area_reg),
        }

    output = {
        "entity_id": args.entity_id,
        "target": "device" if device_mode else "entity",
    }
    if device_mode:
        output["device"] = target.get("name_by_user") or target.get("name")
    notes = []

    if not changes:
        output["changes"] = {}
        output["note"] = "already set; nothing to do"
        print_output(output, args.format)
        return

    if args.dry_run:
        output["dry_run"] = True
        output["changes"] = changes
        print_output(output, args.format)
        return

    result = ha_result({**command, **{f: wanted[f] for f in changes}}) or {}
    after_entry = result.get("entity_entry", result) if not device_mode else result
    mismatched = [f for f in changes if after_entry.get(f) != wanted[f]]
    output["changes"] = changes
    output["verified"] = not mismatched

    if "area_id" in changes:
        if device_mode and entry.get("area_id"):
            notes.append(
                f"the entity keeps its own area "
                f"'{area_label(area_reg, entry['area_id'])}'; run "
                "`update --no-area` on it to inherit the device's area"
            )
        if not device_mode and wanted["area_id"] is None and entry.get("device_id"):
            notes.append("the entity now inherits its device's area, if it has one")
    if result.get("require_restart"):
        notes.append("Home Assistant needs a restart for this to take effect")
    elif result.get("reload_delay"):
        notes.append(
            f"the integration reloads in about {result['reload_delay']}s "
            "to apply the enable/disable"
        )
    if mismatched:
        notes.append(f"read-back differs for: {', '.join(mismatched)}")
    if notes:
        output["notes"] = notes

    print_output(output, args.format)
    if mismatched:
        sys.exit(1)


def find_references(entity_id, root=None):
    """Return [{file, line, text}] for each line that names entity_id."""
    root = root or HA_CONFIG
    pattern = re.compile(r"(?<![\w.])" + re.escape(entity_id) + r"(?![\w])")
    refs = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel_dir = os.path.relpath(dirpath, root)
        in_storage = rel_dir.split(os.sep)[0] == ".storage"
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        for filename in sorted(filenames):
            if in_storage:
                if not filename.startswith(STORAGE_PREFIXES):
                    continue
            elif not filename.endswith((".yaml", ".yml")):
                continue
            path = os.path.join(dirpath, filename)
            try:
                if os.path.getsize(path) > MAX_SCAN_BYTES:
                    continue
                with open(path, encoding="utf-8", errors="replace") as f:
                    for lineno, line in enumerate(f, 1):
                        if pattern.search(line):
                            refs.append(
                                {
                                    "file": os.path.relpath(path, root),
                                    "line": lineno,
                                    "text": line.strip()[:160],
                                }
                            )
            except OSError:
                continue
    return refs


# Related-item kinds that mean "this uses the entity"; the search also
# returns upward relations (its device, area, integration) which do not
USED_BY_KINDS = ("automation", "script", "scene", "group", "person")


def used_by(item_type, item_id, names):
    """Return {kind: [{entity_id, name}]} from HA's related-items search."""
    related = (
        ha_result(
            {"type": "search/related", "item_type": item_type, "item_id": item_id}
        )
        or {}
    )
    result = {}
    for kind in USED_BY_KINDS:
        ids = sorted(related.get(kind) or [])
        if ids:
            result[kind + "s"] = [
                {"entity_id": i, "name": names.get(i, i)} for i in ids
            ]
    return result


def state_names():
    return {
        s["entity_id"]: s.get("attributes", {}).get("friendly_name", s["entity_id"])
        for s in ha_result({"type": "get_states"}) or []
    }


def references_for(item_type, item_id, names):
    """Combine HA's related search with the config text scan."""
    refs = used_by(item_type, item_id, names)
    files = find_references(item_id)
    if files:
        refs["files"] = files
    return refs


def count_refs(refs):
    return sum(len(v) for v in refs.values())


def cmd_refs(args):
    names = state_names()
    registry = {
        e["entity_id"]: e
        for e in ha_result({"type": "config/entity_registry/list"}) or []
    }
    output = {}

    if args.device:
        devices = {
            d["id"]: d for d in ha_result({"type": "config/device_registry/list"}) or []
        }
        device_ids = []
        for eid in args.entity_ids:
            entry = registry.get(eid)
            if entry is None:
                get_registry_entry(eid)  # raises with the right explanation
            if not entry.get("device_id"):
                raise RuntimeError(f"'{eid}' does not belong to a device")
            if entry["device_id"] not in device_ids:
                device_ids.append(entry["device_id"])
        output["devices"] = []
        for device_id in device_ids:
            device = devices.get(device_id, {})
            entities = sorted(
                e["entity_id"]
                for e in registry.values()
                if e.get("device_id") == device_id
            )
            device_refs = references_for("device", device_id, names)
            output["devices"].append(
                {
                    "device_id": device_id,
                    "name": device.get("name_by_user") or device.get("name"),
                    "references": device_refs,
                    "entities": {
                        eid: references_for("entity", eid, names) for eid in entities
                    },
                }
            )
        total = sum(
            count_refs(d["references"])
            + sum(count_refs(r) for r in d["entities"].values())
            for d in output["devices"]
        )
    else:
        known = set(registry) | set(names)
        for eid in args.entity_ids:
            if eid not in known:
                raise RuntimeError(
                    f"entity '{eid}' not found (try `ha-entities list --search TEXT`)"
                )
        output["entities"] = {
            eid: references_for("entity", eid, names) for eid in args.entity_ids
        }
        total = sum(count_refs(r) for r in output["entities"].values())

    output["total_references"] = total
    output["note"] = (
        "automations/scripts/scenes/groups/persons come from Home Assistant's "
        "related-items search; files is a text scan of the YAML config and of "
        "UI-made dashboards and helpers under .storage, which also finds templates. "
        "The same automation can appear in both."
    )
    print_output(output, args.format)


def cmd_rename(args):
    old, new = args.entity_id, args.new_entity_id
    if not ENTITY_ID_RE.match(new):
        raise RuntimeError(
            f"'{new}' is not a valid entity_id (lowercase domain.object_id, "
            "letters, digits and underscores)"
        )
    if new.split(".")[0] != old.split(".")[0]:
        raise RuntimeError("the domain cannot change; keep the part before the dot")
    if new == old:
        raise RuntimeError("new entity_id is the same as the old one")

    get_registry_entry(old)
    taken = {
        e["entity_id"] for e in ha_result({"type": "config/entity_registry/list"}) or []
    }
    taken |= {s["entity_id"] for s in ha_result({"type": "get_states"}) or []}
    if new in taken:
        raise RuntimeError(f"'{new}' already exists")

    refs = find_references(old)
    output = {"entity_id": old, "new_entity_id": new, "references": refs}
    related = used_by("entity", old, state_names())
    if related:
        output["used_by"] = related
    storage_refs = [r for r in refs if r["file"].startswith(".storage")]

    if args.dry_run:
        output["dry_run"] = True
        print_output(output, args.format)
        return

    result = (
        ha_result(
            {
                "type": "config/entity_registry/update",
                "entity_id": old,
                "new_entity_id": new,
            }
        )
        or {}
    )
    after = result.get("entity_entry", result)
    output["verified"] = after.get("entity_id") == new
    notes = []
    if refs:
        notes.append(
            f"{len(refs)} reference(s) still use '{old}'; Home Assistant does not "
            "rewrite YAML. Update the YAML files, then run ha-reload."
        )
    if storage_refs:
        notes.append(
            "references under .storage come from UI-made dashboards or helpers: "
            "fix dashboards with ha-dashboard and helpers in the UI, never by hand"
        )
    if notes:
        output["notes"] = notes
    print_output(output, args.format)
    if not output["verified"]:
        sys.exit(1)


def main():
    fmt_parent = argparse.ArgumentParser(add_help=False)
    fmt_parent.add_argument(
        "--format",
        choices=["yaml", "json"],
        default="yaml",
        help="Output format (default: yaml)",
    )

    parser = argparse.ArgumentParser(
        prog="ha-entities",
        description="Query Home Assistant entity states, areas, and domains.",
    )
    sub = parser.add_subparsers(dest="command", metavar="command", required=True)

    p_list = sub.add_parser(
        "list", parents=[fmt_parent], help="List entities with optional filters"
    )
    p_list.add_argument(
        "--domain",
        nargs="+",
        default=None,
        metavar="DOMAIN",
        help="Filter by one or more domains (e.g. light sensor)",
    )
    p_list.add_argument("--area", default=None, help="Filter by area name")
    p_list.add_argument(
        "--state", default=None, help="Filter by state value (e.g. on, off)"
    )
    p_list.add_argument(
        "--search",
        default=None,
        metavar="TEXT",
        help="Filter by substring of entity_id or name",
    )
    p_list.add_argument(
        "--exclude-unavailable",
        action="store_true",
        help="Skip entities with state unavailable/unknown",
    )
    p_list.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Limit number of results (default: 100, 0 = unlimited)",
    )
    p_list.set_defaults(func=cmd_list)

    p_get = sub.add_parser(
        "get", parents=[fmt_parent], help="Get full details for specific entities"
    )
    p_get.add_argument("entity_ids", nargs="+", metavar="entity_id")
    p_get.set_defaults(func=cmd_get)

    p_domains = sub.add_parser(
        "domains", parents=[fmt_parent], help="List all domains with entity counts"
    )
    p_domains.set_defaults(func=cmd_domains)

    p_areas = sub.add_parser(
        "areas", parents=[fmt_parent], help="List all areas with entity counts"
    )
    p_areas.set_defaults(func=cmd_areas)

    p_scripts = sub.add_parser(
        "scripts", parents=[fmt_parent], help="List all scripts with their aliases"
    )
    p_scripts.set_defaults(func=cmd_scripts)

    p_automations = sub.add_parser(
        "automations",
        parents=[fmt_parent],
        help="List all automations with their aliases",
    )
    p_automations.set_defaults(func=cmd_automations)

    p_update = sub.add_parser(
        "update",
        parents=[fmt_parent],
        help="Change an entity's (or its device's) name, area, icon, visibility",
    )
    p_update.add_argument("entity_id")
    p_update.add_argument(
        "--device",
        action="store_true",
        help="Apply --name/--area to the entity's device instead of the entity",
    )
    name = p_update.add_mutually_exclusive_group()
    name.add_argument("--name", help="Set the display name")
    name.add_argument(
        "--reset-name",
        action="store_true",
        help="Drop the custom name and use the integration's own",
    )
    area = p_update.add_mutually_exclusive_group()
    area.add_argument("--area", help="Area name or area_id")
    area.add_argument(
        "--no-area",
        action="store_true",
        help="Clear the area (an entity then inherits its device's area)",
    )
    icon = p_update.add_mutually_exclusive_group()
    icon.add_argument("--icon", help="Icon, e.g. mdi:lamp")
    icon.add_argument("--reset-icon", action="store_true", help="Drop a custom icon")
    hidden = p_update.add_mutually_exclusive_group()
    hidden.add_argument("--hidden", action="store_true", help="Hide the entity")
    hidden.add_argument("--visible", action="store_true", help="Unhide the entity")
    disabled = p_update.add_mutually_exclusive_group()
    disabled.add_argument("--disable", action="store_true", help="Disable the entity")
    disabled.add_argument("--enable", action="store_true", help="Enable the entity")
    p_update.add_argument(
        "--dry-run", action="store_true", help="Show the changes without applying"
    )
    p_update.set_defaults(func=cmd_update)

    p_rename = sub.add_parser(
        "rename",
        parents=[fmt_parent],
        help="Change an entity_id and list the references that still use the old one",
    )
    p_rename.add_argument("entity_id")
    p_rename.add_argument("new_entity_id")
    p_rename.add_argument(
        "--dry-run",
        action="store_true",
        help="Only list the references; do not rename",
    )
    p_rename.set_defaults(func=cmd_rename)

    p_refs = sub.add_parser(
        "refs",
        parents=[fmt_parent],
        help="Show what uses an entity: automations, scripts, scenes, "
        "dashboards, templates",
    )
    p_refs.add_argument("entity_ids", nargs="+", metavar="entity_id")
    p_refs.add_argument(
        "--device",
        action="store_true",
        help="Cover every entity of the given entities' devices, and device_id "
        "references (device triggers and actions)",
    )
    p_refs.set_defaults(func=cmd_refs)

    args = parser.parse_args()

    try:
        args.func(args)
    except (RuntimeError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
