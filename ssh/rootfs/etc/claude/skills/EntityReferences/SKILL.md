---
name: EntityReferences
description: Find everything that uses a Home Assistant entity or device —
  automations, scripts, scenes, groups, persons, dashboards, templates and
  YAML packages — by combining Home Assistant's own Related search with a
  scan of the config files. USE WHEN asking what uses / references /
  depends on an entity or device, where an entity is used, whether it is
  safe to rename, remove, replace or disable an entity or device, before
  changing an entity_id, before removing a device or integration, or when
  cleaning up unused entities. ALWAYS use ha-entities refs for this —
  never grep /homeassistant by hand, which misses UI dashboards, UI
  helpers and device-id references.
---

# EntityReferences

Use `ha-entities refs` to answer "what uses this?". It merges two sources:

- **Home Assistant's Related search** (the UI's Related tab): automations,
  scripts, scenes, groups and persons that Home Assistant itself resolves
  as referencing the entity, including device triggers and actions.
- **A text scan** of the YAML config, plus UI-made dashboards and helpers
  under `.storage`. This also catches templates (`states('sensor.x')`),
  which the Related search does not see, and dashboards, which it does
  not cover at all.

`ha-entities` is on `PATH`: invoke it by bare name exactly as shown, never
`./ha-entities` or another path form.

## Commands

```bash
ha-entities refs <entity_id> [<entity_id> ...]    # one or more entities
ha-entities refs <entity_id> --device             # all entities of its device
```

Output is YAML by default (`--format json` for JSON). It is read-only and
never prompts.

## Examples

```bash
# Is this sensor used anywhere?
ha-entities refs sensor.kitchen_temperature

# Several at once
ha-entities refs light.hallway switch.hallway_fan

# Everything that depends on a device, e.g. before replacing it: every
# entity it has, plus automations that use it by device_id
ha-entities refs light.hallway_controller_light --device
```

## Output

- Without `--device`: `entities: {<entity_id>: {automations, scripts,
scenes, groups, persons, files}}`, keys present only when non-empty.
  An empty `{}` means nothing references it.
- With `--device`: `devices: [{device_id, name, references, entities}]`,
  where `references` holds what uses the device itself (device triggers,
  conditions and actions address it by `device_id`) and `entities` has one
  entry per entity of the device.
- `files` entries are `{file, line, text}`, paths relative to
  `/homeassistant`. A file under `.storage/lovelace*` is a UI dashboard
  (change it with `ha-dashboard`); `.storage/core.config_entries` is a UI
  helper (change it in the UI). Never edit either by hand.
- `total_references` is the number of hits across everything. An
  automation found by both sources counts twice.

## How to Use the Result

- **Before renaming entity_ids**: run `refs` on every entity you plan to
  rename (or `--device` for a whole device) and show the user the result
  before running any `ha-entities rename`. Then follow the UpdateEntity
  skill.
- **Before removing or replacing a device**: `refs --device` shows the
  device_id references too. Those break even when a new device keeps the
  same entity_ids, because the new device gets a new device_id.
- **"Is this unused?"**: an empty result means nothing in the config or
  in Home Assistant's registries references it. History and long-term
  statistics are separate (QueryHistory).

## Limits

- The text scan skips `custom_components`, `deps`, `.git` and any file
  over 5 MB, and only reads `.yaml`/`.yml` files plus the dashboard and
  helper stores under `.storage`.
- A reference built at runtime (`states('light.' ~ room)`) cannot be
  found by either source.
