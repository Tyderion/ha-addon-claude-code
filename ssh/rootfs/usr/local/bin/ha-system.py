#!/usr/bin/env python3
"""ha-system — Pending updates and repairs across Home Assistant.

Usage:
  ha-system updates [--all]
  ha-system repairs [--all]

`updates` lists every update entity with a newer version: Core, OS,
Supervisor, apps (add-ons), HACS integrations and cards, and device
firmware. `ha available-updates` only knows the first four. `--all` adds the
current and skipped ones. Nothing here installs anything: see the ManageSystem
skill for which command installs which kind.

`repairs` lists Home Assistant's repair issues with their text, merged with
the Supervisor issues Core does not show as repairs. `--all` adds ignored
ones. Fixing a repair is a UI flow (Settings > Repairs) or, for a Supervisor
suggestion, `ha resolution suggestion apply`.

All commands accept --format yaml|json (default: yaml).
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from ha_lib import (
    FORMAT_PARENT,
    ha_result,
    print_output,
    run_cli,
)

KIND_ORDER = ("core", "os", "supervisor", "app", "hacs", "firmware", "other")
# hassio update entities: unique_id is `<prefix>_version_latest`
# (hassio/entity.py, hassio/update.py)
HASSIO_SUFFIX = "_version_latest"
HASSIO_SYSTEM = {
    "home_assistant_core": "core",
    "home_assistant_os": "os",
    "home_assistant_supervisor": "supervisor",
}
SEVERITY_RANK = {"critical": 0, "error": 1, "warning": 2}


def supervisor_get(path):
    """GET a Supervisor API path through Core's proxy (admin token only)."""
    return (
        ha_result({"type": "supervisor/api", "endpoint": path, "method": "get"}) or {}
    )


def without_none(d):
    return {k: v for k, v in d.items() if v is not None}


# --- updates ---


def update_kind(state, entry):
    """What an update entity updates, and the app slug when it is an app."""
    attrs = state.get("attributes") or {}
    if entry.get("platform") == "hassio":
        prefix = (entry.get("unique_id") or "").removesuffix(HASSIO_SUFFIX)
        if prefix in HASSIO_SYSTEM:
            return HASSIO_SYSTEM[prefix], None
        return "app", prefix
    if entry.get("platform") == "hacs":
        return "hacs", None
    if attrs.get("device_class") == "firmware":
        return "firmware", None
    return "other", None


def shape_update(state, entry):
    attrs = state.get("attributes") or {}
    kind, slug = update_kind(state, entry)
    row = {
        "entity_id": state["entity_id"],
        "name": attrs.get("title") or attrs.get("friendly_name"),
        "kind": kind,
        "slug": slug,
        "installed": attrs.get("installed_version"),
        "latest": attrs.get("latest_version"),
        "release_url": attrs.get("release_url"),
    }
    if attrs.get("in_progress"):
        row["in_progress"] = True
        row["update_percentage"] = attrs.get("update_percentage")
    if attrs.get("auto_update"):
        row["auto_update"] = True
    return without_none(row)


def is_skipped(state):
    attrs = state.get("attributes") or {}
    skipped = attrs.get("skipped_version")
    return skipped is not None and skipped == attrs.get("latest_version")


def cmd_updates(args):
    states = [
        s
        for s in ha_result({"type": "get_states"}) or []
        if s.get("entity_id", "").startswith("update.")
    ]
    registry = {
        e.get("entity_id"): e
        for e in ha_result({"type": "config/entity_registry/list"}) or []
    }

    rows, unknown, unavailable, skipped, pending = [], [], 0, 0, 0
    for state in states:
        value = state.get("state")
        skip = value == "off" and is_skipped(state)
        pending += value == "on"
        skipped += skip
        if value == "unavailable":
            unavailable += 1
        elif value == "unknown":
            unknown.append(update_kind(state, registry.get(state["entity_id"], {}))[0])
        if value == "on" or (args.all and value == "off"):
            row = shape_update(state, registry.get(state["entity_id"], {}))
            if args.all:
                row["state"] = "skipped" if skip else value
            rows.append(row)

    rows.sort(key=lambda r: (KIND_ORDER.index(r["kind"]), (r.get("name") or "")))
    notes = []
    if unknown:
        kinds = sorted(set(unknown), key=KIND_ORDER.index)
        notes.append(
            f"{len(unknown)} {'/'.join(kinds)} update entities report no latest "
            "version (state unknown); they are not pending updates"
        )
    if unavailable:
        notes.append(f"{unavailable} update entities are unavailable")
    if skipped and not args.all:
        notes.append(f"{skipped} updates were skipped in the UI (--all shows them)")

    output = {"pending": pending, "updates": rows}
    if notes:
        output["notes"] = notes
    print_output(output, args.format)


# --- repairs ---


class _KeepMissing(dict):
    """format_map mapping that leaves an unknown {placeholder} as written."""

    def __missing__(self, key):
        return "{" + key + "}"


def render(text, placeholders):
    if not text:
        return None
    try:
        return text.format_map(_KeepMissing(placeholders or {}))
    except (ValueError, IndexError):
        return text


