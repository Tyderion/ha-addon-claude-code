---
name: UpdateEntity
description:
  Change how an entity or device is registered (name, area, icon, hidden or
  disabled flag, entity_id) through the registry API. USE WHEN renaming an
  entity or device, moving it to another area, setting an icon, hiding it,
  or changing an entity_id. NOT FOR pausing an automation
  (automation.turn_off via CallService; a registry disable removes it) or
  disabling an integration (ManageIntegration).
---

# UpdateEntity

Use `ha-entities update` and `ha-entities rename` to change registry
settings. They go through Home Assistant's WebSocket registry API, so
changes apply live, without a restart, and nothing writes `.storage` by
hand.

`ha-entities` is on `PATH`: call it by bare name (a path form such as
`./ha-entities` is rewritten to it anyway). If a call errors, fix the call
rather than writing ad-hoc `ha_lib` scripts or `curl`.

## Commands

```bash
ha-entities update <entity_id> [--device]
                   [--name NAME | --reset-name]
                   [--area AREA | --no-area]
                   [--icon ICON | --reset-icon]
                   [--hidden | --visible] [--disable | --enable]
                   [--dry-run]
ha-entities rename <entity_id> <new_entity_id> [--dry-run]
```

Output is YAML by default (`--format json` after the subcommand for JSON).

## Examples

```bash
# Rename an entity and move it to another area
ha-entities update light.hue_color_lamp_1 --name "Kitchen Ceiling" --area Kitchen

# Move the whole device (all its entities follow unless they set their own area)
ha-entities update light.hue_color_lamp_1 --device --area "Living Room"

# Rename the device itself (what the device page and the name prefix show)
ha-entities update light.hue_color_lamp_1 --device --name "Kitchen Lamp"

# Back to the integration's own name; clear the entity's own area
ha-entities update light.hue_color_lamp_1 --reset-name --no-area

# Hide from auto-generated dashboards, or disable it (takes the entity out
# of the state machine; to pause an automation use automation.turn_off)
ha-entities update sensor.lamp_signal_strength --hidden
ha-entities update sensor.lamp_signal_strength --disable

# Change an entity_id: see what uses it first, then rename
ha-entities rename light.hue_color_lamp_1 light.kitchen_ceiling --dry-run
ha-entities rename light.hue_color_lamp_1 light.kitchen_ceiling
```

## Workflow

1. **Areas:** `ha-entities areas` lists them. `--area` takes a name or
   area_id, case-insensitive; a missing area errors with the existing
   names, and a new one has to be created in the UI first.
2. **Entity or device?** A physical thing ("move the lamp to the bedroom",
   "call the plug Coffee Machine") is usually a `--device` change: most
   integrations display device name plus entity name, and a device
   `--name` changes no entity_id, so it breaks nothing. An entity's own
   `--name` or `--area` overrides the device's for that entity only;
   `--no-area` makes it inherit the device's area again. In `--device`
   mode the output's `device` field names the device that was changed;
   check it is the one the user meant.
3. **Run it** (`--dry-run` shows the planned `changes` without applying).
   The real run prints `changes` (each field before and after) and
   `verified`; a read-back mismatch exits 1 and `notes` names the fields.
   `changes: {}` with `note: already set; nothing to do` means nothing was
   needed. `notes` also says when an entity keeps or inherits an area and
   when an enable needs an integration reload or a restart.
4. **For `rename`**, run it with `--dry-run` first and show the user what
   it reports: `references` (file, line and text of every YAML and
   `.storage` line naming the old id) and `used_by` (automations, scripts,
   scenes, groups, persons). For a whole device, `ha-entities refs
<entity> --device` (FindReferences) covers all its entities in one
   call. After the real rename, Home Assistant does not rewrite YAML:
   update every file in `references` with the Edit tool and run
   `ha-reload`. `.storage` hits are UI dashboards (`ha-dashboard`) or
   config entries (`ha-integrations`), never hand edits.

## Gotchas

- Entities without a `unique_id` (plain YAML sensors, templates without
  one) are not in the registry. The tool says so; change those in their
  YAML, or in `customize.yaml` for friendly_name and icon.
- `--icon`, `--hidden`/`--visible` and `--disable`/`--enable` are
  entity-only; they are refused together with `--device`.
- Home Assistant refuses to enable an entity whose device is disabled;
  enable the device first (its integration via ManageIntegration, or the
  UI).
- `rename` cannot change the domain (the part before the dot), takes only
  lowercase letters, digits and underscores, and refuses an id that
  already exists. The tool never asks; the add-on's permission hook asks
  the user before a real `rename`, while `--dry-run` runs without asking.
- Any refusal prints `Error: ...` on stderr and exits 1 with nothing
  applied; the text says what to fix.
- The token's user must be an administrator: with a non-admin token,
  `update` and `rename` fail with `Unauthorized`, while `list`, `get` and
  `refs` still work.
