---
name: FindEntities
description:
  Look up entities and their current state with ha-entities, such as finding
  an entity_id by name, reading a state or attribute (battery, temperature,
  open/closed), or listing entities, areas, domains, scripts and
  automations. USE WHEN "is the garage door open", "what's the battery of
  X", "which lights are on", "find the kitchen lamp", and before writing
  anything that names an entity. NOT FOR the past (QueryHistory), what uses
  an entity (FindReferences), or which device an entity belongs to and
  which devices are in an area (TestTemplate). Never guess entity IDs, curl
  the API or read .storage for this.
---

# FindEntities

Use `ha-entities` to query Home Assistant entity states, areas, domains, scripts, and automations over the WebSocket API.

`ha-entities` is on `PATH`: call it by bare name (a path form such as
`./ha-entities` is rewritten to it anyway). If a call errors, fix the call
rather than writing ad-hoc `ha_lib` scripts or `curl`.

Start with `ha-entities list --search TEXT` (a substring of the entity_id
or name); never guess an entity_id. Use `domains` or `areas` when you need
the catalogue or a search came back empty, and `get` when you need exact
attribute names rather than the `key_attr` summary. Always narrow `list`
with `--domain`, `--area` or `--search`: a bare `list` on a large instance
returns hundreds of entities.

## Commands

```bash
ha-entities list [--domain DOMAIN ...] [--area AREA] [--state STATE]
                 [--search TEXT] [--exclude-unavailable] [--limit N]
ha-entities get <entity_id> [<entity_id> ...]
ha-entities domains
ha-entities areas
ha-entities scripts
ha-entities automations
```

All commands output YAML by default; put `--format json` after the
subcommand for JSON. All `list` filters are case-insensitive:

- `--area` matches the area's `name` exactly, never its `area_id`. An
  entity is in an area when it has one itself or inherits its device's.
- `--state` is an exact match on the state string (`on`, `unavailable`,
  `23.5`), not a substring or numeric comparison.
- `--exclude-unavailable` drops `unavailable` and `unknown`.
- Results are sorted by `entity_id`, and `--limit` (default 100, `0` =
  unlimited) keeps the first N of that order, so a truncated list can hide
  the entity you want: narrow the filters rather than raising the limit.

## Examples

```bash
# Find an entity by name or id fragment
ha-entities list --search "office ceiling"

# Several domains at once; area names with spaces are quoted
ha-entities list --domain light switch --area "Living Room" --state on

# Full attributes for specific entities (several per call)
ha-entities get light.office_ceiling sensor.netatmo_temperature
```

## Output

### `list`

Returns `{total, filtered_count, returned, truncated, entities}`; `total`
is the whole-instance entity count and `truncated: true` means `--limit`
cut the results. Each entity has `entity_id`, `name`, `state`, plus `area`
and `key_attr` (the domain's most useful attribute, e.g. brightness for
lights, current_temperature for climate) when non-empty.

A `--domain` or `--area` value that matches nothing adds a `hint` listing
the valid domains or area names. A `--search` or `--state` miss gets no
hint; broaden the search text instead.

### `get`

A list of entities with all attributes, last_changed, last_updated,
domain, area, name. Unknown entity_ids print a warning on stderr and are
skipped; if none resolve, it exits 1.

### `domains`

`{domains: [{domain, count}, …]}` sorted by count descending.

### `areas`

`{areas: [{area_id, name, entity_count}, …]}` sorted by count descending.
Only areas holding at least one entity are listed; the `hint` on a
zero-match `--area` lists every area, including empty ones.

### `scripts` and `automations`

`{count, scripts: [...]}` / `{count, automations: [...]}`, each item
`{entity_id, alias, state, mode, last_triggered}`, sorted by alias. A
script's state is `on` while running; an automation's is `on` when
enabled. Older UI-made scripts have numeric entity_ids, so `scripts` is how
to map an alias to one.

## Not this skill

- Changing names, areas, icons, visibility or entity_ids: `ha-entities update` / `rename` (UpdateEntity).
- What uses an entity or device: `ha-entities refs` (FindReferences).
- Which device owns an entity, which devices are in an area, labels: template functions via `ha-template` (TestTemplate).
- Past states and statistics: `ha-history` (QueryHistory).
- The integration an entity comes from, its setup and options: `ha-integrations` (ManageIntegration).
