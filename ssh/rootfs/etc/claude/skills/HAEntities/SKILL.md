---
name: HAEntities
description:
  Query Home Assistant entity states, areas, domains, scripts, and automations.
  ALWAYS use this skill instead of calling the HA REST or WebSocket API directly,
  reading .storage files, or asking the user for entity IDs. Use before writing any
  automation, script, or dashboard that references entities.
---

# HAEntities

Use `ha-entities` to query Home Assistant entity states, areas, domains, scripts, and automations over the WebSocket API.

`ha-entities` is on `PATH`: invoke it by bare name exactly as shown, never `./ha-entities` or another path form — path forms fail and are permission-blocked. If a call errors, fix the invocation rather than dropping to ad-hoc `ha_lib` scripts.

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

All commands output YAML by default; add `--format json` for JSON. All `list` filters are case-insensitive. `--limit` defaults to 100 (`--limit 0` = unlimited).

## Examples

```bash
# List all domains and their entity counts
ha-entities domains

# List all areas and their entity counts
ha-entities areas

# Find an entity by name or id fragment (best first step)
ha-entities list --search "office ceiling"

# List all light entities
ha-entities list --domain light

# List entities from several domains at once
ha-entities list --domain light switch

# List entities in a specific area
ha-entities list --area "Office"

# List entities that are currently "on"
ha-entities list --domain light --state on

# Hide unavailable/unknown entities
ha-entities list --domain sensor --exclude-unavailable

# Get full details for specific entities
ha-entities get light.office_ceiling sensor.netatmo_temperature

# Combine filters
ha-entities list --domain sensor --area "Living Room" --limit 5

# List all scripts with their aliases
ha-entities scripts

# List all automations with their aliases
ha-entities automations
```

## Output Format

All output is YAML (or JSON with `--format json`).

### `list` — Token-efficient summary

Returns `{total, filtered_count, returned, truncated, entities}`. `total` is the whole-instance entity count; `truncated: true` means `--limit` cut the results. Each entity has:

- `entity_id`, `name`, `state`, plus `area` and `key_attr` (domain-specific important attributes) when non-empty

On zero matches a `hint` field lists the available domains/areas.

### `get` — Full entity details

Returns a list of entities with all attributes, last_changed, last_updated, domain, area, name. Unknown entity_ids print a warning on stderr and are skipped; if none resolve, exits 1.

### `domains` — Domain summary

Returns `{domains: [{domain, count}, …]}` sorted by count descending.

### `areas` — Area summary

Returns `{areas: [{area_id, name, entity_count}, …]}` sorted by count descending.

### `scripts` — Script listing

Returns `{count, scripts: [{entity_id, alias, state, mode, last_triggered}, …]}` sorted by alias alphabetically. State is `on` (running) or `off` (idle).

### `automations` — Automation listing

Returns `{count, automations: [{entity_id, alias, state, mode, last_triggered}, …]}` sorted by alias alphabetically. State is `on` (enabled) or `off` (disabled).

## When to Use

- **Before writing automations**: find entity IDs, check current states, discover available entities
- **Before writing dashboards**: find entities to display, check what areas exist
- **Debugging**: check entity states, verify entity existence
- **Discovery**: explore what domains/areas/entities are available
- **Finding scripts**: use `scripts` to list all scripts with their entity_id and alias (useful for scripts with numeric IDs)
- **Finding automations**: use `automations` to list all automations with their entity_id, alias, and state (enabled/disabled)

## Tips

- To find a specific entity, start with `list --search TEXT` — never guess entity IDs
- Always narrow `list` with `--domain`, `--area`, or `--search`: a bare `list` on a large instance returns hundreds of entities (capped at 100 by default, `truncated: true` tells you results were cut)
- Use `domains` first to see what's available
- Use `areas` to find area names
- Use `get` for full attribute details when you need to know exact attribute names
- The `key_attr` in `list` output shows the most important attribute per domain (e.g. brightness for lights, current_temperature for climate)
- A long-lived HA token is required (one-time setup); if it's missing, the tool exits with the exact setup instructions
