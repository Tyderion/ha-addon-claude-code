#!/usr/bin/env python3
"""ha-template — Render a Jinja template against the live Home Assistant state.

Usage:
  ha-template TEMPLATE [--var KEY=VALUE ...] [--watch] [--timeout N]
  ha-template --file FILE [--var KEY=VALUE ...] [--watch] [--timeout N]

Renders via the WebSocket render_template API, so the result is exactly what
automations and dashboards would see. The output includes `listeners` — the
entities/domains the template watches — which is what to check when a template
does not update.

--var values are parsed as JSON when possible (numbers, booleans, lists,
objects), otherwise taken as plain strings.

--watch keeps the subscription open and prints a new document every time a
watched entity changes the result. Stop with Ctrl+C.

Accepts --format yaml|json (default: yaml).
"""

import argparse
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from ha_lib import (
    FORMAT_PARENT,
    ha_subscribe,
    parse_pairs,
    print_output,
    run_cli,
)


def read_template(args):
    if args.template is not None:
        return args.template
    try:
        with open(args.file) as f:
            return f.read()
    except OSError as e:
        raise RuntimeError(f"cannot read template file: {e}") from None


def _listeners(event):
    """Trim the listeners dict to what is actually listened to."""
    raw = event.get("listeners") or {}
    trimmed = {}
    for key in ("entities", "domains"):
        if raw.get(key):
            trimmed[key] = raw[key]
    for key in ("time", "all"):
        if raw.get(key):
            trimmed[key] = True
    return trimmed


def _event_entry(event):
    if event.get("error") and "result" not in event:
        return {"error": event["error"], "level": event.get("level", "ERROR")}
    entry = {"result": event.get("result")}
    listeners = _listeners(event)
    if listeners:
        entry["listeners"] = listeners
    return entry


def run(args):
    template = read_template(args)
    command = {
        "type": "render_template",
        "template": template,
        "report_errors": True,
    }
    variables = parse_pairs(args.var, "--var")
    if variables:
        command["variables"] = variables
    if args.timeout is not None:
        command["timeout"] = args.timeout

    events = ha_subscribe(command)

    if not args.watch:
        event = next(events)
        entry = _event_entry(event)
        if "error" in entry:
            print(f"Template error: {entry['error']}", file=sys.stderr)
            sys.exit(1)
        print_output(entry, args.format)
        return

    try:
        for event in events:
            entry = {"at": datetime.now().strftime("%H:%M:%S"), **_event_entry(event)}
            if args.format == "yaml":
                print("---")
            print_output(entry, args.format)
            sys.stdout.flush()
    except KeyboardInterrupt:
        pass


def main():
    parser = argparse.ArgumentParser(
        prog="ha-template",
        description="Render a Jinja template against the live Home Assistant state.",
        parents=[FORMAT_PARENT],
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("template", nargs="?", help="Template string (inline)")
    source.add_argument(
        "-f", "--file", metavar="FILE", help="Read the template from FILE"
    )
    parser.add_argument(
        "--var",
        action="append",
        metavar="KEY=VALUE",
        help="Template variable; value parsed as JSON when possible (repeatable)",
    )
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Keep rendering on every state change until Ctrl+C",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=None,
        metavar="N",
        help="Render timeout in seconds (default: HA's own, 3s)",
    )
    parser.set_defaults(func=run)
    run_cli(parser)


if __name__ == "__main__":
    main()
