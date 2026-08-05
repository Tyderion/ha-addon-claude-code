---
name: TestTemplate
description:
  Render and verify Home Assistant Jinja templates against live state. USE
  WHEN writing or debugging a template — before putting Jinja into an
  automation, script, dashboard, or template sensor, when a template "doesn't
  update", or to check what a template expression evaluates to right now.
  ALWAYS verify templates with ha-template instead of reasoning about Jinja
  from memory.
---

# TestTemplate

Use `ha-template` to render a Jinja template through the WebSocket
`render_template` API — the exact engine automations and dashboards use.

## Commands

```bash
ha-template '{{ states("sun.sun") }}'
ha-template --file template.jinja
ha-template TEMPLATE --var KEY=VALUE ...   # inject variables
ha-template TEMPLATE --watch               # re-render on state changes, Ctrl+C to stop
```

Output is YAML by default (`--format json` for JSON): the rendered `result`
(native type — numbers stay numbers, lists stay lists) plus `listeners`, the
entities/domains/time the template subscribes to.

## Workflow

1. **Draft the template in a file** for anything beyond a one-liner —
   `--file` avoids shell-quoting pain with `{{ }}` and quotes.
2. **Render it** and check both the result and `listeners`. A template that
   should react to an entity but doesn't list it under `listeners` will never
   update in HA either — that's the "my template sensor is stale" bug.
3. **Only then** paste it into the automation/dashboard/sensor config.

## Variables

Templates copied from automations often reference variables like `trigger`
or script `variables`. Inject them with `--var`; values parse as JSON when
possible, else plain strings:

```bash
ha-template '{{ trigger.to_state.state }}' \
    --var trigger='{"to_state": {"state": "on"}}'
ha-template '{{ brightness > 128 }}' --var brightness=200
```

## Examples

```bash
# What does this evaluate to right now?
ha-template '{{ states("sensor.outdoor_temp") | float > 25 }}'

# Verify a notification message template
ha-template '{{ area_name("light.office") }}: {{ states("light.office") }}'

# Debug "why doesn't my template update" — check listeners
ha-template '{{ expand("group.doors") | selectattr("state","eq","on") | list | count }}'

# Watch a condition flip live while you toggle the entity
ha-template '{{ is_state("binary_sensor.front_door", "on") }}' --watch
```

## Gotchas

- Errors (undefined entities, syntax) print to stderr and exit 1 — fix the
  template rather than wrapping it in `default` filters blindly.
- `listeners.all: true` means the template re-renders on EVERY state change
  (e.g. it calls `states` without arguments) — expensive; scope it down.
- `states("x.y")` returns a string; compare numbers with `| float` / `| int`.
- Results keep their native type: `{{ 1 + 1 }}` renders as `2` (int), not
  `"2"` — what template sensors and conditions actually receive.
- `--watch` only re-renders on changes to listed listeners; a template with
  no listeners (pure literals) renders once and then stays silent.

## Setup

Requires the same long-lived token as `ha-entities` (HA_TOKEN env var or
`/homeassistant/.claude/ha_token`); if missing, the tool prints setup steps.