def issue_text(resources, domain, key, placeholders):
    """Title and description of an issue from the integration's translations.

    A fixable issue often keeps its explanation in the fix flow's first step
    rather than in `description`.
    """
    base = f"component.{domain}.issues.{key}"
    description = resources.get(f"{base}.description")
    if description is None:
        steps = sorted(
            k
            for k in resources
            if k.startswith(f"{base}.fix_flow.step.") and k.endswith(".description")
        )
        description = resources.get(steps[0]) if steps else None
    return (
        render(resources.get(f"{base}.title"), placeholders),
        render(description, placeholders),
    )


def fetch_translations(domains):
    if not domains:
        return {}
    language = (ha_result({"type": "get_config"}) or {}).get("language") or "en"
    command = {
        "type": "frontend/get_translations",
        "language": language,
        "category": "issues",
        "integration": sorted(domains),
    }
    return (ha_result(command) or {}).get("resources") or {}


def supervisor_issues(core_ids):
    """Supervisor issues Core does not show as repairs, and the system state.

    Core mirrors some issue types as `hassio` repairs whose issue_id is the
    Supervisor uuid without dashes; the others exist only here.
    """
    info = supervisor_get("/resolution/info")
    issues = []
    for issue in info.get("issues") or []:
        uuid = issue.get("uuid") or ""
        if uuid.replace("-", "") in core_ids:
            continue
        try:
            reply = supervisor_get(f"/resolution/issue/{uuid}/suggestions")
            suggestions = [
                {"type": s.get("type"), "uuid": s.get("uuid")}
                for s in reply.get("suggestions") or []
            ]
        except RuntimeError:
            suggestions = None
        issues.append(
            {
                "uuid": uuid,
                "key": f"issue_{issue.get('context')}_{issue.get('type')}",
                "reference": issue.get("reference"),
                "suggestions": suggestions,
            }
        )
    system = {k: info[k] for k in ("unhealthy", "unsupported") if info.get(k)}
    return issues, system


def cmd_repairs(args):
    core = (ha_result({"type": "repairs/list_issues"}) or {}).get("issues") or []
    core_ids = {i.get("issue_id") for i in core if i.get("domain") == "hassio"}
    try:
        sup_issues, system = supervisor_issues(core_ids)
    except RuntimeError as e:
        sup_issues, system = [], {}
        print(
            f"Warning: cannot read the Supervisor's resolution center ({e}); "
            "showing Core repairs only",
            file=sys.stderr,
        )

    shown = [i for i in core if args.all or not i.get("ignored")]
    hidden = len(core) - len(shown)
    domains = {i.get("domain") for i in shown if i.get("domain")}
    if sup_issues:
        domains.add("hassio")
    try:
        resources = fetch_translations(domains)
    except RuntimeError as e:
        resources = {}
        print(
            f"Warning: cannot load repair texts ({e}); showing translation keys",
            file=sys.stderr,
        )

    repairs = []
    for issue in shown:
        title, description = issue_text(
            resources,
            issue.get("domain"),
            issue.get("translation_key"),
            issue.get("translation_placeholders"),
        )
        row = {
            "source": "core",
            "domain": issue.get("domain"),
            "issue_domain": issue.get("issue_domain"),
            "issue_id": issue.get("issue_id"),
            "severity": issue.get("severity"),
            "title": title or issue.get("translation_key"),
            "description": description,
            "fixable": bool(issue.get("is_fixable")),
            "breaks_in": issue.get("breaks_in_ha_version"),
            "learn_more_url": issue.get("learn_more_url"),
            "created": issue.get("created"),
        }
        if issue.get("ignored"):
            row["ignored"] = True
        if row["issue_domain"] == row["domain"]:
            del row["issue_domain"]
        repairs.append(without_none(row))
    repairs.sort(key=lambda r: SEVERITY_RANK.get(r.get("severity"), 3))

    for issue in sup_issues:
        title, description = issue_text(
            resources, "hassio", issue["key"], {"reference": issue["reference"]}
        )
        row = {
            "source": "supervisor",
            **issue,
            "title": title or issue["key"],
            "description": description,
        }
        repairs.append(without_none(row))

    output = {"repairs": repairs}
    if hidden:
        output["ignored_hidden"] = hidden
    if system:
        output["system"] = system
    print_output(output, args.format)


def main():
    parser = argparse.ArgumentParser(
        prog="ha-system",
        description="Pending updates and repairs across Home Assistant.",
    )
    sub = parser.add_subparsers(dest="command", metavar="command", required=True)

    p_updates = sub.add_parser(
        "updates",
        parents=[FORMAT_PARENT],
        help="Pending updates: Core, OS, Supervisor, apps, HACS, firmware",
    )
    p_updates.add_argument(
        "--all", action="store_true", help="Also current and skipped ones"
    )
    p_updates.set_defaults(func=cmd_updates)

    p_repairs = sub.add_parser(
        "repairs",
        parents=[FORMAT_PARENT],
        help="Repair issues with their text, plus Supervisor issues",
    )
    p_repairs.add_argument("--all", action="store_true", help="Also ignored ones")
    p_repairs.set_defaults(func=cmd_repairs)

    run_cli(parser, (KeyError, TypeError, AttributeError))


if __name__ == "__main__":
    main()
