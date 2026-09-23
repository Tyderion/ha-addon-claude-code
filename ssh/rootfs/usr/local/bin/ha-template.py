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
import json
import os
import sys
from datetime import datetime

import yaml

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from ha_lib import ha_subscribe


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


def parse_vars(pairs):
    variables = {}
    for pair in pairs or []:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise RuntimeError(f"--var expects KEY=VALUE, got '{pair}'")
        try:
            variables[key] = json.loads(value)
        except json.JSONDecodeError:
            variables[key] = value
    return variables


def read_template(args):
    if args.template is not None and args.file:
        raise RuntimeError("pass the template inline OR via --file, not both")
    if args.template is not None:
        return args.template
    if args.file:
        try:
            with open(args.file) as f:
                return f.read()
        except OSError as e:
            raise RuntimeError(f"cannot read template file: {e}") from None
    raise RuntimeError("no template given — pass it inline or via --file")


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
    variables = parse_vars(args.var)
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
    )
    parser.add_argument(
        "template", nargs="?", default=None, help="Template string (inline)"
    )
    parser.add_argument(
        "-f", "--file", default=None, metavar="FILE", help="Read the template from FILE"
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
    parser.add_argument(
        "--format",
        choices=["yaml", "json"],
        default="yaml",
        help="Output format (default: yaml)",
    )

    args = parser.parse_args()

    try:
        run(args)
    except (RuntimeError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
