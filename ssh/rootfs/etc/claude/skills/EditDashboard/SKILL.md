---
name: EditDashboard
description:
  Manage Home Assistant Lovelace dashboards, views, cards, tiles, badges, and
  sidebar entries via the WebSocket API — get, set, create, delete, and update.
  USE for any dashboard, Lovelace, view, or card operation. NEVER edit
  .storage/lovelace.* files directly — they will go stale.
---

# EditDashboard

Use `ha-dashboard` to manage Lovelace dashboards through the HA WebSocket API — the same path the frontend uses. This avoids stale file reads; note that a concurrent edit made in the HA UI between `get` and `set` will still be overwritten.

## Setup

A long-lived HA access token is required (one-time). If it's missing, `ha-dashboard` exits with the exact setup instructions — just follow them (HA UI → Profile → Security → Long-Lived Access Tokens, save to `/homeassistant/.claude/ha_token`).

## Commands

```bash
ha-dashboard list                                    # List all dashboards
ha-dashboard get <url_path>                          # Print config JSON to stdout
ha-dashboard set <url_path> <file>                   # Save dashboard config from JSON file
ha-dashboard create <url_path> <title> [options]     # Create a new empty dashboard
ha-dashboard delete <url_path>                       # Delete a dashboard (permanent)
ha-dashboard update <url_path> [options]             # Update metadata only
```

The special `url_path` **`default`** addresses the main dashboard (the first row in `list` output).

### create / update options

| Flag                     | Meaning            | Default                            |
| ------------------------ | ------------------ | ---------------------------------- |
| `--icon mdi:NAME`        | MDI icon           | `mdi:view-dashboard` (create only) |
| `--show` / `--hidden`    | Sidebar visibility | shown (create), unchanged (update) |
| `--admin` / `--no-admin` | Require admin      | false (create), unchanged (update) |
| `--title TITLE`          | Display name       | — (update only)                    |

## Workflow: Edit Config

Always LIST first to find the correct `url_path`, then GET, modify, and SET back:

```bash
ha-dashboard list                                             # find the correct url_path
ha-dashboard get dashboard-name > /tmp/dashboard.backup.json  # backup — only recovery path
cp /tmp/dashboard.backup.json /tmp/dashboard.json
# edit /tmp/dashboard.json with Edit tool
ha-dashboard set dashboard-name /tmp/dashboard.json           # JSON is validated before push
```

## Workflow: Create a New Dashboard

```bash
# 1. Register the dashboard
ha-dashboard create my-new-dash "My Dashboard" --icon mdi:home

# 2. Build its config and push it
ha-dashboard get dashboard-name > /tmp/new.json   # start from an existing one, or build from scratch
# edit /tmp/new.json
ha-dashboard set my-new-dash /tmp/new.json
```

## Workflow: Delete a Dashboard

```bash
ha-dashboard get my-new-dash > /tmp/my-new-dash.backup.json   # backup first
ha-dashboard delete my-new-dash
```

Deletion is **permanent** — the dashboard registration and all its card config are removed. The backup is the only recovery path.

## Workflow: Rename / Update Metadata

```bash
ha-dashboard update dashboard-name --title "Phone" --icon mdi:phone
ha-dashboard update my-dash --hidden          # remove from sidebar
ha-dashboard update my-dash --show --admin    # restore + require admin
```

## Gotchas

- `get` on a freshly created dashboard (or an auto-generated one with no stored config) returns `config_not_found` — that is expected. Skip `get` and `set` a config with a `views` array directly.
- Dashboards using `{"strategy": {...}}` (including HA's default "Overview") are auto-generated. `set` with a static `views` config **permanently** converts them to static and discards auto-population — confirm with the user first.

## Rules

- **Always back up before `set` or `delete`**: `ha-dashboard get <url_path> > /tmp/<url_path>.backup.json` — it is the only recovery path
- **Always save dashboard JSON to `/tmp/`** — use `/tmp/<url_path>.json` as the working file (e.g. `/tmp/dashboard-name.json`). You have read/edit/write permissions for `/tmp/*.json`.
- **Always pass config as a file path** — `ha-dashboard set <url_path> <file>`. Never pipe via stdin (`cat file | ha-dashboard set …` or `ha-dashboard set … < file`) — stdin is not supported.
- **Always LIST first** before any get/set/delete/update — never assume the exact `url_path`, the user may use a short or approximate name
- **Always GET first** before editing config — never use stale file reads
- **Never write `.storage/lovelace.*` files directly** — HA's in-memory state won't update
- **Do NOT validate JSON manually** — never run `python3 -m json.tool`, `jq`, or any other validation command. The `set` command already validates input before pushing and will report errors if the JSON is invalid.
- `create` makes an empty dashboard — always follow with `set` to add cards
- `update` only changes metadata (title, icon, sidebar, admin); use `set` for card changes
- `dashboard_id` (internal HA concept) is derived automatically from `url_path` — never needed in commands
- Changes are live immediately after `set`, `create`, `delete`, or `update` — no reload needed
