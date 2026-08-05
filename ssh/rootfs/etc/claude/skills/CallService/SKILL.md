---
name: CallService
description:
  Discover and call Home Assistant services with real field metadata. USE
  WHEN calling any service, turning things on/off beyond simple toggles,
  looking up what parameters a service takes, or writing service calls into
  automations/scripts. ALWAYS check ha-service show before writing service
  data anywhere — never guess field names or values.
---

# CallService

Use `ha-service` to discover services (with their real parameter specs) and
to call them over the WebSocket API.

## Commands

```bash
ha-service list                          # compact domain → services map
ha-service list --domain light           # one-liners with descriptions
ha-service list --search vacuum          # search id/name/description
ha-service show light.turn_on            # full field spec — the source of truth
ha-service call light.turn_on --entity light.office_ceiling --data brightness=200
```

All commands output YAML by default (`--format json` for JSON).

## Workflow

1. **Find the service**: `ha-service list --search ...` when unsure of the name.
2. **Check the spec**: `ha-service show domain.service` — real fields with
   selectors, required flags, and examples. This is what stops made-up
   parameters like `brightness_percent`.
3. **Call it**: targets via `--entity` / `--area` / `--device` / `--label`
   (all repeatable), data via `--data KEY=VALUE` (JSON-parsed values) or
   `--data-file file.yaml` for complex payloads (flags override the file).

The same verified `--data` keys translate 1:1 into automation/script YAML
(`data:` block) — verify with a live call first, then write the YAML.

## Responses

Services that return data (`weather.get_forecasts`, `calendar.get_events`,
todo lists...) are handled automatically: `show` marks them
`returns_response`, and `call` requests and prints the `response` without
any extra flag.

## Dangerous services

`homeassistant.restart/stop`, `hassio.*`, `recorder.purge*`, and
`shell_command.*` are refused unless `--unsafe` is passed, and the shipped
permission settings prompt before such calls run. Prefer the `ha` CLI
equivalents (`ha core restart`) where they exist — same prompt, clearer log.

## Examples

```bash
# What parameters does the vacuum's send_command take?
ha-service show vacuum.send_command

# Set a thermostat
ha-service call climate.set_temperature --entity climate.living_room --data temperature=21.5

# Everything in an area
ha-service call light.turn_off --area living_room

# Get a weather forecast (response printed automatically)
ha-service call weather.get_forecasts --entity weather.home --data type=daily

# Complex payload from a file
ha-service call mqtt.publish --data-file payload.yaml
```

## Gotchas

- Unknown `--data` keys warn on stderr but are still sent — HA itself
  rejects truly invalid data with its own error.
- List values need JSON: `--data 'rgb_color=[255,0,0]'`.
- `--data` string values that look like JSON are parsed as JSON; quote-wrap
  in the payload file if a literal string like `"true"` is really meant.
- Calls wait for completion; long-running scripts may need `--timeout`.
- Service data fields are NOT the same as entity attributes — always `show`
  the service rather than copying attribute names from `ha-entities`.

## Setup

Requires the same long-lived token as `ha-entities` (HA_TOKEN env var or
`/homeassistant/.claude/ha_token`); if missing, the tool prints setup steps.
