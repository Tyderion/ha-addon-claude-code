#!/usr/bin/env python3
"""ha-trace — Inspect Home Assistant automation and script traces.

Usage:
  ha-trace list
  ha-trace runs <target>
  ha-trace show <target> [--run RUN_ID] [--full]

<target> is an entity_id (automation.morning_lights, script.wake_up) or a
friendly name/alias. Traces exist only for runs that actually started; HA
stores the last few runs per item and clears them on Core restart.

All commands accept --format yaml|json (default: yaml).
"""

import argparse
import json
import os
import sys
from datetime import datetime

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


def _parse_ts(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _alias(state_obj):
    attrs = state_obj.get("attributes", {})
    return attrs.get("friendly_name", state_obj["entity_id"])


def fetch_traceables():
    """Return automation and script state objects, keyed for trace lookups.

    Automation traces are keyed by the automation's internal `id` attribute
    (not the entity_id); script traces are keyed by the entity object_id.
    """
    states = ha_result({"type": "get_states"}) or []
    automations = [s for s in states if s["entity_id"].startswith("automation.")]
    scripts = [s for s in states if s["entity_id"].startswith("script.")]
    return automations, scripts


def resolve_target(target):
    """Resolve entity_id or friendly name to (domain, item_id, state_obj)."""
    automations, scripts = fetch_traceables()

    if target.startswith("automation."):
        for s in automations:
            if s["entity_id"] == target:
                item_id = s.get("attributes", {}).get("id")
                if not item_id:
                    raise RuntimeError(
                        f"'{target}' has no internal id (YAML automation without "
                        "an `id:` field) — HA does not record traces for it. "
                        "Add a unique `id:` to the automation and reload."
                    )
                return "automation", item_id, s
        raise RuntimeError(
            f"no automation with entity_id '{target}' — run `ha-trace list`"
        )

    if target.startswith("script."):
        for s in scripts:
            if s["entity_id"] == target:
                return "script", target.split(".", 1)[1], s
        raise RuntimeError(f"no script with entity_id '{target}' — run `ha-trace list`")

    # Friendly-name / fragment search over both domains
    needle = target.lower()
    candidates = []
    for domain, objs in (("automation", automations), ("script", scripts)):
        for s in objs:
            if needle == _alias(s).lower():
                candidates.append((domain, s, True))
            elif needle in _alias(s).lower() or needle in s["entity_id"].lower():
                candidates.append((domain, s, False))

    exact = [c for c in candidates if c[2]]
    if len(exact) == 1:
        candidates = exact
    if not candidates:
        raise RuntimeError(f"nothing matches '{target}' — run `ha-trace list`")
    if len(candidates) > 1:
        ids = ", ".join(s["entity_id"] for _, s, _ in candidates)
        raise RuntimeError(f"'{target}' is ambiguous, matches: {ids}")

    domain, s, _ = candidates[0]
    if domain == "script":
        return domain, s["entity_id"].split(".", 1)[1], s
    item_id = s.get("attributes", {}).get("id")
    if not item_id:
        raise RuntimeError(
            f"'{s['entity_id']}' has no internal id (YAML automation without "
            "an `id:` field) — HA does not record traces for it."
        )
    return domain, item_id, s


def _run_summary(trace):
    entry = {
        "run_id": trace.get("run_id"),
        "start": trace.get("timestamp", {}).get("start"),
        "finish": trace.get("timestamp", {}).get("finish"),
        "outcome": trace.get("script_execution"),
        "last_step": trace.get("last_step"),
    }
    if trace.get("trigger"):
        entry["trigger"] = trace["trigger"]
    if trace.get("error"):
        entry["error"] = trace["error"]
    return entry


def _sorted_runs(traces):
    return sorted(
        traces,
        key=lambda t: t.get("timestamp", {}).get("start") or "",
        reverse=True,
    )


def cmd_list(args):
    automations, scripts = fetch_traceables()

    traces_by_item = {}
    for domain in ("automation", "script"):
        for t in ha_result({"type": "trace/list", "domain": domain}) or []:
            traces_by_item.setdefault((domain, t.get("item_id")), []).append(t)

    def build(domain, objs, item_id_of):
        items = []
        for s in objs:
            runs = _sorted_runs(traces_by_item.get((domain, item_id_of(s)), []))
            entry = {
                "entity_id": s["entity_id"],
                "alias": _alias(s),
                "state": s["state"],
                "last_triggered": s.get("attributes", {}).get("last_triggered"),
                "traces_stored": len(runs),
            }
            if runs:
                entry["latest"] = _run_summary(runs[0])
            items.append(entry)
        # Traced items first (newest run first), untraced alphabetically
        items.sort(
            key=lambda e: (
                e["traces_stored"] == 0,
                -(
                    _parse_ts(e.get("latest", {}).get("start")) or datetime.min
                ).timestamp()
                if e["traces_stored"]
                else 0,
                e["alias"].lower(),
            )
        )
        return items

    output = {
        "automations": build(
            "automation", automations, lambda s: s.get("attributes", {}).get("id")
        ),
        "scripts": build("script", scripts, lambda s: s["entity_id"].split(".", 1)[1]),
    }
    print_output(output, args.format)


def cmd_runs(args):
    domain, item_id, state_obj = resolve_target(args.target)
    traces = _sorted_runs(
        ha_result({"type": "trace/list", "domain": domain, "item_id": item_id}) or []
    )

    output = {
        "entity_id": state_obj["entity_id"],
        "alias": _alias(state_obj),
        "state": state_obj["state"],
        "last_triggered": state_obj.get("attributes", {}).get("last_triggered"),
        "runs": [_run_summary(t) for t in traces],
    }
    if not traces:
        output["hint"] = (
            "no stored traces — it has not run since the last Core restart. "
            "If it should have: check `state` (off = disabled) and verify the "
            "trigger entity with ha-entities."
        )
    print_output(output, args.format)


def cmd_show(args):
    domain, item_id, state_obj = resolve_target(args.target)

    run_id = args.run
    if not run_id:
        traces = _sorted_runs(
            ha_result({"type": "trace/list", "domain": domain, "item_id": item_id})
            or []
        )
        if not traces:
            raise RuntimeError(
                f"no stored traces for '{state_obj['entity_id']}' — it has not "
                "run since the last Core restart (check `ha-trace runs`)"
            )
        run_id = traces[0]["run_id"]

    full = ha_result(
        {"type": "trace/get", "domain": domain, "item_id": item_id, "run_id": run_id}
    )

    if args.full:
        print_output(full, args.format)
        return

    start = _parse_ts(full.get("timestamp", {}).get("start"))
    steps = []
    for elements in (full.get("trace") or {}).values():
        for el in elements:
            step = {"path": el.get("path")}
            ts = _parse_ts(el.get("timestamp"))
            if start and ts:
                step["offset_s"] = round((ts - start).total_seconds(), 3)
            if "result" in el:
                step["result"] = el["result"]
            if "error" in el:
                step["error"] = el["error"]
            steps.append(step)
    steps.sort(key=lambda s: s.get("offset_s", 0))

    output = {
        "entity_id": state_obj["entity_id"],
        "alias": _alias(state_obj),
        **_run_summary(full),
        "steps": steps,
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
        prog="ha-trace",
        description="Inspect Home Assistant automation and script traces.",
    )
    sub = parser.add_subparsers(dest="command", metavar="command", required=True)

    p_list = sub.add_parser(
        "list",
        parents=[fmt_parent],
        help="All automations/scripts with stored trace counts and latest outcome",
    )
    p_list.set_defaults(func=cmd_list)

    p_runs = sub.add_parser(
        "runs", parents=[fmt_parent], help="Stored trace runs for one item"
    )
    p_runs.add_argument("target", help="entity_id or friendly name")
    p_runs.set_defaults(func=cmd_runs)

    p_show = sub.add_parser(
        "show", parents=[fmt_parent], help="Step-by-step walkthrough of one run"
    )
    p_show.add_argument("target", help="entity_id or friendly name")
    p_show.add_argument(
        "--run", default=None, metavar="RUN_ID", help="Run to show (default: latest)"
    )
    p_show.add_argument(
        "--full", action="store_true", help="Dump the raw unabridged trace"
    )
    p_show.set_defaults(func=cmd_show)

    args = parser.parse_args()

    try:
        args.func(args)
    except (RuntimeError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
