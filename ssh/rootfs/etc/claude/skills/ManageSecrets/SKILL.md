---
name: ManageSecrets
description:
  Work with secrets.yaml through ha-secrets, to list names, create or test-
  fire a webhook id, or store or read an API key. USE WHEN a task needs a
  secret, password or webhook id, or "make a webhook for X", "what URL does
  my device post to", "store this token". Never cat, grep, Read or append to
  secrets.yaml, and never curl a webhook by hand (use ha-secrets fire).
---

# ManageSecrets

Use `ha-secrets` for everything that involves `secrets.yaml`. Any shell
command that names the file asks the user first, every time, so reading
it to look up a name or a webhook id costs a prompt that `ha-secrets`
avoids.

`ha-secrets` is on `PATH`: call it by bare name (a path form such as
`./ha-secrets` is rewritten to it anyway). If a call errors, fix the call
rather than writing ad-hoc `ha_lib` scripts or `curl`.

## Commands

```bash
ha-secrets keys [--search TEXT]                     # names and comments, never values
ha-secrets webhook <key> [--comment TEXT]           # generate an id, store it, print it once
ha-secrets fire <key> [--data K=V ... | --json BODY] [--method POST|PUT]
ha-secrets add <key> <value|-> [--comment TEXT]     # asks the user first
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

1. **Create the id** with a comment saying who sends to it: the comment
   is what the next session sees in `ha-secrets keys`.
2. **Reference it** in the trigger as `webhook_id: !secret <key>`, then
   `ha-reload`.
3. **Hand the id over.** The output's `webhook_id` (or `path`) is what the
   sender needs. This is the one time it is printed, so give it to the
   user in the same reply.
4. **Test it** with `fire`. The id never appears in the command or the
   output. Home Assistant answers 200 even when nothing listens on the id,
   so check the automation's trace, not the status code.

## Gotchas

- `webhook` and `add` refuse a key that already exists, and neither ever
  changes an existing line. Rotating or removing a secret is a manual edit
  of `secrets.yaml`, which asks the user.
- Key names are letters, digits and `_`, not starting with a digit.
- `add` takes the value as an argument or, with `-`, from stdin. It never
  prints the value back.
- Only reach for `get` when the value itself is the answer the user asked
  for. To use a secret in config, write `!secret <key>`; to test a webhook,
  use `fire`.
