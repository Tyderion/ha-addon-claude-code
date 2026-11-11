#!/usr/bin/env python3
"""ha-history — Query Home Assistant state history and long-term statistics.

Usage:
  ha-history changes <entity_id> [<entity_id> ...] [--last 24h | --from ISO [--to ISO]]
                     [--limit N]
  ha-history stats <entity_id> [<entity_id> ...] [--last 7d | --from ISO [--to ISO]]
                   [--period hour|day|week|month|5minute]
  ha-history stats-list [--search TEXT] [--limit N]
  ha-history logbook [<entity_id> ...] [--device ID ...] [--context ID]
                     [--kind KIND ...] [--exclude PATTERN ...]
                     [--last 24h | --from ISO [--to ISO]] [--limit N]

`changes` reads the recorder's raw state history (kept ~10 days by default);
`stats` reads long-term statistics (hourly/daily aggregates, kept forever, but
only for numeric sensors — see `stats-list` for what's available); `logbook`
reads the logbook, which attributes each change to the user, automation,
script, service call, entity or event that caused it (same retention as
`changes`).

Relative windows: --last N[mhdw] (minutes/hours/days/weeks), e.g. --last 8h.
All commands accept --format yaml|json (default: yaml).
"""

import argparse
import fnmatch
import os
import re
import sys
import urllib.parse
from collections import Counter
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from ha_lib import (
    FORMAT_PARENT,
    ha_http,
    ha_result,
    print_output,
    run_cli,
)

# What a logbook row is, and what caused it; --kind accepts either
ROW_KINDS = ("state", "run", "message")
CAUSE_KINDS = ("user", "automation", "script", "service", "entity", "event", "none")
BY_ENTITY_TOP = 15
# Context ids are ULIDs; HA silently drops any other value and returns the
# whole unfiltered logbook, so a run_id or user id must never reach it
CONTEXT_ID_RE = re.compile(r"[0-9A-Za-z]{26}")
# Domains the logbook never records (HA's ALWAYS_CONTINUOUS_DOMAINS), and the
# sensor device classes it still treats as non-numeric
CONTINUOUS_DOMAINS = ("counter", "image", "proximity")
NON_NUMERIC_DEVICE_CLASSES = ("date", "enum", "timestamp")


def humanize(seconds):
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    parts = []
    for label, size in (("d", 86400), ("h", 3600), ("m", 60)):
        value, seconds = divmod(seconds, size)
        if value:
            parts.append(f"{value}{label}")
    return " ".join(parts[:2]) or "0m"


def local_iso(ts):
    """Unix timestamp (seconds) -> local-time ISO string."""
    return datetime.fromtimestamp(ts, tz=timezone.utc).astimezone().isoformat()


