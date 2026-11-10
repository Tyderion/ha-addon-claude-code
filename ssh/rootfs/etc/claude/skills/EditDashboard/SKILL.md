---
name: EditDashboard
description:
  Manage Lovelace dashboards, views, cards and badges through ha-dashboard.
  USE WHEN anything touches a dashboard ("add this to my overview", "make a
  tab for the garden"). NOT FOR YAML-mode dashboards (ui-lovelace.yaml),
  which are plain files. Never edit .storage/lovelace.* by hand.
---

# EditDashboard

Use `ha-dashboard`, which goes through the HA WebSocket API like the frontend does. `set` replaces the whole config, so an edit made in the HA UI between your `get` and `set` is lost; keep that window short.

`ha-dashboard` is on `PATH`: call it by bare name (a path form such as `./ha-dashboard` is rewritten to it anyway). If a call errors, fix the call rather than writing ad-hoc `ha_lib` scripts or `curl`.

## Commands

```bash
ha-dashboard list                                    # List all dashboards
ha-dashboard get <url_path>                          # Print config JSON to stdout
ha-dashboard set <url_path> <file>                   # Save dashboard config from JSON file
ha-dashboard create <url_path> <title> [options]     # Create a new empty dashboard
ha-dashboard delete <url_path>                       # Delete a dashboard (permanent)
ha-dashboard update <url_path> [options]             # Update metadata only
```

The special `url_path` **`default`** addresses the main dashboard (the first row in `list` output). It works with `get` and `set` only; the main dashboard has no entry HA can `update` or `delete`.

### create / update options

| Flag                     | Meaning            | Default                            |
| ------------------------ | ------------------ | ---------------------------------- |
| `--icon mdi:NAME`        | MDI icon           | `mdi:view-dashboard` (create only) |
| `--show` / `--hidden`    | Sidebar visibility | shown (create), unchanged (update) |
| `--admin` / `--no-admin` | Require admin      | false (create), unchanged (update) |
| `--title TITLE`          | Display name       | — (update only)                    |

## Workflow: Edit Config

`list` first, since the user's name for a dashboard is rarely its exact `url_path`. Then back it up, edit a copy in `/tmp/`, and `set` it from the file. The backup is the only recovery path; `get` fresh each time rather than reusing an earlier `/tmp` copy. Keep the files directly under `/tmp/` with a `.json` suffix, the one `/tmp` pattern the Edit tool may change without asking.

```bash
ha-dashboard list
ha-dashboard get dashboard-name > /tmp/dashboard-name.backup.json
cp /tmp/dashboard-name.backup.json /tmp/dashboard-name.json
# edit /tmp/dashboard-name.json with the Edit tool
ha-dashboard set dashboard-name /tmp/dashboard-name.json
```

## Workflow: Create a New Dashboard

`url_path` must be a lowercase slug **containing a hyphen** (`garden-tab`, not `garden`) that does not clash with a built-in panel; HA rejects anything else with `invalid_format`.

```bash
# 1. Register the dashboard (it starts empty, so `get` on it fails)
ha-dashboard create my-new-dash "My Dashboard" --icon mdi:home

# 2. Build its config and push it: start from another dashboard,
#    or from the minimal shape {"views": [{"title": "Home", "cards": []}]}
ha-dashboard get dashboard-name > /tmp/new.json
# edit /tmp/new.json with the Edit tool
ha-dashboard set my-new-dash /tmp/new.json
```

## Workflow: Delete a Dashboard

No hook asks before `delete` or `set`: each runs the moment it is issued, so confirm with the user and take the backup first.

```bash
ha-dashboard get my-new-dash > /tmp/my-new-dash.backup.json
ha-dashboard delete my-new-dash
```

Deletion is **permanent**: the registration and all its card config go.

## Workflow: Rename / Update Metadata

```bash
ha-dashboard update dashboard-name --title "Phone" --icon mdi:phone
ha-dashboard update my-dash --hidden          # remove from sidebar
ha-dashboard update my-dash --show --admin    # restore + require admin
```

## Gotchas

- `set` takes a file path only; stdin (`cat file | ha-dashboard set …`, `< file`) is not supported.
- `set` parses the JSON and checks for a top-level `views` list (or `strategy` object) before pushing, so don't run `jq` or `python3 -m json.tool` on it first. Nothing checks card contents: a wrong card type or entity renders as an error card in the UI, so tell the user what to look at after a large change.
- `get` exits 1 with `config_not_found` when nothing is stored, and the `>` redirect leaves an empty backup file behind. That happens on a dashboard you just created, where you `set` a `views` config directly, and on HA's default Overview if it was never edited. The Overview is auto-generated, like any dashboard whose `get` returns `{"strategy": {...}}`: `set` with static `views` converts it and discards auto-population, so confirm with the user first. `set` also accepts a `{"strategy": {...}}` object, so `{"strategy": {"type": "original-states"}}` puts a dashboard back on auto-generation.
- `list` marks YAML-mode dashboards (declared in `configuration.yaml`) with `[yaml: edit its file]`. `get` shows their config, but `set`, `update` and `delete` do not work on them; edit their YAML file instead.
- `get` and `list` work with any token; `set`, `create`, `update` and `delete` need an administrator's token.
- Every command takes effect immediately; no reload needed.
