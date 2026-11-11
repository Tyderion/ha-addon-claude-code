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

Use `ha-trace` to inspect Home Assistant execution traces, the recorded
step-by-step history of automation and script runs.

`ha-trace` is on `PATH`: call it by bare name (a path form such as
`./ha-trace` is rewritten to it anyway). If a call errors, fix the call
rather than writing ad-hoc `ha_lib` scripts or `curl`.

## Commands

```bash
ha-trace list                                   # every automation and script: state, last_triggered, traces_stored, latest run
ha-trace runs <target>                          # every stored run: start, trigger, outcome, last_step
ha-trace show <target> [--run RUN_ID] [--full]  # one run step by step (default: the newest)
```

`<target>` is an entity_id (`automation.morning_lights`, `script.wake_up`),
a friendly name/alias (case-insensitive), or a fragment of either
(`morning`); a fragment matching several items errors and lists them. A
target starting with `automation.` or `script.` must match an entity_id
exactly. All commands output YAML by default; add `--format json` for JSON.

## Debugging Workflow

1. `ha-trace runs <target>`: did it run at all, which trigger fired, how
   did each run end, and where did it stop (`last_step`)?
2. `ha-trace show <target>`: walk through one run step by step, the
   trigger, each condition's true/false result, each executed action,
   errors.
3. **No stored traces?** It has not run recently. `runs` still prints
   `state` (`off` = disabled) and `last_triggered`. If it should have
   fired, check the trigger entity itself: `ha-entities get
<trigger_entity>` for its current state, then `ha-history changes
<trigger_entity> --last 24h` (QueryHistory) to see whether the
   triggering change happened at all. A trigger that never fires leaves no
   trace.
4. **Fired twice, too often or at the wrong time?** `ha-trace runs` lists
   every stored run with its `start` and `trigger`, which usually answers
   it; `show --run <id>` only when you need one run's steps.
5. **What did a run change?** `show` prints the run's `context_id`; `ha-history logbook --context <id>` (QueryHistory) lists every entity that run changed. An automation the run started has its own context.

## Outcome values

The `outcome` field (HA's `script_execution`) tells you how a run ended:

- `finished`: ran to completion
- `failed_conditions`: a condition evaluated false; `last_step` names it
- `cancelled`: a newer run replaced it (`mode: restart`), or it was
  stopped by `automation.turn_off` or Core shutting down
- `failed_single`: skipped because a previous run was still active (`mode: single`)
- `failed_max_runs`: hit the `max` limit of parallel/queued mode
- `aborted`: a `stop:` action with `error: true` ended it
- `error`: an action raised an error; see the `error` field and the failing step in `show`
- `null`: the run is still in progress

## Reading `show` output

`steps` is the executed path in order: `trigger/N` (the N-th trigger in
the automation's list fired; scripts have none), `condition/N` (each with
`result.result: true/false`), `action/N` (each with elapsed `offset_s` and
its result). Paths are zero-indexed and nest inside `choose`, `if` and
`repeat` (`action/1/choose/0/sequence/0`), so a run whose `last_step` is
`condition/1` with `result: false` was blocked by the second condition.
Use `--full` only when the condensed view isn't enough: it dumps the
complete trace including variables and config, which is large.

## Gotchas

- HA keeps only the last ~5 runs per item (`stored_traces` option). They
  survive a clean Core restart but not a crash. This is a debugging tool,
  not history.
- YAML automations without an `id:` field get no traces at all. `runs` and
  `show` say so; `list` just shows `traces_stored: 0`, so a never-traced
  automation there may simply lack an id. Add a unique `id:` and reload to
  enable tracing.
- Blueprint-based automations trace like any other automation.
