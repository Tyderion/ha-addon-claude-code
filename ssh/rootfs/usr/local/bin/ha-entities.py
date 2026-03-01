#!/usr/bin/env python3
"""ha-entities — Query Home Assistant entity states, areas, domains, and scripts.

Usage:
  ha-entities list [--domain DOMAIN] [--area AREA] [--state STATE] [--limit N]
  ha-entities get <entity_id> [<entity_id> ...]
  ha-entities domains
  ha-entities areas
  ha-entities scripts
"""

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ha_lib import ha_call


def print_output(data, fmt):
    json_str = json.dumps(data, indent=2, default=str)
    if fmt == "json":
        print(json_str)
    else:
        result = subprocess.run(
            ["npx", "--yes", "@toon-format/cli"],
            input=json_str, capture_output=True, text=True,
        )
        if result.returncode != 0:
            print(json_str)  # fall back to JSON on error
        else:
            print(result.stdout, end="")

# Key attributes to extract per domain (token-efficient output)
KEY_ATTR_MAP = {
    "light": ["brightness"],
    "climate": ["current_temperature"],
    "cover": ["current_position"],
    "sensor": ["unit_of_measurement"],
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

# Attributes to strip from unknown domains
NOISE_ATTRS = frozenset({
    "friendly_name", "icon", "entity_picture", "supported_features",
    "attribution", "restored", "access_token",
})


def fetch_all_data():
    """Fetch states + 3 registries over the singleton connection."""
    states_result = ha_call({"type": "get_states"})
    entity_reg_result = ha_call({"type": "config/entity_registry/list"})
    device_reg_result = ha_call({"type": "config/device_registry/list"})
    area_reg_result = ha_call({"type": "config/area_registry/list"})

    states = states_result.get("result", [])
    entity_reg = entity_reg_result.get("result", [])
    device_reg = device_reg_result.get("result", [])
    area_reg = area_reg_result.get("result", [])

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
    # Unknown domain: return scalar non-noise attributes only
    result = {}
    for k, v in attributes.items():
        if k not in NOISE_ATTRS and isinstance(v, (str, int, float, bool)):
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
    entity_areas, _ = build_area_lookup(entity_reg, device_reg, area_reg)
    entity_names = build_entity_names(entity_reg)

    total_count = len(states)
    filtered = states

    # Apply filters
    if args.domain:
        filtered = [s for s in filtered if s["entity_id"].startswith(args.domain + ".")]
    if args.area:
        area_lower = args.area.lower()
        filtered = [s for s in filtered if entity_areas.get(s["entity_id"], "").lower() == area_lower]
    if args.state:
        filtered = [s for s in filtered if s["state"] == args.state]

    filtered_count = len(filtered)

    # Sort by entity_id for consistent output
    filtered.sort(key=lambda s: s["entity_id"])

    # Apply limit
    if args.limit and args.limit > 0:
        filtered = filtered[:args.limit]

    entities = []
    for s in filtered:
        eid = s["entity_id"]
        domain = eid.split(".")[0]
        attrs = s.get("attributes", {})
        entry = {
            "entity_id": eid,
            "name": get_name(s, entity_names),
            "area": entity_areas.get(eid),
            "state": s["state"],
            "key_attr": get_key_attr(domain, attrs),
        }
        entities.append(entry)

    output = {
        "count": total_count,
        "filtered_count": filtered_count,
        "filters": {
            "domain": args.domain,
            "area": args.area,
            "state": args.state,
        },
        "entities": entities,
    }
    print_output(output, args.format)


def cmd_get(args):
    states, entity_reg, device_reg, area_reg = fetch_all_data()
    entity_areas, _ = build_area_lookup(entity_reg, device_reg, area_reg)
    entity_names = build_entity_names(entity_reg)

    # Build state lookup
    state_map = {s["entity_id"]: s for s in states}

    results = []
    for eid in args.entity_ids:
        s = state_map.get(eid)
        if not s:
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

    data = results[0] if len(results) == 1 else results
    print_output(data, args.format)


def cmd_domains(args):
    states_result = ha_call({"type": "get_states"})
    states = states_result.get("result", [])

    domain_counts = {}
    for s in states:
        domain = s["entity_id"].split(".")[0]
        domain_counts[domain] = domain_counts.get(domain, 0) + 1

    domains = sorted(domain_counts.items(), key=lambda x: -x[1])
    output = {
        "domains": [{"domain": d, "count": c} for d, c in domains]
    }
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
    states_result = ha_call({"type": "get_states"})
    states = states_result.get("result", [])

    # Filter to script entities only
    scripts = [s for s in states if s["entity_id"].startswith("script.")]

    # Sort by friendly_name/alias for easier reading
    scripts.sort(key=lambda s: s.get("attributes", {}).get("friendly_name", s["entity_id"]).lower())

    output_scripts = []
    for s in scripts:
        attrs = s.get("attributes", {})
        output_scripts.append({
            "entity_id": s["entity_id"],
            "alias": attrs.get("friendly_name", s["entity_id"]),
            "state": s["state"],  # 'on' = running, 'off' = idle
            "mode": attrs.get("mode"),
            "last_triggered": attrs.get("last_triggered"),
        })

    output = {
        "count": len(output_scripts),
        "scripts": output_scripts,
    }
    print_output(output, args.format)


def main():
    fmt_kwargs = dict(args=["--format"], kwargs=dict(
        choices=["toon", "json"], default="toon", help="Output format (default: toon)"
    ))

    parser = argparse.ArgumentParser(
        prog="ha-entities",
        description="Query Home Assistant entity states, areas, and domains.",
    )
    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.required = True

    p_list = sub.add_parser("list", help="List entities with optional filters")
    p_list.add_argument("--domain", default=None, help="Filter by domain (e.g. light, sensor)")
    p_list.add_argument("--area", default=None, help="Filter by area name")
    p_list.add_argument("--state", default=None, help="Filter by state value (e.g. on, off)")
    p_list.add_argument("--limit", type=int, default=None, help="Limit number of results")
    p_list.add_argument(*fmt_kwargs["args"], **fmt_kwargs["kwargs"])

    p_get = sub.add_parser("get", help="Get full details for specific entities")
    p_get.add_argument("entity_ids", nargs="+", metavar="entity_id")
    p_get.add_argument(*fmt_kwargs["args"], **fmt_kwargs["kwargs"])

    p_domains = sub.add_parser("domains", help="List all domains with entity counts")
    p_domains.add_argument(*fmt_kwargs["args"], **fmt_kwargs["kwargs"])

    p_areas = sub.add_parser("areas", help="List all areas with entity counts")
    p_areas.add_argument(*fmt_kwargs["args"], **fmt_kwargs["kwargs"])

    p_scripts = sub.add_parser("scripts", help="List all scripts with their aliases")
    p_scripts.add_argument(*fmt_kwargs["args"], **fmt_kwargs["kwargs"])

    args = parser.parse_args()

    if args.command == "list":
        cmd_list(args)
    elif args.command == "get":
        cmd_get(args)
    elif args.command == "domains":
        cmd_domains(args)
    elif args.command == "areas":
        cmd_areas(args)
    elif args.command == "scripts":
        cmd_scripts(args)


if __name__ == "__main__":
    main()
