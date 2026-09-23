---
name: UpdateEntity
description:
  Change how an entity or device is registered in Home Assistant — display
  name, area, icon, hidden or disabled, and its entity_id — through the
  registry API, with before/after output and read-back verification. USE
  WHEN renaming an entity or device, changing its friendly name, moving it
  to another area/room, setting an icon, hiding or unhiding, disabling or
  enabling, or changing an entity_id. ALWAYS use ha-entities update/rename
  for these — never edit .storage/core.entity_registry or
  core.device_registry.
---

# UpdateEntity

Use `ha-entities update` and `ha-entities rename` to change registry
settings. They go through Home Assistant's WebSocket registry API, which
applies changes live with no restart and no risk to the `.storage` files.

`ha-entities` is on `PATH`: invoke it by bare name exactly as shown, never
`./ha-entities` or another path form. If a call errors, fix the invocation
rather than dropping to ad-hoc `ha_lib` scripts or editing `.storage`.

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

Output is YAML by default (`--format json` for JSON).

## Examples

```bash
# Find the entity first; never guess the id
ha-entities list --search "ceiling"

# Rename it and move it to another area
ha-entities update light.hue_color_lamp_1 --name "Kitchen Ceiling" --area Kitchen

# Move the whole device (all its entities follow unless they set their own area)
ha-entities update light.hue_color_lamp_1 --device --area "Living Room"

# Rename the device itself (what the device page and the name prefix show)
ha-entities update light.hue_color_lamp_1 --device --name "Kitchen Lamp"

# Back to the integration's own name; clear the entity's own area
ha-entities update light.hue_color_lamp_1 --reset-name --no-area

# Hide from auto-generated dashboards / disable entirely
ha-entities update sensor.lamp_signal_strength --hidden
ha-entities update sensor.lamp_signal_strength --disable

# Change an entity_id: list what still references it first
ha-entities rename light.hue_color_lamp_1 light.kitchen_ceiling --dry-run
ha-entities rename light.hue_color_lamp_1 light.kitchen_ceiling
```

## Workflow

1. **Find the entity** with `ha-entities list --search TEXT`, and the area
   names with `ha-entities areas`. `--area` takes an area's name or
   area_id, case-insensitive; a new area has to be created in the UI first.
2. **Entity or device?** A physical thing ("move the lamp to the bedroom",
   "call the plug Coffee Machine") is usually a `--device` change. An
   entity-level area or name overrides the device's for that entity only.
3. **Run it** and read `changes` (each field before and after) and
   `verified`. A mismatch exits 1 and names the fields that differ.
4. **For `rename`**, always do `--dry-run` first and show the user the
   `references`. Home Assistant does not rewrite YAML: after renaming,
   update every listed YAML file with the Edit tool and run `ha-reload`.
   References under `.storage` are UI-made dashboards (fix with
   `ha-dashboard`) or UI helpers (fix in the UI, never by hand).

## Gotchas

- Entities without a `unique_id` (plain YAML sensors, templates without
  one) are not in the registry. The tool says so; change those in their
  YAML, or in `customize.yaml` for friendly_name and icon.
- `--name` on an entity replaces its own name. Many integrations show the
  device name plus the entity name, so renaming the device is often what
  the user actually wants.
- `--no-area` on an entity makes it inherit its device's area; it does not
  leave it without an area if the device has one.
- `--enable` may need an integration reload (the output says after how
  many seconds) or a restart (`notes` says so). Enabling an entity of a
  disabled device is refused by Home Assistant.
- `--icon`, `--hidden`/`--visible` and `--disable`/`--enable` are
  entity-only; they are refused together with `--device`.
- `rename` always prompts for confirmation, because a renamed entity_id
  breaks every automation, script and dashboard that still uses the old
  one.

## Setup

Requires the same long-lived token as `ha-entities` (HA_TOKEN env var or
`/homeassistant/.claude/ha_token`), and the token's user must be an
administrator, since the registry API is admin-only.
