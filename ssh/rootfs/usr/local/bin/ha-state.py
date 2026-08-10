#!/usr/bin/env python3
"""ha-state — Read and mutate Home Assistant virtual state safely.

Usage:
  ha-state show <entity_id>
  ha-state set <entity_id> <value> [--duration H:MM:SS] [--timeout N]

Owns value-settable state: helpers (input_boolean, input_select,
input_number, input_text, input_datetime), counter, timer, the var
integration, and the device-backed select/number/text domains. `show`
prints the current state plus exactly which values `set` accepts;
`set` resolves the right service, validates the value against the
entity's own constraints, calls it, then reads the state back and
reports before/after with a verified flag (exit 1 on a mismatch).

Device command domains (light, switch, climate, ...) belong to
`ha-service call`; this tool refuses them. It never uses HA's raw
set-state API — every mutation goes through a real service call.

All commands accept --format yaml|json (default: yaml).
"""

import argparse
import difflib
import json
import os
import re
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from ha_lib import ha_call, ha_result

BOOL_VALUES = ("on", "off", "toggle")
TIMER_SERVICES = {
    "start": "active",
    "pause": "paused",
    "cancel": "idle",
    "finish": "idle",
    "change": "active",
}
COUNTER_KEYWORDS = ("increment", "decrement", "reset")


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


def get_states():
    return ha_result({"type": "get_states"}) or []


def find_entity(entity_id, states):
    for state in states:
        if state["entity_id"] == entity_id:
            return state
    existing = [s["entity_id"] for s in states]
    near = difflib.get_close_matches(entity_id, existing, n=3, cutoff=0.6)
    hint = f" — did you mean: {', '.join(near)}?" if near else ""
    raise RuntimeError(
        f"no entity '{entity_id}'{hint} "
        "(find entities with `ha-entities list --search ...`)"
    )


def parse_json_value(value):
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def attr_subset(attrs, keys):
    return {key: attrs[key] for key in keys if attrs.get(key) is not None}


def matches_number(after, expected):
    try:
        return abs(float(after) - expected) < 1e-9
    except (TypeError, ValueError):
        return False


# Each builder validates the value against the live entity and returns
# (service, service_data, expected) — expected is a state string, a
# predicate over the read-back state, or None when HA normalizes the
# stored value (then verification is skipped).


def build_boolean(state, value, args):
    v = value.lower()
    if v not in BOOL_VALUES:
        raise RuntimeError(f"'{state['entity_id']}' takes one of: on, off, toggle")
    if v == "toggle":
        flipped = {"on": "off", "off": "on"}.get(state.get("state"))
        return "toggle", {}, flipped
    return f"turn_{v}", {}, v


def build_select(state, value, args):
    options = state.get("attributes", {}).get("options") or []
    if value not in options:
        raise RuntimeError(f"invalid option '{value}' — allowed: {', '.join(options)}")
    return "select_option", {"option": value}, value


def build_number(state, value, args):
    attrs = state.get("attributes", {})
    try:
        num = float(value)
    except ValueError:
        raise RuntimeError(f"'{value}' is not a number") from None
    lo, hi = attrs.get("min"), attrs.get("max")
    if (lo is not None and num < lo) or (hi is not None and num > hi):
        raise RuntimeError(f"{num} is outside the allowed range {lo}..{hi}")
    return "set_value", {"value": num}, lambda after: matches_number(after, num)


def build_text(state, value, args):
    attrs = state.get("attributes", {})
    lo, hi = attrs.get("min") or 0, attrs.get("max")
    if len(value) < lo or (hi is not None and len(value) > hi):
        raise RuntimeError(f"text length {len(value)} is outside {lo}..{hi}")
    pattern = attrs.get("pattern")
    if pattern and not re.fullmatch(pattern, value):
        raise RuntimeError(f"value does not match the required pattern: {pattern}")
    return "set_value", {"value": value}, value


def build_datetime(state, value, args):
    attrs = state.get("attributes", {})
    if attrs.get("has_date") and attrs.get("has_time"):
        key = "datetime"
    elif attrs.get("has_date"):
        key = "date"
    else:
        key = "time"
    return "set_datetime", {key: value}, None


def build_counter(state, value, args):
    if value.lstrip("+-").isdigit():
        return "set_value", {"value": int(value)}, str(int(value))
    if value in COUNTER_KEYWORDS:
        return value, {}, None
    raise RuntimeError(
        "counter takes an integer or one of: " + ", ".join(COUNTER_KEYWORDS)
    )


