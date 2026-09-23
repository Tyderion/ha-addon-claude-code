---
name: SetState
description:
  Safely read and mutate Home Assistant virtual state — helpers (input_*),
  counters, timers, var, and device-backed select/number/text — with value
  validation and read-back verification. USE WHEN setting or toggling a
  helper, changing an input_select option, setting an input_number, text,
  or datetime value, starting/pausing/cancelling a timer, changing a
  counter, or setting a var. ALWAYS use ha-state for these — ha-service
  refuses helper domains and redirects here.
---

# SetState

Use `ha-state` to change value-settable state. It resolves the right
service for the domain, validates the value against the entity's own
constraints, and verifies the result by reading the state back.

`ha-state` is on `PATH`: invoke it by bare name exactly as shown, never
`./ha-state` or another path form — path forms fail and are
permission-blocked. If a call errors, fix the invocation rather than
dropping to ad-hoc `ha_lib` scripts.

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

## Setup

Requires the same long-lived token as `ha-entities` (HA_TOKEN env var or
`/homeassistant/.claude/ha_token`); if missing, the tool prints setup steps.
