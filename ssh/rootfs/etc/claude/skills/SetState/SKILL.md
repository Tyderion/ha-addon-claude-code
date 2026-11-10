---
name: SetState
description: Set helper and virtual state (input_*, counter, timer, var, device
  select/number/text) with validation and read-back. USE WHEN turning a
  helper on or off ("turn on vacation mode"), picking an option, setting a
  number, text or datetime, or starting, pausing or cancelling a timer. NOT
  FOR physical devices (CallService) or creating a helper (YAML, or
  ManageIntegration).
---

# SetState

Use `ha-state` to change value-settable state. It resolves the right
service for the domain, validates the value against the entity's own
constraints, and verifies the result by reading the state back.

`ha-state` is on `PATH`: call it by bare name (a path form such as
`./ha-state` is rewritten to it anyway). If a call errors, fix the call
rather than writing ad-hoc `ha_lib` scripts or `curl`.

## Commands

```bash
ha-state show input_select.house_mode      # current state + accepted values
ha-state set input_select.house_mode Away  # validated, called, verified
ha-state set input_boolean.vacation_mode on     # on / off / toggle
ha-state set input_number.target_temp 21.5      # checked against min/max
ha-state set timer.laundry start --duration 0:45:00
ha-state set counter.coffee_count increment     # or an integer, or reset
```

All commands output YAML by default (`--format json` for JSON).

## Workflow

1. **Check what's settable**: `ha-state show <entity>` prints the current
   state and exactly which values `set` accepts (select options, number
   range, timer keywords...).
2. **Set it**: `ha-state set <entity> <value>`. The output shows
   `before`, `after`, and `verified`; a mismatch prints a note and exits 1
   so silent failures can't slip through.

## Supported Domains

`input_boolean`, `input_select`, `input_number`, `input_text`,
`input_datetime`, `counter`, `timer`, `var`, plus the device-backed
`select`, `number`, and `text` domains.

Device command domains (`light`, `switch`, `climate`, ...) are refused —
those go through `ha-service call`. Reading arbitrary entities is
`ha-entities`' job.

## Gotchas

- `verified: false` (exit 1) means HA stored something other than the
  requested value — often number step rounding; inspect `after` before
  retrying.
- `toggle` verifies against the flipped previous state.
- `timer` takes keywords (`start`, `pause`, `cancel`, `finish`,
  `change`), not durations, as the value; duration goes in `--duration`
  and only applies to `start`/`change`. `change` needs a running timer.
- `input_datetime` values pass through to HA (`YYYY-MM-DD HH:MM:SS`,
  `HH:MM:SS`, or a date, matching the helper's has_date/has_time); HA
  normalizes the stored form, so read-back verification is skipped.
- `var` values are JSON-parsed when possible; quote-wrap in the shell if
  a literal string like `"true"` is really meant.
- Never write state via HA's raw set-state API — it creates phantom
  states no device backs. Every `ha-state` mutation is a real service
  call.
