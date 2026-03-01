---
name: EditDashboard
description:
  Manage Home Assistant Lovelace dashboards via the WebSocket API — get,
  set, create, delete, and update. USE for any dashboard operation. NEVER edit
  .storage/lovelace.* files directly — they will go stale.
---

# EditDashboard

Use `ha-dashboard` to manage Lovelace dashboards through the HA WebSocket API — the same path the frontend uses. This avoids stale-data overwrites.

## One-Time Setup

A long-lived HA access token is required:

1. HA UI → Profile (bottom-left) → **Security** tab → **Long-Lived Access Tokens** → Create Token
2. Name it "Claude Dashboard API"
3. Copy the token and save it:
   ```bash
   echo "your_token_here" > /homeassistant/.claude/ha_token
   chmod 600 /homeassistant/.claude/ha_token
   ```

## Commands

```bash
ha-dashboard list                                    # List all dashboards
ha-dashboard get <url_path>                          # Print config JSON to stdout
ha-dashboard set <url_path>                          # Read JSON from stdin and save
ha-dashboard create <url_path> <title> [options]     # Create a new empty dashboard
ha-dashboard delete <url_path>                       # Delete a dashboard (permanent)
ha-dashboard update <url_path> [options]             # Update metadata only
```

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
ha-dashboard list                                      # find the correct url_path
ha-dashboard get dashboard-name > /tmp/dashboard.json
# edit /tmp/dashboard.json with Edit tool
ha-dashboard set dashboard-name < /tmp/dashboard.json   # JSON is validated before push
```

## Workflow: Create a New Dashboard

```bash
# 1. Register the dashboard
ha-dashboard create my-new-dash "My Dashboard" --icon mdi:home

# 2. Build its config and push it
ha-dashboard get dashboard-name > /tmp/new.json   # start from an existing one, or build from scratch
# edit /tmp/new.json
ha-dashboard set my-new-dash < /tmp/new.json
```

## Workflow: Delete a Dashboard

```bash
ha-dashboard delete my-new-dash
```

Deletion is **permanent** — the dashboard registration and all its card config are removed.

## Workflow: Rename / Update Metadata

```bash
ha-dashboard update dashboard-name --title "Phone" --icon mdi:phone
ha-dashboard update my-dash --hidden          # remove from sidebar
ha-dashboard update my-dash --show --admin    # restore + require admin
```

## Rules

- **Always save dashboard JSON to `/tmp/`** — use `/tmp/<url_path>.json` as the working file (e.g. `/tmp/dashboard-name.json`). You have read/edit/write permissions for `/tmp/*.json`.
- **Always GET first** before editing config — never use stale file reads
- **Never write `.storage/lovelace.*` files directly** — HA's in-memory state won't update
- **JSON is validated automatically** — `set` validates input before pushing (no need for manual `python3 -m json.tool`)
- `create` makes an empty dashboard — always follow with `set` to add cards
- `update` only changes metadata (title, icon, sidebar, admin); use `set` for card changes
- `dashboard_id` (internal HA concept) is derived automatically from `url_path` — never needed in commands
- Changes are live immediately after `set`, `create`, `delete`, or `update` — no reload needed
