---
name: CallService
description:
  Turn things on or off, run scripts and scenes, set a thermostat or cover,
  send a notification, or call any other service, and look up the fields a
  service takes. USE WHEN "turn off the lights", "set the heating to 21",
  "notify my phone", "pause the morning automation" (automation.turn_off),
  or before writing service data into config. NOT FOR helpers, counters,
  timers or var (SetState). Run ha-service show before writing service
  data; never guess field names.
---

# CallService

Use `ha-service` to discover services (with their real parameter specs) and
to call them over the WebSocket API.

`ha-service` is on `PATH`: call it by bare name (a path form such as
`./ha-service` is rewritten to it anyway). If a call errors, fix the call
rather than writing ad-hoc `ha_lib` scripts or `curl`.

## Commands

```bash
ha-service list                          # compact domain → services map
ha-service list --domain light --search color --limit 20   # filters combine; default limit 100
ha-service show light.turn_on            # full field spec
ha-service call light.turn_on --entity light.office_ceiling --data brightness=200
```

All commands output YAML by default (`--format json` for JSON).

## Workflow

1. **Find the service**: `ha-service list --search ...` when unsure of the name.
2. **Check the spec**: `ha-service show domain.service` lists the real
   fields with selectors, required flags and examples, plus
   `target_domains`, `returns_response`, and `dangerous` when the call
   needs `--unsafe`. Field names are not entity attribute names
   (`brightness`, not `brightness_percent`); never copy keys from
   `ha-entities get` output.
3. **Call it**: targets via `--entity` / `--area` / `--device` / `--label`
   (all repeatable), data via `--data KEY=VALUE` or `--data-file
file.yaml` for complex payloads (`--data` overrides the file).
4. **Responses** come back without extra flags: `call` prints `response`
   for services `show` marks `returns_response` (weather forecasts,
   calendar events, todo lists).
5. **Check what it did**: `call` prints a `context_id`; `ha-history logbook --context <id>` (QueryHistory) lists every change that call caused.

The same `--data` keys translate 1:1 into the `data:` block of
automation/script YAML, so `show` is enough to write it; a live call is
optional and only where the side effect is wanted.

## Not For

Helper and virtual state (`input_boolean`, `input_select`,
`input_number`, `input_text`, `input_datetime`, `counter`, `timer`, `var`):
`call` refuses these domains except their `reload`/`configure` services.
Use `ha-state set` (SetState), which validates the value and reads the
result back; prefer it for device-backed `select`/`number`/`text` too,
which `call` accepts unverified. `input_button.press` is not a value and
is called here.

## Dangerous services

`homeassistant.restart/stop`, `hassio.*`, `recorder.purge*` and
`shell_command.*` are refused unless `--unsafe` is passed, and the add-on's
permission hook asks the user before any call with `--unsafe`. Prefer the
`ha` CLI equivalents (`ha core restart`) where they exist; they ask too,
and the log is clearer.

## Examples

```bash
# What parameters does the vacuum's send_command take?
ha-service show vacuum.send_command

# Set a thermostat
ha-service call climate.set_temperature --entity climate.living_room --data temperature=21.5

# Pause an automation (turn_on resumes it, trigger runs it once)
ha-service call automation.turn_off --entity automation.morning_lights

# Everything in an area (area_id, not the display name)
ha-service call light.turn_off --area living_room

# Get a weather forecast (response printed automatically)
ha-service call weather.get_forecasts --entity weather.home --data type=daily

# Complex payload from a file
ha-service call mqtt.publish --data-file payload.yaml
```

## Gotchas

- Only `--entity` targets are checked before the call, with suggestions.
  `--area`, `--device` and `--label` take registry ids (`living_room`,
  not `Living Room`), and HA silently does nothing for an unknown one, so
  take the id from `ha-entities areas` or `ha-template`.
- Unknown `--data` keys warn on stderr (listing the known keys) but are
  still sent; HA rejects truly invalid data with its own error. A service
  that declares no fields gets no warning at all.
- `--data` values are JSON-parsed: lists need JSON (`--data
'rgb_color=[255,0,0]'`), and a value that should stay a string although
  it looks like JSON is JSON-quoted (`--data 'code="0042"'`). `--data-file`
  values keep their YAML types.
- Calls block until HA finishes (default `--timeout 60`, in seconds). A
  timeout exits 1 but does not cancel the service, so check the entity
  before retrying. Long-running scripts need a bigger `--timeout`, or
  `script.turn_on`, which returns at once.
