---
name: ManageSystem
description: Apps (add-ons), pending updates, repairs and system health, through ha-system and the ha CLI. USE WHEN restarting, stopping, updating or reading the logs of an app or add-on, an app won't start, the user asks what updates are waiting or to update something, what a repair means, or whether the system is healthy, supported or low on disk.
---

# ManageSystem

`ha-system` answers what is pending and what is wrong; it only reads. The `ha` Supervisor CLI does everything to apps (add-ons). Both are on `PATH`.

Every `ha` command asks the user first except reads (`info`, `logs`, `stats`, `check`, bare listings such as `ha apps`) and a few routine ones (`ha apps start`, `ha backups new`, `ha refresh-updates`). The prompt is expected; say what the command is for before running it.

## Commands

```bash
ha-system updates [--all]       # pending updates: core, os, supervisor, app, hacs, firmware
ha-system repairs [--all]       # repair issues with their text, plus Supervisor issues
ha apps                         # every app: name, slug, state, version
ha apps info <slug>             # state, boot, version, update_available
ha apps logs <slug> -n 200      # its log
ha apps changelog <slug>        # what the pending update brings
ha apps restart <slug>          # also stop, start
```

## Apps

- An app is addressed by its slug, not its name: Mosquitto is `core_mosquitto`, a community app looks like `45df7312_zigbee2mqtt`. `ha apps` lists both.
- Always pass `-n` to any `logs` command. `-f` streams forever and the call never returns.
- The app whose slug ends in `_claude` is this one. Restarting, stopping, rebuilding or updating it ends the session you are running in, so ask the user to do it from the UI instead.
- Restarting Mosquitto, Zigbee2MQTT, Matter Server or OpenThread Border Router drops their devices for a few seconds; say so when you ask.
- **An app won't start:** `ha apps info <slug>` (state, boot), then `ha apps logs <slug> -n 200`, then `ha-system repairs`, which shows a boot failure as a repair. If the log comes back empty, `ha host logs -n 200 -t addon_<slug>` reads the journal directly.

## Updates

`ha-system updates` lists what has a newer version, with `kind`, `installed`, `latest`, `release_url`, and `slug` for apps. Its `notes` explain what is left out: firmware entities that report no latest version are not pending updates, and updates skipped in the UI need `--all`. `ha refresh-updates` makes the Supervisor check again first.

Installing goes through a different command per kind, and every one asks:

| kind         | Install with                                                   | Notes                                                                         |
| ------------ | -------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| `core`       | `ha core update --backup`                                      | Read `release_url` first; Core updates can break integrations                 |
| `app`        | `ha apps update <slug> --backup`                               | `ha apps changelog <slug>` says what changes                                  |
| `os`         | `ha backups new --name before-os-update`, then `ha os update`  | Reboots the host; no `--backup` flag                                          |
| `supervisor` | `ha supervisor update`                                         | Usually updates itself (`auto_update: true`)                                  |
| `hacs`       | `ha-service call update.install --entity <entity_id> --unsafe` | A HACS integration needs `ha core restart` afterwards to load the new version |
| `firmware`   | `ha-service call update.install --entity <entity_id> --unsafe` | The device may drop off while it flashes                                      |

To skip a version: `ha-service call update.skip --entity <entity_id>`.

## Repairs

`ha-system repairs` lists what Settings → Repairs shows, worst first: `title`, `description`, `severity`, `fixable`, `breaks_in` (the version that stops supporting it), `learn_more_url`. Ignored ones need `--all`.

- **Fixing** a fixable Core repair, or ignoring one, is a flow in Settings → Repairs. There is no tool for it; tell the user, and do the edit the description asks for (YAML, an integration) when it is yours to do.
- Rows with `source: supervisor` exist only in the Supervisor. Their `suggestions` are what it can do about them: `ha resolution suggestion apply <suggestion uuid>`.
- `system.unhealthy` and `system.unsupported` are reasons the Supervisor marks the system unhealthy or unsupported; each has a page at `https://www.home-assistant.io/more-info/unhealthy/<reason>` (or `unsupported/`).

## System health

- `ha host info`: disk free, used and total, OS, kernel.
- `ha core stats`, `ha supervisor stats`, `ha apps stats <slug>`: CPU and memory.
- `ha os datadisk list`: the data disk and the disks it could move to.
- `ha resolution info`, `ha resolution healthcheck`: the Supervisor's own view and a fresh run of its checks; `ha-system repairs` already shows their results.
