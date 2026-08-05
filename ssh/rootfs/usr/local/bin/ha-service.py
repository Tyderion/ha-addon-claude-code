#!/usr/bin/env python3
"""ha-service — Discover and call Home Assistant services with real metadata.

Usage:
  ha-service list [--domain DOMAIN] [--search TEXT] [--limit N]
  ha-service show <domain.service>
  ha-service call <domain.service> [--entity E ...] [--area A ...]
                  [--device D ...] [--label L ...]
                  [--data KEY=VALUE ...] [--data-file FILE]
                  [--timeout N] [--unsafe]

`list` without filters prints a compact domain → service-names map; with
--domain or --search it prints one-line descriptions. `show` prints the full
field spec (the source of truth for parameters — never guess fields).
`call` validates the service exists, warns about unknown data keys, and
automatically requests the response for services that return one.

--data values are parsed as JSON when possible (numbers, booleans, lists,
objects), otherwise taken as plain strings. --data-file takes a YAML or JSON
mapping; --data flags override file keys.

Dangerous services (restarts, host power, shell commands, recorder purges)
additionally require --unsafe.

All commands accept --format yaml|json (default: yaml).
"""

import argparse
import fnmatch
import json
import os
import sys

import yaml

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from ha_lib import ha_call, ha_result

# Service calls that can take HA down, run arbitrary code, or delete data.
# The permission ask-list gates the canonical command forms; this in-tool
# gate cannot be bypassed by reordering CLI flags.
DANGEROUS_PATTERNS = (
    "homeassistant.restart",
    "homeassistant.stop",
    "hassio.*",
    "recorder.purge*",
    "shell_command.*",
)


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


def fetch_services():
    services = ha_result({"type": "get_services"})
    if not services:
        raise RuntimeError("get_services returned nothing")
    return services


def split_service(value):
    domain, sep, service = value.partition(".")
    if not sep or not domain or not service:
        raise RuntimeError(f"expected domain.service, got '{value}'")
    return domain, service


def lookup_service(services, domain, service):
    if domain not in services:
        raise RuntimeError(
            f"no domain '{domain}' — run `ha-service list` to see domains"
        )
    if service not in services[domain]:
        near = [s for s in services[domain] if service.lower() in s.lower()]
        hint = f" — did you mean: {', '.join(sorted(near))}?" if near else ""
        raise RuntimeError(
            f"no service '{domain}.{service}'{hint} "
            f"(run `ha-service list --domain {domain}`)"
        )
    return services[domain][service]


def flat_fields(spec):
    """Flatten field definitions, merging collapsed section groupings."""
    fields = {}
    for key, value in (spec.get("fields") or {}).items():
        if isinstance(value, dict) and "fields" in value and "selector" not in value:
            fields.update(value["fields"])  # section container, not a real field
        else:
            fields[key] = value
    return fields


def response_kind(spec):
    response = spec.get("response")
    if not isinstance(response, dict):
        return "none"
    return "optional" if response.get("optional") else "only"


def is_dangerous(call_id):
    return any(fnmatch.fnmatch(call_id, p) for p in DANGEROUS_PATTERNS)


def parse_data(args):
    data = {}
    if args.data_file:
        try:
            with open(args.data_file) as f:
                loaded = yaml.safe_load(f)
        except OSError as e:
            raise RuntimeError(f"cannot read data file: {e}") from None
        except yaml.YAMLError as e:
            raise RuntimeError(f"invalid YAML/JSON in data file: {e}") from None
        if loaded is not None and not isinstance(loaded, dict):
            raise RuntimeError("--data-file must contain a mapping")
        data.update(loaded or {})
    for pair in args.data or []:
        key, sep, value = pair.partition("=")
        if not sep or not key:
            raise RuntimeError(f"--data expects KEY=VALUE, got '{pair}'")
        try:
            data[key] = json.loads(value)
        except json.JSONDecodeError:
            data[key] = value
    return data


def build_target(args):
    target = {}
    for key, values in (
        ("entity_id", args.entity),
        ("area_id", args.area),
        ("device_id", args.device),
        ("label_id", args.label),
    ):
        if values:
            target[key] = values
    return target


def cmd_list(args):
    services = fetch_services()

    if not args.domain and not args.search:
        output = {domain: sorted(services[domain]) for domain in sorted(services)}
        print_output(output, args.format)
        return

    rows = []
    domains = [args.domain] if args.domain else sorted(services)
    if args.domain and args.domain not in services:
        raise RuntimeError(
            f"no domain '{args.domain}' — run `ha-service list` to see domains"
        )
    needle = (args.search or "").lower()
    for domain in domains:
        for name in sorted(services[domain]):
            spec = services[domain][name]
            call_id = f"{domain}.{name}"
            haystack = " ".join(
                [call_id, spec.get("name") or "", spec.get("description") or ""]
            ).lower()
            if needle and needle not in haystack:
                continue
            row = {
                "service": call_id,
                "name": spec.get("name") or name,
                "description": (spec.get("description") or "").partition(". ")[0],
            }
            if response_kind(spec) != "none":
                row["returns_response"] = response_kind(spec)
            rows.append(row)

    output = {"total": len(rows), "services": rows[: args.limit]}
    if len(rows) > args.limit:
        output["truncated"] = True
        output["returned"] = args.limit
    print_output(output, args.format)


