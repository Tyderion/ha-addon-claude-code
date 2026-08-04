#!/usr/bin/env python3
"""ha-entities — Query Home Assistant entity states, areas, domains, scripts, and automations.

Usage:
  ha-entities list [--domain DOMAIN ...] [--area AREA] [--state STATE]
                   [--search TEXT] [--exclude-unavailable] [--limit N]
  ha-entities get <entity_id> [<entity_id> ...]
  ha-entities domains
  ha-entities areas
  ha-entities scripts
  ha-entities automations

All commands accept --format yaml|json (default: yaml).
"""

import argparse
import json
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from ha_lib import ha_call


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


def ha_result(command: dict):
    """Run a WS command and return its result, exiting loudly on failure."""
    resp = ha_call(command)
    if not resp.get("success"):
        error = resp.get("error", resp)
        msg = error.get("message", error) if isinstance(error, dict) else error
        print(f"Error: '{command['type']}' failed: {msg}", file=sys.stderr)
        sys.exit(1)
    return resp.get("result", [])


def fetch_all_data():
    """Fetch states + 3 registries over the singleton connection."""
    states = ha_result({"type": "get_states"})
    entity_reg = ha_result({"type": "config/entity_registry/list"})
    device_reg = ha_result({"type": "config/device_registry/list"})
    area_reg = ha_result({"type": "config/area_registry/list"})

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
    states = ha_result({"type": "get_states"})

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
    states = ha_result({"type": "get_states"})

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
    states = ha_result({"type": "get_states"})

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

    args = parser.parse_args()

    try:
        args.func(args)
    except (RuntimeError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
