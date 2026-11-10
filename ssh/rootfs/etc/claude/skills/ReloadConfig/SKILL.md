---
name: ReloadConfig
description:
  Apply YAML changes with ha-reload, and decide when a full restart is
  needed instead. USE WHEN a YAML file was edited, or the user asks to
  reload config or restart Home Assistant; ha-reload hot-reloads, ha core
  restart only when a reload cannot pick the change up.
---

# ReloadConfig

Intelligently reload Home Assistant configuration after YAML changes.

`ha-reload` is on `PATH`: call it by bare name (a path form such as
`./ha-reload` is rewritten to it anyway). If a call errors, fix the call
rather than writing ad-hoc `ha_lib` scripts or `curl`.

## When to Use Each Command

| Command           | Use When                                                                               | Downtime       |
| ----------------- | -------------------------------------------------------------------------------------- | -------------- |
| `ha-reload`       | YAML changes to automations, scripts, scenes, groups, inputs, templates, zones, themes | None (instant) |
| `ha core restart` | New integrations, logger/recorder/http changes, database settings                      | 30+ seconds    |

`ha-reload` takes no arguments and reloads every hot-reloadable domain at once — there is no per-domain option.

## Workflow

After editing YAML files:

1. **Validate first:**

   ```bash
   yamllint <file>   # every change
   ha core check     # only for configuration.yaml changes or before a restart (~30s)
   ```

2. **Apply changes:**

   ```bash
   ha-reload
   ```

3. **Only use restart if ha-reload doesn't pick up changes** (new integrations, etc.):
   ```bash
   ha core restart
   ```

## What ha-reload Reloads

- `automation:` - automations
- `script:` - scripts
- `scene:` - scenes
- `group:` - groups
- `input_boolean:`, `input_number:`, `input_select:`, `input_text:`, `input_datetime:` - input helpers
- `template:` - template sensors/binary sensors
- `timer:`, `counter:` - timers and counters
- `schedule:` - schedules
- `zone:` - zones
- `person:` - persons
- `homeassistant:` - core config (name, location, customize)
- Themes and custom Jinja templates

## Troubleshooting

- `ha-reload` reports success even when an individual domain fails to load — HA returns HTTP 200 regardless. If a change doesn't appear after a reload, check `ha core logs`.
- If the change still isn't live and it involves a new integration or logger/recorder/http settings, use `ha core restart`.
