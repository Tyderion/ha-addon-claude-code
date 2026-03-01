---
name: HAEntities
description:
  Query Home Assistant entity states, areas, and domains. ALWAYS use this
  skill instead of calling the HA REST or WebSocket API directly, reading .storage
  files, or asking the user for entity IDs. Use before writing any automation,
  script, or dashboard that references entities.
---

# HAEntities

Use `ha-entities` to query Home Assistant entity states, areas, and domains over the WebSocket API.

## Commands

```bash
ha-entities list [--domain DOMAIN] [--area AREA] [--state STATE] [--limit N]
ha-entities get <entity_id> [<entity_id> ...]
ha-entities domains
ha-entities areas
```

## Examples

```bash
# List all domains and their entity counts
ha-entities domains

# List all areas and their entity counts
ha-entities areas

# List all light entities
ha-entities list --domain light

# List entities in a specific area
ha-entities list --area "Office"

# List entities that are currently "on"
ha-entities list --domain light --state on

# Get first 10 entities (any domain)
ha-entities list --limit 10

# Get full details for specific entities
ha-entities get light.office_ceiling sensor.netatmo_temperature

# Combine filters
ha-entities list --domain sensor --area "Living Room" --limit 5
```

## Output Format

### `list` — Token-efficient summary

Returns count, filtered_count, applied filters, and an array of entities with:

- `entity_id`, `name`, `area`, `state`, `key_attr` (domain-specific important attributes)

### `get` — Full entity details

Returns all attributes, last_changed, last_updated, domain, area, name.

### `domains` — Domain summary

Returns array of `{domain, count}` sorted by count descending.

### `areas` — Area summary

Returns array of `{area_id, name, entity_count}` sorted by count descending.

## When to Use

- **Before writing automations**: find entity IDs, check current states, discover available entities
- **Before writing dashboards**: find entities to display, check what areas exist
- **Debugging**: check entity states, verify entity existence
- **Discovery**: explore what domains/areas/entities are available

## Tips

- Use `domains` first to see what's available
- Use `areas` to find area names (case-insensitive matching for `--area` filter)
- Use `list --domain X` to find entities in a specific domain
- Use `get` for full attribute details when you need to know exact attribute names
- The `key_attr` in `list` output shows the most important attribute per domain (e.g. brightness for lights, current_temperature for climate)