def cmd_show(args):
    domain, service = split_service(args.service)
    spec = lookup_service(fetch_services(), domain, service)

    fields = {}
    for key, value in flat_fields(spec).items():
        entry = {}
        for meta in ("description", "required", "example", "default", "selector"):
            if meta in value:
                entry[meta] = value[meta]
        fields[key] = entry

    output = {
        "service": f"{domain}.{service}",
        "name": spec.get("name") or service,
        "description": spec.get("description") or "",
        "fields": fields,
    }
    target = spec.get("target")
    if isinstance(target, dict) and target.get("entity"):
        entity = target["entity"]
        domains = []
        for item in entity if isinstance(entity, list) else [entity]:
            domains.extend(item.get("domain") or [])
        if domains:
            output["target_domains"] = domains
    kind = response_kind(spec)
    if kind != "none":
        output["returns_response"] = kind
    if is_dangerous(f"{domain}.{service}"):
        output["dangerous"] = "calling requires --unsafe"
    print_output(output, args.format)


def cmd_call(args):
    domain, service = split_service(args.service)
    call_id = f"{domain}.{service}"
    spec = lookup_service(fetch_services(), domain, service)

    if is_dangerous(call_id) and not args.unsafe:
        raise RuntimeError(
            f"'{call_id}' is a dangerous service (restart/shell/purge class) — "
            "re-run with --unsafe if you really mean it"
        )

    data = parse_data(args)
    known = set(flat_fields(spec))
    unknown = sorted(set(data) - known)
    if unknown and known:
        print(
            f"Warning: data keys not in the service spec: {', '.join(unknown)} "
            f"(known: {', '.join(sorted(known))})",
            file=sys.stderr,
        )

    command = {"type": "call_service", "domain": domain, "service": service}
    if data:
        command["service_data"] = data
    target = build_target(args)
    if target:
        command["target"] = target
    if response_kind(spec) != "none":
        command["return_response"] = True

    result = ha_call(command, timeout=args.timeout).get("result")

    output = {"called": call_id, "success": True}
    if target:
        output["target"] = target
    if data:
        output["data"] = data
    if isinstance(result, dict) and result.get("response") is not None:
        output["response"] = result["response"]
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
        prog="ha-service",
        description="Discover and call Home Assistant services with real metadata.",
    )
    sub = parser.add_subparsers(dest="command", metavar="command", required=True)

    p_list = sub.add_parser(
        "list",
        parents=[fmt_parent],
        help="Domains and services (compact map; details with --domain/--search)",
    )
    p_list.add_argument("--domain", default=None, help="Only this domain")
    p_list.add_argument("--search", default=None, help="Filter by id/name/description")
    p_list.add_argument(
        "--limit", type=int, default=100, help="Max detailed rows (default: 100)"
    )
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser(
        "show", parents=[fmt_parent], help="Full field spec for one service"
    )
    p_show.add_argument("service", help="domain.service")
    p_show.set_defaults(func=cmd_show)

    p_call = sub.add_parser("call", parents=[fmt_parent], help="Call a service")
    p_call.add_argument("service", help="domain.service")
    p_call.add_argument(
        "--entity", action="append", metavar="ENTITY_ID", help="Target entity"
    )
    p_call.add_argument(
        "--area", action="append", metavar="AREA_ID", help="Target area"
    )
    p_call.add_argument(
        "--device", action="append", metavar="DEVICE_ID", help="Target device"
    )
    p_call.add_argument(
        "--label", action="append", metavar="LABEL_ID", help="Target label"
    )
    p_call.add_argument(
        "--data",
        action="append",
        metavar="KEY=VALUE",
        help="Service data; value parsed as JSON when possible (repeatable)",
    )
    p_call.add_argument(
        "--data-file",
        default=None,
        metavar="FILE",
        help="YAML/JSON mapping with service data (--data overrides)",
    )
    p_call.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        metavar="N",
        help="Seconds to wait for the call to finish (default: 60)",
    )
    p_call.add_argument(
        "--unsafe",
        action="store_true",
        help="Confirm calling a dangerous service (restart/shell/purge class)",
    )
    p_call.set_defaults(func=cmd_call)

    args = parser.parse_args()

    try:
        args.func(args)
    except (RuntimeError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
