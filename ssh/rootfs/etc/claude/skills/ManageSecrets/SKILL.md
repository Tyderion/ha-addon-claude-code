---
name: ManageSecrets
description: Work with secrets.yaml through ha-secrets, to list names, create or
  test-fire a webhook id, or store or read an API key. USE WHEN a task needs
  a secret, password or webhook id, or "make a webhook for X", "what URL
  does my device post to", "store this token". Never cat, grep, Read or
  append to secrets.yaml, and never curl a webhook by hand (use ha-secrets
  fire).
---

# ManageSecrets

Use `ha-secrets` for everything that involves `secrets.yaml`. Every other
route to the file (a shell command naming it, Read, Edit) asks the user
and puts values in the transcript that the job did not need; `ha-secrets`
answers the same questions without either.

Use a secret, do not read it: in YAML write `!secret <key>`, in an
`ha-integrations` form pass `"!secret <key>"` (ManageIntegration), and to
test a webhook use `fire`. `get` is for when the value itself is what the
user asked for.

`ha-secrets` is on `PATH`: call it by bare name (a path form such as
`./ha-secrets` is rewritten to it anyway). If a call errors, fix the call
rather than writing ad-hoc `ha_lib` scripts or `curl`.

## Commands

```bash
ha-secrets keys [--search TEXT]                     # names and comments, never values
ha-secrets webhook <key> [--comment TEXT]           # generate an id, store it, print it
ha-secrets fire <key> [--data K=V ... | --json BODY] [--method POST|PUT]   # exit 1 on 4xx/5xx
ha-secrets add <key> <value|-> [--comment TEXT]     # asks the user first; - reads stdin; never echoes the value
ha-secrets get <key>                                # asks the user first
```

Output is YAML by default (`--format json` for JSON).

## Webhooks

```bash
ha-secrets webhook x3_reader_webhook_id --comment "X3 battery log, sent by the NAS feed"
# automation trigger:  webhook_id: !secret x3_reader_webhook_id   then ha-reload
ha-secrets fire x3_reader_webhook_id --data battery=87
ha-trace show automation.x3_reader_battery
```

The comment says who sends to the webhook; it is what the next session
sees in `keys`. The output's `path` (`/api/webhook/<id>`) is what the
sender needs, under whatever Home Assistant URL the sender can reach.
`webhook` is the only command that shows the id without asking, so put it
in the same reply to the user; later, "what URL does my device post to" is
a `get`. `fire` sends the request without the id appearing in the command
or the output, and Home Assistant answers 200 whether or not anything
listens, so read the automation's trace, not the status.

## Gotchas

- `--data` values are parsed as JSON when they can be: `87` is a number,
  `true` a boolean, `007` becomes `7`. For a literal string, JSON-quote it
  (`--data 'code="007"'`) or use `--json`.
- `webhook` and `add` refuse a key that already exists and never change an
  existing line. To rotate or remove a secret, ask the user to edit
  `secrets.yaml`; do not read the file to find the line, `keys` has the
  name.