def build_timer(state, value, args):
    if value not in TIMER_SERVICES:
        raise RuntimeError("timer takes one of: " + ", ".join(TIMER_SERVICES))
    data = {}
    if args.duration:
        if value not in ("start", "change"):
            raise RuntimeError("--duration only applies to start and change")
        data["duration"] = args.duration
    return value, data, TIMER_SERVICES[value]


def build_var(state, value, args):
    data = {"entity_id": state["entity_id"], "value": parse_json_value(value)}
    return "set", data, None


BUILDERS = {
    "input_boolean": build_boolean,
    "input_select": build_select,
    "select": build_select,
    "input_number": build_number,
    "number": build_number,
    "input_text": build_text,
    "text": build_text,
    "input_datetime": build_datetime,
    "counter": build_counter,
    "timer": build_timer,
    "var": build_var,
}


def require_domain(entity_id):
    domain = entity_id.partition(".")[0]
    if domain not in BUILDERS:
        raise RuntimeError(
            f"'{domain}' is not a virtual-state domain — supported: "
            f"{', '.join(sorted(BUILDERS))}. Device commands go through "
            "`ha-service call`; state reads through `ha-entities`."
        )
    return domain


def settable_spec(domain, attrs):
    if domain == "input_boolean":
        return {"values": list(BOOL_VALUES)}
    if domain in ("input_select", "select"):
        return {"options": attrs.get("options") or []}
    if domain in ("input_number", "number"):
        return attr_subset(attrs, ("min", "max", "step", "mode", "unit_of_measurement"))
    if domain in ("input_text", "text"):
        return attr_subset(attrs, ("min", "max", "pattern", "mode"))
    if domain == "input_datetime":
        return attr_subset(attrs, ("has_date", "has_time"))
    if domain == "counter":
        spec = attr_subset(attrs, ("initial", "minimum", "maximum", "step"))
        spec["values"] = "an integer, or " + " / ".join(COUNTER_KEYWORDS)
        return spec
    if domain == "timer":
        spec = attr_subset(attrs, ("duration", "remaining"))
        spec["values"] = list(TIMER_SERVICES)
        return spec
    return {"values": "free-form; JSON-parsed when possible"}


def cmd_show(args):
    domain = require_domain(args.entity_id)
    state = find_entity(args.entity_id, get_states())
    attrs = state.get("attributes", {})
    output = {
        "entity": args.entity_id,
        "name": attrs.get("friendly_name") or args.entity_id,
        "state": state.get("state"),
        "settable": settable_spec(domain, attrs),
    }
    print_output(output, args.format)


def cmd_set(args):
    domain = require_domain(args.entity_id)
    state = find_entity(args.entity_id, get_states())
    before = state.get("state")
    service, data, expected = BUILDERS[domain](state, args.value, args)

    command = {"type": "call_service", "domain": domain, "service": service}
    if data:
        command["service_data"] = data
    if domain != "var":  # var.set addresses the entity in service data
        command["target"] = {"entity_id": [args.entity_id]}
    ha_call(command, timeout=args.timeout)

    after = None
    for current in get_states():
        if current["entity_id"] == args.entity_id:
            after = current.get("state")
            break

    output = {
        "entity": args.entity_id,
        "called": f"{domain}.{service}",
        "before": before,
        "after": after,
    }
    shown_data = {k: v for k, v in data.items() if k != "entity_id"}
    if shown_data:
        output["data"] = shown_data
    if expected is not None:
        ok = expected(after) if callable(expected) else after == expected
        output["verified"] = bool(ok)
        if not ok:
            output["note"] = "state after the call does not match the requested value"
    print_output(output, args.format)
    if output.get("verified") is False:
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
        prog="ha-state",
        description="Read and mutate Home Assistant virtual state safely.",
    )
    sub = parser.add_subparsers(dest="command", metavar="command", required=True)

    p_show = sub.add_parser(
        "show", parents=[fmt_parent], help="Current state and accepted values"
    )
    p_show.add_argument("entity_id", help="Entity in a virtual-state domain")
    p_show.set_defaults(func=cmd_show)

    p_set = sub.add_parser(
        "set", parents=[fmt_parent], help="Set a value (validated, then verified)"
    )
    p_set.add_argument("entity_id", help="Entity in a virtual-state domain")
    p_set.add_argument("value", help="New value, or a keyword for timer/counter")
    p_set.add_argument(
        "--duration",
        default=None,
        metavar="H:MM:SS",
        help="Duration for timer start/change",
    )
    p_set.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        metavar="N",
        help="Seconds to wait for the call (default: 60)",
    )
    p_set.set_defaults(func=cmd_set)

    args = parser.parse_args()

    try:
        args.func(args)
    except (RuntimeError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
