---
name: QueryHistory
description: Query recorded state history, the logbook and long-term statistics. USE WHEN the question is about the past, such as "when was the door last opened", "how long was the heater on", "average temperature yesterday", "energy use this week", "what was X at 3am", "since when is X unavailable", "who or what turned X on", "was it an automation, a person or the device itself". NOT FOR the current value (FindEntities) or the steps inside one automation run (DebugAutomation).
---

# QueryHistory

Use `ha-history` to query the recorder's state history, the logbook and long-term statistics over the WebSocket API.

`ha-history` is on `PATH`: call it by bare name (a path form such as
`./ha-history` is rewritten to it anyway). If a call errors, fix the call
rather than writing ad-hoc `ha_lib` scripts or `curl`.

## Commands

```bash
ha-history changes <entity_id> ... [--last N[mhdw] | --from ISO] [--to ISO] [--limit N]
ha-history stats <id> ...          [--last N[mhdw] | --from ISO] [--to ISO]
                                   [--period 5minute|hour|day|week|month]
ha-history stats-list [--search TEXT] [--limit N]
ha-history logbook [<entity_id> ...] [--device ID ...] [--context ID]
                   [--kind KIND ...] [--exclude GLOB ...]
                   [--last N[mhdw] | --from ISO] [--to ISO] [--limit N]
```

All commands output YAML by default; add `--format json` for JSON. Every
command takes several ids in one call; prefer that to one call per entity.

- **Windows:** with none given, `changes` covers the last 24h and `stats`
  the last 7d in `day` buckets. `--last N[mhdw]` (`30m`, `8h`, `3d`, `2w`)
  counts back from `--to`, which defaults to now, so `--last 8h --to
2026-08-04T12:00` is the 8 h before that moment. `--from`/`--to` take ISO
  dates or datetimes, read as local time unless they carry an offset; a
  bare date is local midnight. `--last` and `--from` together is an error.
- **Limits:** `--limit` is 50 for `changes` and `logbook` and 100 for `stats-list`; `0` means unlimited.

## Picking the right command

- **`changes`**: discrete questions about doors, lights, presence, modes.
  "When did X happen", "how long was X on". Raw history is purged after
  ~10 days (recorder `purge_keep_days`), so keep windows short. Also the
  tool when you need the exact change moments of a numeric sensor within
  hours.
- **`stats`**: numeric trends and totals such as temperature, humidity,
  power, energy. `hour`/`day`/`week`/`month` buckets are kept forever, so
  anything older than the raw retention goes here; `5minute` buckets are
  short-term statistics, purged with raw history. Only numeric entities
  with a `state_class` have statistics. `stats` also takes any id
  `stats-list` returns, including external statistics (`source:id`).
- **`logbook`**: _who or what_ changed something: each state change with its cause. Same retention as `changes`. Scope it to the entities in question; unscoped, it drowns in automations that run every few minutes.

## Output

Each command starts with `window: {from, to}`, the resolved window in
local time.

### `changes`

