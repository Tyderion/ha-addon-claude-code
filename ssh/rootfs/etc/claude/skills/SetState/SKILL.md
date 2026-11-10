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
rather than writing ad-hoc `ha_lib` scripts or `curl`, and never write
state through HA's raw `/api/states` endpoint: that creates phantom states
no device backs, which is why every `ha-state` mutation is a real service
call.

## Commands

```bash
ha-state show input_select.house_mode      # current state + accepted values
ha-state set input_select.house_mode Away  # validated, called, verified
ha-state set input_boolean.vacation_mode on     # on / off / toggle
ha-state set input_number.target_temp 21.5      # checked against min/max
ha-state set input_text.note "Back at 6"        # checked against length and pattern
ha-state set timer.laundry start --duration 0:45:00
ha-state set counter.coffee_count increment     # increment / decrement / reset, or an integer
ha-state set input_select.house_mode Away --timeout 10   # seconds to wait for HA (default 60)
```

All commands output YAML by default (`--format json` for JSON).

`set` validates against the live entity and names the accepted values
when it rejects one, so `show` is only needed to learn what to set.
`input_select`/`select` options are exact, case-sensitive matches.

## Reading the result

A successful `set` prints `called` (the resolved service), `before`,
`after`, and `verified` where the result is checkable.

- Exit 1 with a YAML block (`verified: false` and a `note`) means the
  service was called and HA stored something other than the requested
  value; read `after` before retrying.
- Exit 1 with only an `Error:` line on stderr means nothing was called:
  the value failed validation, HA rejected the service, or the entity does
  not exist.
- No `verified` key, and exit 0 whatever happened, for `input_datetime`
  (HA normalizes the stored form), `var`, counter `increment`/`decrement`/
  `reset`, and `toggle` from `unknown`/`unavailable`: compare `before` and
  `after` yourself.

## Supported Domains

`input_boolean`, `input_select`, `input_number`, `input_text`,
`input_datetime`, `counter`, `timer`, `var`, plus the device-backed
`select`, `number`, and `text` domains. Anything else (`light`, `switch`,
`climate`, ...) is refused: `ha-service call` for commands, `ha-entities`
for reads.

## Gotchas

- `timer` takes keywords (`start`, `pause`, `cancel`, `finish`,
  `change`), not durations, as the value; the duration goes in
  `--duration` (`H:MM:SS`) and is refused for anything but
  `start`/`change`. `start` without `--duration` uses the timer's own
  duration. Verification checks the resulting state (`active`, `paused`,
  `idle`), not the remaining time; `change` needs a running timer.
- `input_datetime` takes `YYYY-MM-DD HH:MM:SS`, `HH:MM:SS`, or a date,
  matching the helper's `has_date`/`has_time`.
- Counter integers are not range-checked locally; a value outside
  `minimum`..`maximum` comes back clamped and `verified: false`.
- `var` values are JSON-parsed when possible (`true`, `3`, `[1,2]`); for a
  literal string that looks like JSON, pass the quotes through the shell:
  `ha-state set var.flag '"true"'`.
