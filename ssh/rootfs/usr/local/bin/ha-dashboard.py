#!/usr/bin/env python3
"""ha-dashboard — Manage Home Assistant Lovelace dashboards via WebSocket API.

Usage:
  ha-dashboard list                                    List all dashboards
  ha-dashboard get <url_path>                          Print config JSON to stdout
  ha-dashboard set <url_path> <file>                   Save dashboard config from JSON file
  ha-dashboard create <url_path> <title> [options]     Create a new dashboard
  ha-dashboard delete <url_path>                       Delete a dashboard
  ha-dashboard update <url_path> [options]             Update dashboard metadata

Create/update options:
  --icon mdi:NAME       MDI icon (default for create: mdi:view-dashboard)
  --hidden              Hide from sidebar
  --show                Show in sidebar (default)
  --admin               Require admin access
  --no-admin            No admin requirement (default)
  --title TITLE         New title (update only)

Authentication (in priority order):
  1. HA_TOKEN environment variable
  2. /homeassistant/.claude/ha_token file

Setup:
  In HA: Profile → Security → Long-Lived Access Tokens → Create Token
  echo "your_token" > /homeassistant/.claude/ha_token
  chmod 600 /homeassistant/.claude/ha_token
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from ha_lib import ha_result, run_cli


def _dashboard_id(url_path: str) -> str:
    """Look up the dashboard_id used by update/delete from its url_path."""
    if url_path == "default":
        raise RuntimeError(
            "the main dashboard has no registry entry; only get and set work on it"
        )
    for d in ha_result({"type": "lovelace/dashboards/list"}) or []:
        if d.get("url_path") == url_path:
            if d.get("mode") == "yaml" or "id" not in d:
                raise RuntimeError(
                    f"'{url_path}' is a YAML-mode dashboard declared in "
                    "configuration.yaml; edit its YAML file instead"
                )
            return d["id"]
    raise RuntimeError(
        f"no dashboard with url_path '{url_path}' — run `ha-dashboard list`"
    )


# --- Commands ---


def cmd_list(args):
    dashboards = ha_result({"type": "lovelace/dashboards/list"}) or []
    print(f"{'default':30s}  (main dashboard)")
    for d in dashboards:
        sidebar = "" if d.get("show_in_sidebar") else "  [hidden]"
        admin = "  [admin]" if d.get("require_admin") else ""
        yaml_mode = "  [yaml: edit its file]" if d.get("mode") == "yaml" else ""
        print(
            f"{d['url_path']:30s}  {d.get('title', '(no title)')}"
            f"{sidebar}{admin}{yaml_mode}"
        )


def cmd_get(args):
    cmd = {"type": "lovelace/config"}
    if args.url_path != "default":
        cmd["url_path"] = args.url_path
    print(json.dumps(ha_result(cmd), indent=2))


def _validate_json(raw: str) -> dict:
    """Parse JSON and check it has the shape of a Lovelace config."""
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Invalid JSON: {e}") from None
    if not isinstance(obj, dict) or not (
        isinstance(obj.get("views"), list) or isinstance(obj.get("strategy"), dict)
    ):
        raise RuntimeError(
            "dashboard config must be a JSON object with a 'views' list "
            "(or a 'strategy' object)"
        )
    return obj


def cmd_set(args):
    url_path, file = args.url_path, args.file
    with open(file) as f:
        config = _validate_json(f.read())
    cmd = {"type": "lovelace/config/save", "config": config}
    if url_path != "default":
        cmd["url_path"] = url_path
    ha_result(cmd)
    print(f"Dashboard '{url_path}' saved successfully.")


def cmd_create(args):
    d = ha_result(
        {
            "type": "lovelace/dashboards/create",
            "url_path": args.url_path,
            "title": args.title,
            "icon": args.icon,
            "show_in_sidebar": args.show_in_sidebar,
            "require_admin": args.require_admin,
        }
    )
    print(f"Created dashboard '{d['title']}' (url_path: {d['url_path']})")


def cmd_delete(args):
    ha_result(
        {
            "type": "lovelace/dashboards/delete",
            "dashboard_id": _dashboard_id(args.url_path),
        }
    )
    print(f"Deleted dashboard '{args.url_path}'.")


UPDATE_FIELDS = ("title", "icon", "show_in_sidebar", "require_admin")


def cmd_update(args):
    fields = {
        k: getattr(args, k) for k in UPDATE_FIELDS if getattr(args, k) is not None
    }
    if not fields:
        raise RuntimeError(
            "no metadata flags given "
            "(use --title/--icon/--show/--hidden/--admin/--no-admin)"
        )
    d = ha_result(
        {
            "type": "lovelace/dashboards/update",
            "dashboard_id": _dashboard_id(args.url_path),
            **fields,
        }
    )
    print(f"Updated dashboard '{d['title']}' (url_path: {d['url_path']})")


# --- Entry point ---


def add_meta_flags(p, show_in_sidebar=None, require_admin=None):
    """Add --hidden/--show and --admin/--no-admin; None defaults mean "unchanged"."""
    sidebar = p.add_mutually_exclusive_group()
    sidebar.add_argument(
        "--hidden",
        dest="show_in_sidebar",
        action="store_false",
        help="Hide from sidebar",
    )
    sidebar.add_argument(
        "--show",
        dest="show_in_sidebar",
        action="store_true",
        help="Show in sidebar" + (" (default)" if show_in_sidebar else ""),
    )
    p.add_argument(
        "--admin",
        dest="require_admin",
        action=argparse.BooleanOptionalAction,
        help="Require admin access"
        + (" (default: no)" if require_admin is False else ""),
    )
    p.set_defaults(show_in_sidebar=show_in_sidebar, require_admin=require_admin)


def main():
    parser = argparse.ArgumentParser(
        prog="ha-dashboard",
        description="Manage Home Assistant Lovelace dashboards via WebSocket API.",
    )
    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.required = True

    sub.add_parser("list", help="List all dashboards").set_defaults(func=cmd_list)

    p_get = sub.add_parser("get", help="Print dashboard config JSON to stdout")
    p_get.add_argument("url_path")
    p_get.set_defaults(func=cmd_get)

    p_set = sub.add_parser("set", help="Save dashboard config from a JSON file")
    p_set.add_argument("url_path")
    p_set.add_argument("file", help="JSON file to read")
    p_set.set_defaults(func=cmd_set)

    p_create = sub.add_parser("create", help="Create a new empty dashboard")
    p_create.add_argument("url_path", help="URL slug, e.g. my-dashboard")
    p_create.add_argument("title", help="Display name")
    p_create.add_argument("--icon", default="mdi:view-dashboard", metavar="mdi:NAME")
    add_meta_flags(p_create, show_in_sidebar=True, require_admin=False)
    p_create.set_defaults(func=cmd_create)

    p_delete = sub.add_parser("delete", help="Delete a dashboard and its config")
    p_delete.add_argument("url_path")
    p_delete.set_defaults(func=cmd_delete)

    p_update = sub.add_parser("update", help="Update dashboard metadata")
    p_update.add_argument("url_path")
    p_update.add_argument("--title", default=None)
    p_update.add_argument("--icon", default=None, metavar="mdi:NAME")
    add_meta_flags(p_update)
    p_update.set_defaults(func=cmd_update)

    run_cli(parser)


if __name__ == "__main__":
    main()
