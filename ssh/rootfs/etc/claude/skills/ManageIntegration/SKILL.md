---
name: ManageIntegration
description:
  Add, configure, reload, disable or delete integrations (config entries)
  and config-flow helpers through ha-integrations. USE WHEN setting up an
  integration, changing its options or credentials, an integration failed or
  keeps retrying, a device "stopped working" or is unavailable, or listing
  discovered devices. Never read or edit .storage/core.config_entries.
---

# ManageIntegration

Use `ha-integrations` for anything about integrations. An integration
instance is a config entry; Home Assistant stores them in
`.storage/core.config_entries`, which is off limits. This tool goes through
the same API as the UI, so changes apply live, usually without a restart.

`ha-integrations` is on `PATH`: call it by bare name (a path form such as
`./ha-integrations` is rewritten to it anyway). If a call errors, fix the call
rather than writing ad-hoc `ha_lib` scripts or `curl`.

## Commands

```bash
ha-integrations list [--domain D] [--search TEXT] [--state S] [--failing]
ha-integrations show <entry>                 # devices, entities, subentries
ha-integrations handlers [--search TEXT] [--helpers]   # what can be added
ha-integrations discovered                   # found devices awaiting setup
ha-integrations schema add <domain>          # first step, submits nothing
ha-integrations schema options|reconfigure <entry>
ha-integrations add <domain> [--step INPUT ...]
ha-integrations options <entry> [--step INPUT ...]
ha-integrations reconfigure <entry> [--step INPUT ...]
ha-integrations update <entry> [--title T] [--polling|--no-polling]
                       [--new-entities|--no-new-entities] [--dry-run]
ha-integrations disable <entry> [--dry-run]
ha-integrations enable <entry>
ha-integrations reload <entry>
ha-integrations delete <entry> [--dry-run]
```

`<entry>` is an entry_id, the entry's title, or a domain with only one
entry. Output is YAML by default (`--format json` for JSON).

## Flows: add, options, reconfigure

These drive the same multi-step dialog the UI shows. Each `--step` answers
the next step in order: a JSON object for a form, an option id for a menu.

1. **Look at the first step** with `schema`. Each field comes with its
   `label`, `help`, `selector` or `type`, whether it is `required`, and its
   `current` value (what the UI would pre-fill; passwords show as
   `********`). A menu lists its `options`.
2. **Ask the user** for anything you cannot look up: hosts, usernames,
   which option they want. Never invent credentials.
3. **Run it** with one `--step` per step. A form only needs the fields you
   change: the others are sent with their `current` value, as the UI does
   (`submitted[].kept` lists them), and `null` leaves a field empty. If the
   steps run out, the run stops with `status: needs_input` and shows the
   next step; add another `--step` and run the whole command again. A
   stopped run aborts the flow, so nothing is half-saved.
4. **Read the result.** `created` (add), `saved` (options) and
   `reconfigured` are success. `changes` shows each field before and after,
   and `verified` says whether reopening the form shows the new values
   (`null` means that form does not pre-fill them, so it could not be
   checked).

```bash
# What does the MQTT setup ask for?
ha-integrations schema add mqtt

# Menu choice, then the broker form; the password comes from secrets.yaml
ha-integrations add mqtt --step broker \
  --step '{"broker": "core-mosquitto", "port": 1883, "username": "ha", "password": "!secret mqtt_password"}'

# Change one option; every other field keeps its current value
ha-integrations schema options "Hue Bridge"
ha-integrations options "Hue Bridge" --step '{"allow_hue_groups": true}'

# Point an entry at a new IP
ha-integrations reconfigure shelly_plug --step '{"host": "192.168.1.40"}'
```

Statuses that exit 1: `needs_input` (answer the shown step), `rejected`
(the integration refused the input; `step.errors` says why, often
`cannot_connect` or `invalid_auth`), `invalid` (a value has the wrong
shape), `aborted` (`reason`, e.g. `already_configured`), `external` (an
OAuth or browser step: tell the user to finish in the UI), `timeout`.
Before failing, the tool checks whether Home Assistant changed the entry
anyway (some flows save, then end with an abort); if it did, the status is
the success one and `notes` says so.

## Other changes

```bash
ha-integrations list --failing                 # what is broken right now
ha-integrations show hue                       # its devices and entities
ha-integrations update hue --title "Hue Upstairs"
ha-integrations update hue --no-polling        # stop polling, keep the entry
ha-integrations reload hue                     # after a network change etc.
ha-integrations disable hue --dry-run          # what goes unavailable
ha-integrations delete hue --dry-run           # what gets removed
```

## Rules

- **Before `delete` or `disable`**, run it with `--dry-run`, then check
  what uses the listed entities with `ha-entities refs <entity> --device`
  (FindReferences skill) and show the user. Both commands ask the user
  for confirmation; a `--dry-run` does not.
- **Passwords:** check `ha-secrets keys --search <domain>` first
  (ManageSecrets skill). If a matching key exists, pass `"!secret NAME"`:
  the tool reads it and sends it without printing it. Otherwise ask the
  user, and pass what they give you; it is masked in the output.
- A config-flow integration added here is live at once; no `ha core
restart` is needed. Integrations that are only configured in YAML are not
  listed by `handlers` and are set up in `configuration.yaml` instead.
- Subentries (for example extra conversation agents) are listed by `show`
  but are changed in the UI.
- **Helpers** set up through a config flow (template, group, threshold,
  utility meter, min/max) are listed by `handlers --helpers` and added
  like any integration. Toggles, dropdowns and other `input_*` helpers
  are YAML plus `ha-reload`.
- The token's user must be an administrator; the config entry API is
  admin-only.
