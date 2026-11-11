#!/usr/bin/env python3
"""ha-trace — Inspect Home Assistant automation and script traces.

Usage:
  ha-trace list
  ha-trace runs <target>
  ha-trace show <target> [--run RUN_ID] [--full]

<target> is an entity_id (automation.morning_lights, script.wake_up) or a
friendly name/alias. Traces exist only for runs that actually started; HA
stores the last few runs per item and keeps them across a clean Core
restart; a crash loses them.

All commands accept --format yaml|json (default: yaml).
"""

import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from ha_lib import (
    FORMAT_PARENT,
    ha_result,
    print_output,
    run_cli,
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


def _item_id(domain, state, strict=False):
    """The key HA files traces under: an automation's `id` attribute (None if
    it has none, or an error when `strict`), a script's object_id."""
    if domain == "script":
        return state["entity_id"].split(".", 1)[1]
    item_id = state.get("attributes", {}).get("id")
    if not item_id and strict:
        raise RuntimeError(
            f"'{state['entity_id']}' has no internal id (YAML automation without "
            "an `id:` field) — HA does not record traces for it. "
            "Add a unique `id:` to the automation and reload."
        )
    return item_id


def resolve_target(target):
    """Resolve entity_id or friendly name to (domain, item_id, state_obj)."""
    automations, scripts = fetch_traceables()
    candidates = [("automation", s) for s in automations]
    candidates += [("script", s) for s in scripts]

    # Best match wins: exact entity_id, then exact alias, then substring
    needle = target.lower()
    matchers = (
        lambda s: s["entity_id"] == target,
        lambda s: needle == _alias(s).lower(),
        lambda s: needle in _alias(s).lower() or needle in s["entity_id"].lower(),
    )
    for i, matches in enumerate(matchers):
        found = [(d, s) for d, s in candidates if matches(s)]
        if found:
            break
        if i == 0:
            # A full entity_id is never searched as a name fragment
            for domain in ("automation", "script"):
                if target.startswith(f"{domain}."):
                    raise RuntimeError(
                        f"no {domain} with entity_id '{target}' — run `ha-trace list`"
                    )
    if not found:
        raise RuntimeError(f"nothing matches '{target}' — run `ha-trace list`")
    if len(found) > 1:
        ids = ", ".join(s["entity_id"] for _, s in found)
        raise RuntimeError(f"'{target}' is ambiguous, matches: {ids}")

    domain, s = found[0]
    return domain, _item_id(domain, s, strict=True), s


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


def stored_runs(domain, item_id):
    """Stored traces of one automation or script, newest first."""
    return _sorted_runs(
        ha_result({"type": "trace/list", "domain": domain, "item_id": item_id}) or []
    )


def cmd_list(args):
    automations, scripts = fetch_traceables()

    traces_by_item = {}
    for domain in ("automation", "script"):
        for t in ha_result({"type": "trace/list", "domain": domain}) or []:
            traces_by_item.setdefault((domain, t.get("item_id")), []).append(t)

    def build(domain, objs):
        items = []
        for s in objs:
            runs = _sorted_runs(traces_by_item.get((domain, _item_id(domain, s)), []))
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
        # Traced items first (newest run first), untraced alphabetically: two
        # stable sorts, with "" (no run) ordering after every ISO timestamp
        items.sort(key=lambda e: e["alias"].lower())
        items.sort(key=lambda e: e.get("latest", {}).get("start") or "", reverse=True)
        return items

    output = {
        "automations": build("automation", automations),
        "scripts": build("script", scripts),
    }
    print_output(output, args.format)


def cmd_runs(args):
    domain, item_id, state_obj = resolve_target(args.target)
    traces = stored_runs(domain, item_id)

    output = {
        "entity_id": state_obj["entity_id"],
        "alias": _alias(state_obj),
        "state": state_obj["state"],
        "last_triggered": state_obj.get("attributes", {}).get("last_triggered"),
        "runs": [_run_summary(t) for t in traces],
    }
    if not traces:
        output["hint"] = (
            "no stored traces — it has not run recently. If it should have: "
            "check `state` (off = disabled), then the trigger entity with "
            "ha-entities get and ha-history changes."
        )
    print_output(output, args.format)


def cmd_show(args):
    domain, item_id, state_obj = resolve_target(args.target)

    run_id = args.run
    if not run_id:
        traces = stored_runs(domain, item_id)
        if not traces:
            raise RuntimeError(
                f"no stored traces for '{state_obj['entity_id']}' — it has not "
                "run recently (check `ha-trace runs`)"
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
    }
    # The run's context: `ha-history logbook --context <id>` lists what it changed
    context_id = (full.get("context") or {}).get("id")
    if context_id:
        output["context_id"] = context_id
    output["steps"] = steps
    print_output(output, args.format)


def main():

    parser = argparse.ArgumentParser(
        prog="ha-trace",
        description="Inspect Home Assistant automation and script traces.",
    )
    sub = parser.add_subparsers(dest="command", metavar="command", required=True)

    p_list = sub.add_parser(
        "list",
        parents=[FORMAT_PARENT],
        help="All automations/scripts with stored trace counts and latest outcome",
    )
    p_list.set_defaults(func=cmd_list)

    p_runs = sub.add_parser(
        "runs", parents=[FORMAT_PARENT], help="Stored trace runs for one item"
    )
    p_runs.add_argument("target", help="entity_id or friendly name")
    p_runs.set_defaults(func=cmd_runs)

    p_show = sub.add_parser(
        "show", parents=[FORMAT_PARENT], help="Step-by-step walkthrough of one run"
    )
    p_show.add_argument("target", help="entity_id or friendly name")
    p_show.add_argument(
        "--run", default=None, metavar="RUN_ID", help="Run to show (default: latest)"
    )
    p_show.add_argument(
        "--full", action="store_true", help="Dump the raw unabridged trace"
    )
    p_show.set_defaults(func=cmd_show)

    run_cli(parser)


if __name__ == "__main__":
    main()
