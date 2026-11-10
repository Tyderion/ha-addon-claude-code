---
name: FindReferences
description:
  Find everything that uses an entity or device (automations, scripts,
  scenes, groups, dashboards, templates, YAML). USE WHEN asking what uses or
  depends on an entity or device, whether it is safe to rename, remove,
  replace or disable one, or when cleaning up unused entities. Use
  ha-entities refs, not grep, which misses UI dashboards and device-id
  references.
---

# FindReferences

Use `ha-entities refs` to answer "what uses this?". It merges two sources:

- **Home Assistant's Related search** (the UI's Related tab): automations,
  scripts, scenes, groups and persons that Home Assistant itself resolves
  as referencing the entity. Automations that address the entity's device
  by `device_id` (device triggers, conditions and actions) show up with
  `--device`.
- **A text scan** of the YAML config and of the UI-made dashboards and
  config entries under `.storage`. This is what finds templates
  (`states('sensor.x')`, `states.sensor.x.state`) and dashboards, which the
  Related search does not see.

`ha-entities` is on `PATH`: call it by bare name (a path form such as
`./ha-entities` is rewritten to it anyway). If a call errors, fix the call
rather than writing ad-hoc `ha_lib` scripts or `curl`.

## Commands

```bash
ha-entities refs <entity_id> [<entity_id> ...]    # one or more entities
ha-entities refs <entity_id> --device             # all entities of its device, plus device_id references
```

Output is YAML by default (`--format json` after `refs` for JSON). It is
read-only and never prompts.

## Output

- Without `--device`: `entities: {<entity_id>: {automations, scripts,
scenes, groups, persons, files}}`, keys present only when non-empty;
  each of the first five is a list of `{entity_id, name}`.
- With `--device`: `devices: [{device_id, name, references, entities}]`,
  one entry per distinct device (two given entities on the same device
  share one). `references` has the same shape as an entity's entry and
  holds what uses the device itself by `device_id`; `entities` is
  `{<entity_id>: {...}}` for every entity of the device.
- `files` entries are `{file, line, text}`, paths relative to
  `/homeassistant`, `text` cut to 160 characters. A file under
  `.storage/lovelace*` is a UI dashboard (change it with `ha-dashboard`);
  `.storage/core.config_entries` is an integration or config-flow helper
  (change it with `ha-integrations`, ManageIntegration). Never edit either
  by hand.
- `total_references` counts every list element: each Related-search item
  once and each matching file line once, so an automation found by both
  sources counts in `automations` and again for each line naming the
  entity.

## How to Use the Result

- **"Is this unused?"**: an empty `{}` means neither source found
  anything, within the Limits below. History and long-term statistics are
  separate (QueryHistory).
- **Before renaming entity_ids**: `refs` every entity you plan to rename
  (`--device` for a whole device), show the user what uses them, then
  follow UpdateEntity, which covers the rename and fixing the references
  afterwards.
- **Before removing or replacing a device**: `refs --device` shows the
  device_id references too. Those break even when a new device keeps the
  same entity_ids, because the new device gets a new device_id.

## Limits

- The text scan reads `.yaml`/`.yml` files under `/homeassistant`,
  skipping `.git`, `.cloud`, `deps`, `tts`, `backups`, `custom_components`,
  `node_modules` and `__pycache__` at any depth, plus any file over 5 MB.
  Under `.storage` it reads only `lovelace*` and `core.config_entries*`.
- A reference built at runtime (`states('light.' ~ room)`) cannot be
  found by either source.
- `refs` refuses an entity_id Home Assistant no longer has (no state, not
  in the registry). Leftover references to an already-removed entity have
  to be found with `rg -F '<entity_id>' /homeassistant`.
- `--device` refuses an entity without a device (YAML sensors, template
  entities, most helpers); run `refs` without it for those.
