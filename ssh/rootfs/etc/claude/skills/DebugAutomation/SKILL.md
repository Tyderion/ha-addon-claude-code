---
name: DebugAutomation
description:
  Inspect automation and script runs through their execution traces. USE
  WHEN an automation didn't fire, fired twice, too often or at the wrong
  time, ran but did nothing or stopped halfway, a script failed, or the
  question is what an automation actually did ("why didn't the lights turn
  on at sunset"). Check the trace with ha-trace instead of reasoning from
  the YAML.
---

# DebugAutomation

Use `ha-trace` to inspect Home Assistant execution traces — the recorded
step-by-step history of automation and script runs.

`ha-trace` is on `PATH`: call it by bare name (a path form such as
`./ha-trace` is rewritten to it anyway). If a call errors, fix the call
rather than writing ad-hoc `ha_lib` scripts or `curl`.

## Commands

```bash
ha-trace list
ha-trace runs <target>
ha-trace show <target> [--run RUN_ID] [--full]
```

`<target>` is an entity_id (`automation.morning_lights`, `script.wake_up`) or a
friendly name/alias. All commands output YAML by default; add `--format json`
for JSON.

## Debugging Workflow

1. `ha-trace runs <target>` — did it run at all, and how did each run end?
2. `ha-trace show <target>` — walk through the latest run step by step: the
   trigger, each condition's true/false result, each executed action, errors.
3. **No stored traces?** The automation never started since the last Core
   restart. Check the `state` field in the output (`off` = disabled), check
   `last_triggered`, then verify the trigger entity itself with
   `ha-entities get <trigger_entity>` — a trigger that never fires leaves no
   trace. Then `ha-history changes <trigger_entity> --last 24h`
   (QueryHistory) shows whether the triggering change happened at all.
4. **Fired twice, too often or at the wrong time?** `ha-trace runs` lists
   each run with its time; `show --run` on each tells which trigger fired.

## Outcome values

The `outcome` field (HA's `script_execution`) tells you how a run ended:

- `finished` — ran to completion
- `failed_conditions` — a condition evaluated false; `show` reveals which one
- `cancelled` — stopped early (restart, `mode: restart`, or manual stop)
- `failed_single` — skipped because a previous run was still active (`mode: single`)
- `failed_max_runs` — hit the `max` limit of parallel/queued mode
- `error` — an action raised an error; see the `error` field and the failing step

## Reading `show` output

`steps` is the executed path in order: `trigger/0` (what fired), `condition/N`
(each with `result.result: true/false`), `action/N` (each with elapsed
`offset_s` and its result). The run stops at the last listed step — a run
ending on `condition/1` with `result: false` means condition 2 blocked it.
Use `--full` only when the condensed view isn't enough: it dumps the complete
trace including variables and config, which is large.

## Examples

```bash
# Overview: which automations/scripts have recent runs, and their outcomes
ha-trace list

# Why didn't the morning lights come on?
ha-trace runs "Morning lights"
ha-trace show automation.morning_lights

# Inspect a specific earlier run
ha-trace show automation.morning_lights --run 8b46a3f60d0b4f568650bd10c4f0341c
```

## Gotchas

- Traces exist only for runs that **started**. "It never triggered" cannot be
  answered by a trace — use the workflow above (enabled? trigger entity?).
- HA stores only the last ~5 runs per item (`stored_traces` option) and
  discards all traces on Core restart. This is a debugging tool, not history.
- YAML automations without an `id:` field get no traces at all; `ha-trace`
  reports this explicitly. Add a unique `id:` and reload to enable tracing.
- Blueprint-based automations trace like any other automation.