def parse_iso(value):
    """ISO date/datetime -> aware datetime (local time if it has no offset)."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as e:
        raise RuntimeError(e) from None
    return parsed if parsed.tzinfo else parsed.astimezone()


def parse_window(args, default_last):
    """Resolve --last / --from / --to into aware (start, end) datetimes."""
    if args.last and args.from_:
        raise RuntimeError("use either --last or --from, not both")

    end = parse_iso(args.to) if args.to else datetime.now(timezone.utc)
    if args.from_:
        start = parse_iso(args.from_)
    else:
        m = re.fullmatch(r"(\d+)([mhdw])", args.last or default_last)
        if not m:
            raise RuntimeError(
                f"invalid --last value '{args.last}' — use e.g. 30m, 8h, 3d, 2w"
            )
        amount, unit = int(m.group(1)), m.group(2)
        delta = {
            "m": timedelta(minutes=amount),
            "h": timedelta(hours=amount),
            "d": timedelta(days=amount),
            "w": timedelta(weeks=amount),
        }[unit]
        start = end - delta

    if start >= end:
        raise RuntimeError("window start must be before its end")
    return start, end


def window_out(start, end):
    """The resolved window as printed: local-time ISO strings."""
    return {
        "from": start.astimezone().isoformat(),
        "to": end.astimezone().isoformat(),
    }


def cmd_changes(args):
    start, end = parse_window(args, default_last="24h")

    history = (
        ha_result(
            {
                "type": "history/history_during_period",
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
                "entity_ids": args.entity_ids,
                "include_start_time_state": True,
                "significant_changes_only": True,
                "minimal_response": True,
                "no_attributes": True,
            }
        )
        or {}
    )

    window_end_ts = end.timestamp()
    entities = []
    for eid in args.entity_ids:
        rows = history.get(eid) or []
        if not rows:
            print(
                f"Warning: no recorded history for '{eid}' in this window "
                "(check the id with ha-entities, or widen the window)",
                file=sys.stderr,
            )
            continue

        # Merge consecutive identical states, compute time spent in each entry
        merged = []
        for row in rows:
            state, ts = row.get("s"), row.get("lu")
            if merged and merged[-1]["state"] == state:
                continue
            merged.append({"state": state, "ts": ts})
        for i, entry in enumerate(merged):
            next_ts = merged[i + 1]["ts"] if i + 1 < len(merged) else window_end_ts
            entry["duration_s"] = max(0, next_ts - entry["ts"])

        # Time-in-state summary over the full window
        totals = {}
        for entry in merged:
            totals[entry["state"]] = totals.get(entry["state"], 0) + entry["duration_s"]
        window_s = sum(totals.values()) or 1

        result = {
            "entity_id": eid,
            "changes_total": len(merged),
            "current_state": merged[-1]["state"],
        }
        if len(totals) > 10:
            result["hint"] = (
                "states look numeric/continuous — time_in_state omitted; "
                "use `ha-history stats` for aggregates"
            )
        else:
            result["time_in_state"] = [
                {
                    "state": state,
                    "total": humanize(seconds),
                    "percent": round(100 * seconds / window_s, 1),
                }
                for state, seconds in sorted(totals.items(), key=lambda x: -x[1])
            ]

        newest_first = list(reversed(merged))
        if args.limit > 0:
            newest_first = newest_first[: args.limit]
        result["returned"] = len(newest_first)
        result["truncated"] = len(newest_first) < len(merged)
        result["changes"] = [
            {
                "state": e["state"],
                "from": local_iso(e["ts"]),
                "duration": humanize(e["duration_s"]),
            }
            for e in newest_first
        ]
        entities.append(result)

    if not entities:
        print("Error: no history for any requested entity", file=sys.stderr)
        sys.exit(1)

    output = {
        "window": window_out(start, end),
        "entities": entities,
    }
    print_output(output, args.format)


def cmd_stats(args):
    start, end = parse_window(args, default_last="7d")

    stats = (
        ha_result(
            {
                "type": "recorder/statistics_during_period",
                "start_time": start.isoformat(),
                "end_time": end.isoformat(),
                "statistic_ids": args.entity_ids,
                "period": args.period,
            }
        )
        or {}
    )

    meta = ha_result({"type": "recorder/list_statistic_ids"}) or []
    units = {
        m.get("statistic_id"): m.get("statistics_unit_of_measurement")
        or m.get("unit_of_measurement")
        for m in meta
    }

    entities = []
    for eid in args.entity_ids:
        rows = stats.get(eid) or []
        if not rows:
            print(
                f"Warning: no statistics for '{eid}' — only numeric sensors with "
                "a state_class have long-term statistics (see `ha-history "
                "stats-list`)",
                file=sys.stderr,
            )
            continue
        buckets = []
        for row in rows:
            bucket = {"start": local_iso(row["start"] / 1000)}
            for key in ("mean", "min", "max", "sum", "state", "change"):
                if row.get(key) is not None:
                    value = row[key]
                    bucket[key] = round(value, 3) if isinstance(value, float) else value
            buckets.append(bucket)
        entities.append(
            {
                "entity_id": eid,
                "unit": units.get(eid),
                "period": args.period,
                "buckets": buckets,
            }
        )

    if not entities:
        print("Error: no statistics for any requested entity", file=sys.stderr)
        sys.exit(1)

    output = {
        "window": window_out(start, end),
        "entities": entities,
    }
    print_output(output, args.format)


def cmd_stats_list(args):
    meta = ha_result({"type": "recorder/list_statistic_ids"}) or []

    items = []
    for m in meta:
        sid = m.get("statistic_id", "")
        name = m.get("display_name") or m.get("name")
        entry = {"statistic_id": sid}
        if name:
            entry["name"] = name
        unit = m.get("statistics_unit_of_measurement") or m.get("unit_of_measurement")
        if unit:
            entry["unit"] = unit
        has_mean = m.get("has_mean") or m.get("mean_type") not in (None, 0, "none")
        entry["kind"] = "sum" if m.get("has_sum") else "mean" if has_mean else "unknown"
        items.append(entry)

    if args.search:
        needle = args.search.lower()
        items = [
            i
            for i in items
            if needle in i["statistic_id"].lower()
            or needle in i.get("name", "").lower()
        ]

    items.sort(key=lambda i: i["statistic_id"])
    total = len(items)
    if args.limit > 0:
        items = items[: args.limit]

    output = {
        "total": total,
        "returned": len(items),
        "truncated": len(items) < total,
        "statistics": items,
    }
    print_output(output, args.format)


def row_kind(row):
    """What a logbook row is: a state change, an automation/script run, or a message."""
    if "state" in row:
        return "state"
    if row.get("domain") in ("automation", "script") and row.get("context_id"):
        return "run"
    return "message"


def describe_cause(row):
    """Why a logbook row happened, from the context fields HA added to it.

    The user, when HA recorded one, rides along as `user_id`; it is resolved
    to a name later, only for the rows that get printed.
    """
    event_type = row.get("context_event_type")
    user_id = row.get("context_user_id")

    if event_type == "automation_triggered":
        cause = {
            "kind": "automation",
            "name": row.get("context_name"),
            "entity_id": row.get("context_entity_id"),
            "trigger": row.get("context_source") or row.get("context_message"),
        }
    elif event_type == "script_started":
        cause = {
            "kind": "script",
            "name": row.get("context_name"),
            "entity_id": row.get("context_entity_id"),
        }
    elif event_type == "call_service":
        cause = {
            "kind": "user" if user_id else "service",
            "service": f"{row.get('context_domain')}.{row.get('context_service')}",
        }
    elif event_type:
        cause = {
            "kind": "event",
            "event_type": event_type,
            **{
                key: row.get(f"context_{key}")
                for key in ("domain", "name", "message", "source", "entity_id")
            },
        }
    elif user_id:
        cause = {"kind": "user"}
    elif row.get("context_entity_id"):
        cause = {
            "kind": "entity",
            "entity_id": row["context_entity_id"],
            "state": row.get("context_state"),
        }
    else:
        cause = {"kind": "none"}

    if user_id:
        cause["user_id"] = user_id
    return {k: v for k, v in cause.items() if v is not None}


def shape_row(row):
    entry = {"when": local_iso(row["when"]), "kind": row_kind(row)}
    for key in ("entity_id", "state", "name", "message", "attributes"):
        if row.get(key) not in (None, {}):
            entry[key] = row[key]
    entry["cause"] = describe_cause(row)
    # Only run rows carry an id: the handle for `--context` and ha-trace
    for key in ("context_id", "item_id", "run_id"):
        if row.get(key):
            entry[key] = row[key]
    return entry


def resolve_users(entries):
    """Replace each cause's user_id with a `user` naming who it was.

    `token_user` marks the user the add-on's token belongs to. It cannot tell
    that user's own clicks from calls made through the token; only a context
    id can (ha-service prints the one of its call).
    """
    with_user = [e["cause"] for e in entries if "user_id" in e["cause"]]
    if not with_user:
        return

    try:
        users = {u.get("id"): u for u in ha_result({"type": "config/auth/list"}) or []}
    except RuntimeError as e:
        users = {}
        print(
            f"Warning: cannot list users ({e}); showing raw user ids",
            file=sys.stderr,
        )
    try:
        token_user_id = (ha_result({"type": "auth/current_user"}) or {}).get("id")
    except RuntimeError:
        token_user_id = None

    for cause in with_user:
        user_id = cause.pop("user_id")
        known = users.get(user_id) or {}
        user = {"name": known.get("name")}
        if not known:
            user["user_id"] = user_id
        if known.get("system_generated"):
            user["system_generated"] = True
        if user_id == token_user_id:
            user["token_user"] = True
        cause["user"] = user


def explain_missing(entity_id):
    """Why the logbook has nothing for an entity, as far as we can tell."""
    domain = entity_id.partition(".")[0]
    if domain in CONTINUOUS_DOMAINS:
        return f"the logbook never records {domain} entities; use `ha-history changes`"
    if domain == "sensor":
        try:
            # Quoted: a space or non-ASCII id would fail inside urllib instead
            path = "/api/states/" + urllib.parse.quote(entity_id, safe="")
            state = ha_http("GET", path) or {}
        except RuntimeError:
            state = {}
        attrs = state.get("attributes") or {}
        device_class = attrs.get("device_class")
        if (
            attrs.get("unit_of_measurement")
            or attrs.get("state_class")
            or (device_class and device_class not in NON_NUMERIC_DEVICE_CLASSES)
        ):
            return (
                "it is a numeric sensor, which the logbook skips; use "
                "`ha-history changes` or `stats`"
            )
    return (
        "either it did not change in this window (attribute-only updates do not "
        "count), or the logbook skips it (excluded from logbook/recorder); "
        "`ha-history changes` tells the two apart"
    )


def cmd_logbook(args):
    if args.context and (args.entity_ids or args.device):
        # HA asserts against the combination and answers only unknown_error
        raise RuntimeError(
            "--context cannot be combined with entity ids or --device; "
            "query the context alone"
        )
    if args.context and not CONTEXT_ID_RE.fullmatch(args.context):
        raise RuntimeError(
            f"'{args.context}' is not a context id (a 26-character ULID, as "
            "printed in `context_id`); run_id, item_id and user ids are not"
        )
    # A context id names its own moment; the window only bounds the search
    start, end = parse_window(args, default_last="10d" if args.context else "24h")

    command = {
        "type": "logbook/get_events",
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
    }
    if args.entity_ids:
        command["entity_ids"] = args.entity_ids
    if args.device:
        command["device_ids"] = args.device
    if args.context:
        command["context_id"] = args.context
    rows = ha_result(command) or []

    if args.context and not rows:
        raise RuntimeError(
            f"no logbook entries for context '{args.context}'. Either the "
            "recorder has not written them yet (it commits every few seconds; "
            "retry shortly), the context changed no state, or what it set off "
            "ran in child contexts (an automation run gets its own; find it "
            "with ha-trace or an entity-scoped query). If it is older, widen "
            "the window"
        )
    seen = {r.get("entity_id") for r in rows}
    missing = [eid for eid in args.entity_ids if eid not in seen]
    for eid in missing:
        print(
            f"Warning: no logbook entries for '{eid}': {explain_missing(eid)}",
            file=sys.stderr,
        )
    if args.entity_ids and not args.device and len(missing) == len(args.entity_ids):
        raise RuntimeError("no logbook entries for any requested entity")

    # Sort on HA's epoch seconds: local ISO strings misorder across a DST change
    entries = [
        shape_row(r) for r in sorted(rows, key=lambda r: r["when"], reverse=True)
    ]
    if args.kind:
        entries = [
            e
            for e in entries
            if e["kind"] in args.kind or e["cause"]["kind"] in args.kind
        ]
    if args.exclude:
        entries = [
            e
            for e in entries
            if not any(fnmatch.fnmatch(e.get("entity_id", ""), p) for p in args.exclude)
        ]

    output = {"window": window_out(start, end)}
    if not (args.entity_ids or args.device or args.context):
        counts = Counter(e.get("entity_id") or "(none)" for e in entries)
        output["by_entity"] = [
            {"entity_id": eid, "count": n}
            for eid, n in counts.most_common(BY_ENTITY_TOP)
        ]
    total = len(entries)
    if args.limit > 0:
        entries = entries[: args.limit]
    resolve_users(entries)
    output["returned"] = len(entries)
    output["truncated"] = len(entries) < total
    output["entries"] = entries
    print_output(output, args.format)


def main():
    window_parent = argparse.ArgumentParser(add_help=False)
    window_parent.add_argument(
        "--last",
        default=None,
        metavar="N[mhdw]",
        help="Relative window, e.g. 30m, 8h, 3d, 2w",
    )
    window_parent.add_argument(
        "--from",
        dest="from_",
        default=None,
        metavar="ISO",
        help="Window start (ISO date/datetime, local time if no offset)",
    )
    window_parent.add_argument(
        "--to",
        default=None,
        metavar="ISO",
        help="Window end (default: now); --last counts back from it",
    )

    parser = argparse.ArgumentParser(
        prog="ha-history",
        description="Query Home Assistant state history and long-term statistics.",
    )
    sub = parser.add_subparsers(dest="command", metavar="command", required=True)

    p_changes = sub.add_parser(
        "changes",
        parents=[FORMAT_PARENT, window_parent],
        help="State-change log with time-in-state summary (default: last 24h)",
    )
    p_changes.add_argument("entity_ids", nargs="+", metavar="entity_id")
    p_changes.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Newest changes to list per entity (default: 50, 0 = unlimited)",
    )
    p_changes.set_defaults(func=cmd_changes)

    p_stats = sub.add_parser(
        "stats",
        parents=[FORMAT_PARENT, window_parent],
        help="Long-term statistics buckets (default: last 7d, daily)",
    )
    p_stats.add_argument("entity_ids", nargs="+", metavar="entity_id")
    p_stats.add_argument(
        "--period",
        choices=["5minute", "hour", "day", "week", "month"],
        default="day",
        help="Bucket size (default: day)",
    )
    p_stats.set_defaults(func=cmd_stats)

    p_slist = sub.add_parser(
        "stats-list",
        parents=[FORMAT_PARENT],
        help="List entities that have long-term statistics",
    )
    p_slist.add_argument(
        "--search", default=None, metavar="TEXT", help="Filter by id/name substring"
    )
    p_slist.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Limit results (default: 100, 0 = unlimited)",
    )
    p_slist.set_defaults(func=cmd_stats_list)

    p_logbook = sub.add_parser(
        "logbook",
        parents=[FORMAT_PARENT, window_parent],
        help="What changed and what caused it (default: last 24h)",
    )
    p_logbook.add_argument("entity_ids", nargs="*", metavar="entity_id")
    p_logbook.add_argument(
        "--device",
        action="append",
        default=[],
        metavar="DEVICE_ID",
        help="Also every entity of this device (repeatable)",
    )
    p_logbook.add_argument(
        "--context",
        default=None,
        metavar="CONTEXT_ID",
        help="Everything that happened in one context, by its context_id (a "
        "ULID, not a run_id; default window: last 10d)",
    )
    p_logbook.add_argument(
        "--kind",
        action="append",
        default=[],
        choices=ROW_KINDS + CAUSE_KINDS,
        help="Keep entries of this row or cause kind (repeatable)",
    )
    p_logbook.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="PATTERN",
        help="Drop entries whose entity_id matches this glob (repeatable)",
    )
    p_logbook.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Newest entries to list (default: 50, 0 = unlimited)",
    )
    p_logbook.set_defaults(func=cmd_logbook)

    run_cli(parser, (ValueError,))


if __name__ == "__main__":
    main()