Per entity: `changes_total` (entries including the window-start state, so
an unchanged entity reports 1), `current_state`, a `time_in_state` summary
(total duration and percent per state over the window; answers "how long
was X on" directly), and the newest changes first as `{state, from,
duration}`. `returned` is the count listed, and `truncated: true` means
more changes exist; the summary always covers the full window. For
entities with more than 10 distinct states, `time_in_state` is omitted and
a `hint` points to `stats`.

### `stats`

Per entity: `unit`, `period`, and `buckets` of `{start, mean, min, max}`
for measurements or `{start, sum, state, change}` for metered entities
(energy, gas, water); `change` is the consumption within that bucket,
usually what "how much energy did I use" asks for.

### `stats-list`

`{total, returned, truncated, statistics}`, sorted by id, each with
`statistic_id`, `kind` (`mean` = measurements, `sum` = metered
consumption, `unknown` = neither) and, when HA has them, `name` and
`unit`. `--search` is a case-insensitive substring match on id or name.

### `logbook`

`{returned, truncated, entries}`, newest first. An unscoped query also gets `by_entity`: the 15 busiest entity ids (counted after `--kind`/`--exclude`, before `--limit`), which shows what to `--exclude`. Each entry has `when`, `kind` and `cause`:

- `kind` is what the row is: `state` (an entity changed; `entity_id`, `state`, and `attributes.event_type` for `event.*` entities), `run` (an automation or script started; `entity_id`, `name`, `message` such as `triggered by time pattern`, and `context_id`), or `message` (any other logbook line, e.g. Home Assistant starting).
- `cause.kind` is why it happened:
  - `user`: someone acted through HA, with `service` when it was a service call. `user.name` names them; `system_generated: true` means Supervisor or an add-on, not a person. `token_user: true` is the user this tool's token belongs to, usually the person you're talking to. Your own `ha-service` calls carry the same user, so `token_user` cannot tell their clicks from your calls; only a context id can (below).
  - `automation` / `script`: `name`, `entity_id`, and for automations the `trigger` (`time pattern`, `state of binary_sensor.x`, `event 'shelly.click'`). A `user` may ride along when a person's action triggered it.
  - `service`: a service call with no user, e.g. from an integration or another add-on.
  - `entity`: another entity's change caused it (`entity_id`, `state`), e.g. a group following its member.
  - `event`: an integration event (`event_type`, `domain`, `message`), e.g. `shelly.click` for a physical button wired through HA.
  - `none`: no cause recorded. Usually the device itself, a physical control, or the integration reporting an outside change. Not proof, though: HA drops the cause when a device reports its new state more than 5 s after the call, and an unscoped query misses causes from before its window. Before saying "nobody did it", re-query scoped to that entity, and check `ha-trace list` for an automation whose `last_triggered` matches.

`--kind` (repeatable) keeps entries whose row kind or cause kind matches; `--exclude` drops entity ids matching a glob (`--exclude 'automation.beer_*'`).

**Following a cause.** Only `run` entries carry a `context_id`. `ha-history logbook --context <id>` (on its own; default window 10 days) lists everything that context did. Three ways to get an id:

- `ha-history logbook automation.<x>` over the time in question returns that automation's runs.
- `ha-trace show <automation>` prints its run's `context_id` (DebugAutomation).
- `ha-service call` prints the `context_id` of the call it made (CallService).

An automation started by another automation runs in a child context, so each hop needs its own `--context`.

## Examples

```bash
# When was the front door last opened?
ha-history changes binary_sensor.front_door

# How long was the office light on yesterday? (see time_in_state)
ha-history changes light.office --from 2026-08-04 --to 2026-08-05

# Average living-room temperature per day over the last week
ha-history stats sensor.living_room_temperature

# Hourly energy consumption today (a bare date means local midnight)
ha-history stats sensor.energy_total --from 2026-08-05 --period hour

# What can I get statistics for?
ha-history stats-list --search energy

# What turned on the kitchen light around 3am?
ha-history logbook light.kitchen --from 2026-08-05T02:30 --to 2026-08-05T03:30

# Did anyone do anything overnight?
ha-history logbook --kind user --from 2026-08-04T23:00 --to 2026-08-05T07:00

# Everything one automation run changed
ha-history logbook --context 01K1Z9...
```

## Gotchas

- A `changes` window entirely older than the raw retention prints
  `Warning: no recorded history` on stderr and exits 1; ignore its "widen
  the window" advice and use `stats`. A window reaching past the purge
  boundary starts at the oldest surviving row, so `time_in_state` then
  covers only that span.
- `stats` for an entity without a `state_class` (including all
  non-numeric entities) warns and exits 1; check `stats-list`.
- `changes` merges consecutive identical states, so it reports state
  _changes_, not every recorder row. The newest change's `duration` runs
  to the window end; the oldest entry is the state the entity already had
  when the window started, not a change.
- `logbook` skips numeric sensors, `counter`/`image`/`proximity` entities and entities excluded from the logbook, and lists only real state changes (no attribute-only updates, no window-start state). An entity with no entries gets a warning naming the likely reason; `changes` still covers the skipped entities.
- "Since when is X unavailable": `changes --last 10d`. If the oldest entry
  is already `unavailable`, the outage predates the raw retention; for an
  entity with statistics, the last `stats` bucket with data dates the loss
  instead.
