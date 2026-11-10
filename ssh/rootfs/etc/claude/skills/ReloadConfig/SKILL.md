---
name: ReloadConfig
description:
  Apply YAML changes with ha-reload, and decide when a full restart is
  needed instead. USE WHEN a YAML file was edited, or the user asks to
  reload config or restart Home Assistant; ha-reload hot-reloads, ha core
  restart only when a reload cannot pick the change up.
---

# ReloadConfig

`ha-reload` is on `PATH`, takes no arguments and reloads every
hot-reloadable domain at once (a path form such as `./ha-reload` is
rewritten to the bare name anyway). If it fails it prints why; do not
reproduce it with `curl` against the Supervisor API.

If only one domain changed and other automations may be mid-run, reload
just that domain instead: `ha-service call automation.reload` (or
`script.reload`, `template.reload`, `rest.reload`, ...). A full reload
stops every running automation and script. Integrations set up in the UI
are not YAML: use `ha-integrations reload <entry>` (ManageIntegration).

## When to Use Each Command

| Command           | Use When                                                                                                                    | Downtime                                       |
| ----------------- | --------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| `ha-reload`       | Any edit inside a domain listed under "What ha-reload Reloads"                                                              | None; a few seconds while HA checks the config |
| `ha core restart` | A top-level key for a YAML integration that is not loaded yet, `logger:`/`recorder:`/`http:` changes, custom component code | 30+ seconds; asks the user first               |

## Workflow

1. **Validate:** every YAML edit under `/homeassistant` is parse-checked
   automatically by a hook (syntax and duplicate keys); fix any error it
   returns first. `yamllint <file>` is optional and checks style, not
   whether HA accepts the file.
2. **Apply:** `ha-reload`. It is all-or-nothing: Home Assistant checks the
   whole configuration first and, if anything is invalid, reloads nothing
   and `ha-reload` exits 1 with HA's error text. Exit 0 can still hide a
   per-domain setup error (a template that fails at runtime); if the
   change is not live, `ha core logs` has it.
3. **Restart only for the cases in the table.** Run `ha core check` (~30s)
   first, since a restart with an invalid config boots into safe mode,
   and tell the user what the restart is for:
   ```bash
   ha core check && ha core restart
   ```

## What ha-reload Reloads

Everything Developer Tools → YAML → Quick Reload reloads: every loaded
integration that offers a `<domain>.reload` service (all except `notify`),
plus the `homeassistant:` core section (name, location, units, customize),
themes and custom Jinja templates. That covers automations, scripts,
scenes, groups, every `input_*` helper, `template:`, timers, counters,
schedules, zones, persons, and YAML platforms such as `rest`,
`command_line`, `shell_command` and `mqtt`. The authoritative list on this
instance is `ha-service list --search reload`.
