---
name: QueryHistory
description:
  Query Home Assistant state history and long-term statistics. USE WHEN
  questions are about the past — "when was the door last opened", "how long
  was the light on", "average temperature yesterday", "energy usage this
  week", "what was X at 3am", or any trend/duration/usage question. ALWAYS
  use ha-history instead of the REST API or guessing from current state.
---

# QueryHistory

Use `ha-history` to query the recorder's state history and long-term
statistics over the WebSocket API.

## Commands

```bash
ha-history changes <entity_id> ... [--last 24h | --from ISO [--to ISO]] [--limit N]
ha-history stats <entity_id> ...   [--last 7d | --from ISO [--to ISO]]
                                   [--period 5minute|hour|day|week|month]
ha-history stats-list [--search TEXT] [--limit N]
```

All commands output YAML by default; add `--format json` for JSON. Relative
windows use `--last N[mhdw]` (e.g. `30m`, `8h`, `3d`, `2w`); absolute windows
use ISO dates/datetimes, interpreted as local time unless they carry an
offset.

## Picking the right command

- **`changes`** — discrete questions: doors, lights, presence, modes. "When
  did X happen", "how long was X on". Raw history is purged after ~10 days by
  default, so keep windows short.
- **`stats`** — numeric trends and totals: temperature, humidity, power,
  energy. Hourly/daily/monthly buckets, kept forever. Only entities with a
  `state_class` have statistics — `stats-list` shows which.
- Rule of thumb: on/off-style entity → `changes`; numeric sensor → `stats`;
  numeric sensor but you need exact change moments within hours → `changes`
  with a short window.

## Output

### `changes`

Per entity: `changes_total`, `current_state`, a `time_in_state` summary
(total duration and percent per state over the whole window — answers "how
long was X on" directly), and the newest changes first as
`{state, from, duration}`. `--limit` (default 50) caps listed changes;
`truncated: true` means more changes exist — the summary always covers the
full window regardless. Entities that look numeric (>10 distinct states) get
a hint to use `stats` instead of a meaningless summary.

### `stats`

Per entity: `unit`, `period`, and `buckets` of `{start, mean, min, max}` for
measurements or `{start, sum, state, change}` for metered entities (energy,
gas, water) — `change` is the consumption within that bucket, usually what
"how much energy did I use" asks for.

### `stats-list`

`{total, returned, truncated, statistics}` with `statistic_id`, `name`,
`unit`, and `kind` (`mean` = measurements, `sum` = metered consumption).

## Examples

```bash
# When was the front door last opened?
ha-history changes binary_sensor.front_door --last 24h

# How long was the office light on yesterday? (see time_in_state)
ha-history changes light.office --from 2026-08-04 --to 2026-08-05

# Average living-room temperature per day over the last week
ha-history stats sensor.living_room_temperature --last 7d --period day

# Hourly energy consumption today
ha-history stats sensor.energy_total --last 24h --period hour

# What can I get statistics for?
ha-history stats-list --search energy
```

## Gotchas

- Raw history (`changes`) is purged after ~10 days (recorder `purge_keep_days`);
  asking for older windows silently returns nothing — use `stats` for
  anything older.
- `stats` returns nothing for entities without a `state_class` (including all
  non-numeric entities) — that's expected, not an error; check `stats-list`.
- `changes` merges consecutive identical states, so it reports state
  _changes_, not every recorder row.
- The last change's `duration` runs to the window end, and the first entry is
  the state the entity already had when the window started.
- Ask for multiple entities in one call instead of one call each — it's one
  WebSocket round-trip either way.

## Setup

Requires the same long-lived token as `ha-entities` (HA_TOKEN env var or
`/homeassistant/.claude/ha_token`); if missing, the tool prints setup steps.
