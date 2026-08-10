---
name: HomeAssistantReload
description: Reload Home Assistant YAML configuration. USE WHEN user edits YAML files OR wants to apply config changes OR asks to reload automations/scripts/scenes OR asks to restart Home Assistant (check whether a reload suffices first). Uses ha-reload for hot reload, ha core restart only when necessary.
---

# HomeAssistantReload

Intelligently reload Home Assistant configuration after YAML changes.

`ha-reload` is on `PATH`: invoke it by bare name, never `./ha-reload` or
another path form — path forms fail and are permission-blocked.

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

## Example

**After adding a new integration**

```
User: "I added mqtt: to configuration.yaml"
→ Run: ha core check     (configuration.yaml changed)
→ Run: ha core restart
→ Result: Full restart required for new integrations
```
