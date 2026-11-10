---
name: TestTemplate
description: Render Jinja templates against live state, and answer device, area,
  integration and label membership questions with template functions
  (area_devices, device_entities, integration_entities, label_entities)
  that ha-entities lacks. USE WHEN writing or debugging a template, a
  template sensor doesn't update, or "which devices are in the kitchen",
  "what device is sensor.x part of". Verify with ha-template rather than
  reasoning about Jinja from memory.
---

# TestTemplate

Use `ha-template` to render a Jinja template through the WebSocket
`render_template` API, the exact engine automations and dashboards use.

`ha-template` is on `PATH`: call it by bare name (a path form such as
`./ha-template` is rewritten to it anyway). If a call errors, fix the call
rather than writing ad-hoc `ha_lib` scripts or `curl`.

## Commands

```bash
ha-template '{{ states("sun.sun") }}'
ha-template --file template.jinja          # or -f; give exactly one of TEMPLATE / --file
ha-template TEMPLATE --var KEY=VALUE ...   # inject variables
ha-template TEMPLATE --timeout 3           # fail if rendering takes longer (no limit by default)
ha-template TEMPLATE --watch               # a new document whenever the result changes, Ctrl+C to stop
```

Output is YAML by default (`--format json` for JSON): the rendered
`result` (native type: numbers stay numbers, lists stay lists) plus
`listeners`, the `entities`, `domains`, `time` and `all` subscriptions the
template holds. Empty keys are dropped, and a template that listens to
nothing has no `listeners` key at all.

## Membership questions

`ha-entities` lists entities, areas and domains, but cannot say which
devices an area holds, which device owns an entity, or what an
integration or label covers. Template functions answer that from Home
Assistant's own registries, so use them instead of reading `.storage`:

```bash
ha-template '{{ area_devices("Kitchen") | map("device_attr", "name") | list }}'
ha-template '{{ device_attr("sensor.hall_motion", "name") }}'
ha-template '{{ device_entities(device_id("sensor.hall_motion")) }}'
ha-template '{{ integration_entities("zha") }}'
ha-template '{{ label_entities("battery") }}'
```

Also `area_entities`, `area_name`, `areas()`, `labels()`. `area_devices`
and `area_entities` take an area name or area_id. `device_attr` takes an
entity_id or a device_id; `device_entities` needs the device_id, hence
`device_id(...)`. For an entity without a device (`sun.sun`, most template
sensors) `device_id()` renders `None` and `device_attr` errors with "Must
provide a device or entity ID": that is the answer, not a tool failure.
`integration_entities` takes the integration domain (`zha`) and spans all
its entries.

## Workflow

Use `--file` for anything beyond a one-liner; shell quoting of `{{ }}` is
the usual failure. Check `listeners` as well as `result`: an entity the
template should react to but that is missing from `listeners` will not
trigger updates in HA either, which is the cause of most "my template
sensor is stale" bugs. `listeners.all: true` means it re-renders on every
state change (e.g. `states` called without arguments); scope it down.

## Variables

Templates copied from automations often reference variables like `trigger`
or script `variables`. Inject them with `--var`; values parse as JSON when
possible (`200` → int, `true`/`false`/`null` → bool/None, `{...}` →
dict), else plain strings (`on` stays `"on"`). To keep a JSON-looking value
a string, quote it as JSON: `--var code='"0042"'`.

```bash
ha-template '{{ trigger.to_state.state }}' \
    --var trigger='{"to_state": {"state": "on"}}'
ha-template '{{ brightness > 128 }}' --var brightness=200
```

## Examples

```bash
# Count open doors in a group
ha-template '{{ expand("group.doors") | selectattr("state","eq","on") | list | count }}'

# Watch a condition flip live while you toggle the entity
ha-template '{{ is_state("binary_sensor.front_door", "on") }}' --watch
```

## Gotchas

- Syntax errors and undefined variables or attributes (`trigger` without
  `--var trigger=...`) print `Template error: ...` to stderr and exit 1,
  with no result shown. A missing entity is not an error:
  `states("sensor.nope")` renders `unknown`, so check for it explicitly.
  Fix the template or supply the variable rather than wrapping it in
  `default` filters blindly.
- `states("x.y")` returns a string; compare numbers with `| float` /
  `| int`. The displayed `result` of `{{ states("sensor.temp") }}` shows
  as a number only because HA parses the rendered text afterwards; inside
  the template it is still a string.
- `--watch` prints a `---` separated document (with an `at:` timestamp)
  each time a listened-to change alters the result, so a template whose
  value stays the same prints nothing new. Errors while watching print as
  `error:` documents and watching continues.
