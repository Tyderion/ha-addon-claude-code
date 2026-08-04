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
from ha_lib import ha_result


def _dashboard_id(url_path: str) -> str:
    """Look up the dashboard_id used by update/delete from its url_path."""
    for d in ha_result({"type": "lovelace/dashboards/list"}) or []:
        if d.get("url_path") == url_path:
            return d["id"]
    raise RuntimeError(
        f"no dashboard with url_path '{url_path}' — run `ha-dashboard list`"
    )


# --- Commands ---


def cmd_list():
    dashboards = ha_result({"type": "lovelace/dashboards/list"}) or []
    print(f"{'default':30s}  (main dashboard)")
    for d in dashboards:
        sidebar = "" if d.get("show_in_sidebar") else "  [hidden]"
        admin = "  [admin]" if d.get("require_admin") else ""
        print(f"{d['url_path']:30s}  {d.get('title', '(no title)')}{sidebar}{admin}")


def cmd_get(url_path: str):
    cmd = {"type": "lovelace/config"}
    if url_path != "default":
        cmd["url_path"] = url_path
    print(json.dumps(ha_result(cmd), indent=2))


def _validate_json(raw: str) -> dict:
    """Parse JSON and check it has the shape of a Lovelace config."""
    try:
        obj = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"Error: Invalid JSON: {e}", file=sys.stderr)
        sys.exit(1)
    if not isinstance(obj, dict) or not (
        isinstance(obj.get("views"), list) or isinstance(obj.get("strategy"), dict)
    ):
        print(
            "Error: dashboard config must be a JSON object with a 'views' list "
            "(or a 'strategy' object)",
            file=sys.stderr,
        )
        sys.exit(1)
    return obj


def cmd_set(url_path: str, file: str):
    try:
        with open(file) as f:
            raw = f.read()
    except OSError as e:
        print(f"Error: cannot read {file}: {e}", file=sys.stderr)
        sys.exit(1)
    config = _validate_json(raw)
    cmd = {"type": "lovelace/config/save", "config": config}
    if url_path != "default":
        cmd["url_path"] = url_path
    ha_result(cmd)
    print(f"Dashboard '{url_path}' saved successfully.")


def cmd_create(
    url_path: str, title: str, icon: str, show_in_sidebar: bool, require_admin: bool
):
    d = ha_result(
        {
            "type": "lovelace/dashboards/create",
            "url_path": url_path,
            "title": title,
            "icon": icon,
            "show_in_sidebar": show_in_sidebar,
            "require_admin": require_admin,
        }
    )
    print(f"Created dashboard '{d['title']}' (url_path: {d['url_path']})")


def cmd_delete(url_path: str):
    ha_result(
        {
            "type": "lovelace/dashboards/delete",
            "dashboard_id": _dashboard_id(url_path),
        }
    )
    print(f"Deleted dashboard '{url_path}'.")


def cmd_update(url_path: str, title, icon, show_in_sidebar, require_admin):
    if all(v is None for v in (title, icon, show_in_sidebar, require_admin)):
        print(
            "Error: no metadata flags given "
            "(use --title/--icon/--show/--hidden/--admin/--no-admin)",
            file=sys.stderr,
        )
        sys.exit(1)
    cmd = {
        "type": "lovelace/dashboards/update",
        "dashboard_id": _dashboard_id(url_path),
    }
    if title is not None:
        cmd["title"] = title
    if icon is not None:
        cmd["icon"] = icon
    if show_in_sidebar is not None:
        cmd["show_in_sidebar"] = show_in_sidebar
    if require_admin is not None:
        cmd["require_admin"] = require_admin
    d = ha_result(cmd)
    print(f"Updated dashboard '{d['title']}' (url_path: {d['url_path']})")


# --- Entry point ---


def main():
    parser = argparse.ArgumentParser(
        prog="ha-dashboard",
        description="Manage Home Assistant Lovelace dashboards via WebSocket API.",
    )
    sub = parser.add_subparsers(dest="command", metavar="command")
    sub.required = True

    sub.add_parser("list", help="List all dashboards")

    p_get = sub.add_parser("get", help="Print dashboard config JSON to stdout")
    p_get.add_argument("url_path")

    p_set = sub.add_parser("set", help="Save dashboard config from a JSON file")
    p_set.add_argument("url_path")
    p_set.add_argument("file", help="JSON file to read")

    p_create = sub.add_parser("create", help="Create a new empty dashboard")
    p_create.add_argument("url_path", help="URL slug, e.g. my-dashboard")
    p_create.add_argument("title", help="Display name")
    p_create.add_argument("--icon", default="mdi:view-dashboard", metavar="mdi:NAME")
    sidebar = p_create.add_mutually_exclusive_group()
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
        help="Show in sidebar (default)",
    )
    p_create.set_defaults(show_in_sidebar=True)
    admin = p_create.add_mutually_exclusive_group()
    admin.add_argument(
        "--admin",
        dest="require_admin",
        action="store_true",
        help="Require admin access",
    )
    admin.add_argument(
        "--no-admin",
        dest="require_admin",
        action="store_false",
        help="No admin requirement (default)",
    )
    p_create.set_defaults(require_admin=False)

    p_delete = sub.add_parser("delete", help="Delete a dashboard and its config")
    p_delete.add_argument("url_path")

    p_update = sub.add_parser("update", help="Update dashboard metadata")
    p_update.add_argument("url_path")
    p_update.add_argument("--title", default=None)
    p_update.add_argument("--icon", default=None, metavar="mdi:NAME")
    sidebar2 = p_update.add_mutually_exclusive_group()
    sidebar2.add_argument(
        "--hidden",
        dest="show_in_sidebar",
        action="store_false",
        help="Hide from sidebar",
    )
    sidebar2.add_argument(
        "--show", dest="show_in_sidebar", action="store_true", help="Show in sidebar"
    )
    p_update.set_defaults(show_in_sidebar=None)
    admin2 = p_update.add_mutually_exclusive_group()
    admin2.add_argument(
        "--admin",
        dest="require_admin",
        action="store_true",
        help="Require admin access",
    )
    admin2.add_argument(
        "--no-admin",
        dest="require_admin",
        action="store_false",
        help="No admin requirement",
    )
    p_update.set_defaults(require_admin=None)

    args = parser.parse_args()

    try:
        if args.command == "list":
            cmd_list()
        elif args.command == "get":
            cmd_get(args.url_path)
        elif args.command == "set":
            cmd_set(args.url_path, args.file)
        elif args.command == "create":
            cmd_create(
                args.url_path,
                args.title,
                args.icon,
                args.show_in_sidebar,
                args.require_admin,
            )
        elif args.command == "delete":
            cmd_delete(args.url_path)
        elif args.command == "update":
            cmd_update(
                args.url_path,
                args.title,
                args.icon,
                args.show_in_sidebar,
                args.require_admin,
            )
    except (RuntimeError, OSError) as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
