#!/usr/bin/env python3
"""ha-history — Query Home Assistant state history and long-term statistics.

Usage:
  ha-history changes <entity_id> [<entity_id> ...] [--last 24h | --from ISO [--to ISO]]
                     [--limit N]
  ha-history stats <entity_id> [<entity_id> ...] [--last 7d | --from ISO [--to ISO]]
                   [--period hour|day|week|month|5minute]
  ha-history stats-list [--search TEXT] [--limit N]

`changes` reads the recorder's raw state history (kept ~10 days by default);
`stats` reads long-term statistics (hourly/daily aggregates, kept forever, but
only for numeric sensors — see `stats-list` for what's available).

Relative windows: --last N[mhdw] (minutes/hours/days/weeks), e.g. --last 8h.
All commands accept --format yaml|json (default: yaml).
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

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


def parse_window(args, default_last):
    """Resolve --last / --from / --to into aware (start, end) datetimes."""
    if args.last and args.from_:
        raise RuntimeError("use either --last or --from/--to, not both")

    now = datetime.now(timezone.utc)
    if args.from_:
        start = datetime.fromisoformat(args.from_)
        if start.tzinfo is None:
            start = start.astimezone()
        end = now
        if args.to:
            end = datetime.fromisoformat(args.to)
            if end.tzinfo is None:
                end = end.astimezone()
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
        start, end = now - delta, now

    if start >= end:
        raise RuntimeError("window start must be before its end")
    return start, end


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
        "window": {
            "from": start.astimezone().isoformat(),
            "to": end.astimezone().isoformat(),
        },
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
        "window": {
            "from": start.astimezone().isoformat(),
            "to": end.astimezone().isoformat(),
        },
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


def main():
    fmt_parent = argparse.ArgumentParser(add_help=False)
    fmt_parent.add_argument(
        "--format",
        choices=["yaml", "json"],
        default="yaml",
        help="Output format (default: yaml)",
    )
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
        "--to", default=None, metavar="ISO", help="Window end (default: now)"
    )

    parser = argparse.ArgumentParser(
        prog="ha-history",
        description="Query Home Assistant state history and long-term statistics.",
    )
    sub = parser.add_subparsers(dest="command", metavar="command", required=True)

    p_changes = sub.add_parser(
        "changes",
        parents=[fmt_parent, window_parent],
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
        parents=[fmt_parent, window_parent],
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
        parents=[fmt_parent],
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

    args = parser.parse_args()

    try:
        args.func(args)
    except (RuntimeError, OSError, ValueError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
