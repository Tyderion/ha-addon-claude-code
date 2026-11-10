#!/usr/bin/env python3
"""ha-secrets — Work with secrets.yaml without reading or editing it by hand.

Usage:
  ha-secrets keys [--search TEXT]
  ha-secrets webhook KEY [--comment TEXT]
  ha-secrets fire KEY [--data KEY=VALUE ... | --json BODY] [--method M]
  ha-secrets add KEY VALUE [--comment TEXT]
  ha-secrets get KEY

keys     lists the secret names and the comment above each, never a value.
webhook  generates a random webhook id, appends it as KEY and prints it once,
         so it can be configured in whatever sends to the webhook. Use it in
         YAML as `webhook_id: !secret KEY`.
fire     sends a test request to the webhook stored under KEY, without the
         id ever appearing in the command or the output. Home Assistant
         answers 200 whether or not anything listens on that id, so check
         the automation's trace to see what it did.
add      appends KEY with a literal value (`-` reads it from stdin).
get      prints one value.

webhook and add refuse a KEY that already exists and never change existing
lines; changing or removing a secret is a manual edit. The file is parsed
before and after every write, and a write that does not read back is undone.

Accepts --format yaml|json (default: yaml).
"""

import argparse
import json
import os
import re
import string
import sys
import urllib.error
import urllib.parse
import urllib.request
from secrets import choice

import yaml

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from ha_lib import (
    FORMAT_PARENT,
    HA_HOST,
    HA_PORT,
    parse_pairs,
    print_output,
    run_cli,
)

SECRETS_FILE = "/homeassistant/secrets.yaml"
KEY_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
# A top-level key as written by hand: bare, or single- or double-quoted
TOP_LEVEL_KEY_RE = re.compile(r"""^(?:'([^']+)'|"([^"]+)"|([^\s#'"][^:]*?))\s*:""")
# Words YAML 1.1 reads as booleans or null, so a key named like this would
# not compare equal to an existing unquoted one
YAML_WORDS = {"yes", "no", "on", "off", "true", "false", "null", "y", "n", "~"}
WEBHOOK_ID_LENGTH = 32
WEBHOOK_ALPHABET = string.ascii_letters + string.digits


def read_text():
    try:
        with open(SECRETS_FILE, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return ""


def parse(text):
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as e:
        raise RuntimeError(f"{SECRETS_FILE} does not parse: {e}") from None
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise RuntimeError(f"{SECRETS_FILE} is not a mapping of names to values")
    return data


def comments(text):
    """Map each top-level key to the comment block directly above it."""
    found, block = {}, []
    for line in text.splitlines():
        # Only an unindented comment can belong to the next key; an indented
        # one is part of the previous key's block value
        if line.startswith("#"):
            block.append(line.lstrip("#").strip())
            continue
        if m := TOP_LEVEL_KEY_RE.match(line):
            text_block = " ".join(part for part in block if part)
            if text_block:
                found[next(g for g in m.groups() if g is not None)] = text_block
        if not line.startswith((" ", "\t")):
            block = []
    return found


def lookup(key):
    data = parse(read_text())
    if key not in data:
        raise RuntimeError(f"no '{key}' in {SECRETS_FILE} (see `ha-secrets keys`)")
    return data[key]


def append(key, value, comment):
    """Append KEY: VALUE under an optional comment, verified by reading back."""
    if not KEY_RE.match(key):
        raise RuntimeError(
            f"'{key}' is not a usable name: letters, digits and _ only, "
            "not starting with a digit"
        )
    if key.lower() in YAML_WORDS:
        raise RuntimeError(f"'{key}' is a YAML keyword; pick another name")
    existed = os.path.exists(SECRETS_FILE)
    text = read_text()
    if key in parse(text):
        raise RuntimeError(
            f"'{key}' already exists in {SECRETS_FILE}; pick another name "
            "(changing an existing secret is a manual edit)"
        )

    block = "" if not text or text.endswith("\n") else "\n"
    if text.strip():
        block += "\n"
    for line in (comment or "").splitlines():
        block += f"# {line}".rstrip() + "\n"
    block += yaml.safe_dump(
        {key: value}, default_flow_style=False, allow_unicode=True, width=1 << 16
    )

    # A new secrets file is readable by its owner only
    fd = os.open(SECRETS_FILE, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(block)
    try:
        written = parse(read_text()).get(key)
    except RuntimeError:
        written = None
    if written != value:
        if existed:
            with open(SECRETS_FILE, "rb+") as f:
                f.truncate(len(text.encode("utf-8")))
        else:
            os.remove(SECRETS_FILE)
        raise RuntimeError(f"'{key}' did not read back after writing; undone")


def post_webhook(method, path, body):
    """Send a webhook request and return (status, decoded reply)."""
    request = urllib.request.Request(
        f"http://{HA_HOST}:{HA_PORT}{path}",
        data=json.dumps(body).encode(),
        method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as e:
        status, raw = e.code, e.read()
    except urllib.error.URLError as e:
        reason = getattr(e, "reason", e)
        raise RuntimeError(
            f"cannot reach Home Assistant at {HA_HOST}:{HA_PORT}: {reason}"
        ) from None
    text = raw.decode("utf-8", "replace").strip()
    try:
        return status, json.loads(text) if text else None
    except ValueError:
        return status, text


def run_keys(args):
    text = read_text()
    notes = comments(text)
    entries = []
    for key in parse(text):
        if args.search and args.search.lower() not in (
            f"{key} {notes.get(key, '')}".lower()
        ):
            continue
        entry = {"key": key}
        if key in notes:
            entry["comment"] = notes[key]
        entries.append(entry)
    print_output({"file": SECRETS_FILE, "keys": entries}, args.format)


def run_webhook(args):
    webhook_id = "".join(choice(WEBHOOK_ALPHABET) for _ in range(WEBHOOK_ID_LENGTH))
    append(args.key, webhook_id, args.comment)
    print_output(
        {
            "key": args.key,
            "webhook_id": webhook_id,
            "path": f"/api/webhook/{webhook_id}",
            "yaml": f"webhook_id: !secret {args.key}",
        },
        args.format,
    )


def run_fire(args):
    webhook_id = lookup(args.key)
    # HA's webhook_id is a string, but an unquoted number in the file is not
    if isinstance(webhook_id, int) and not isinstance(webhook_id, bool):
        webhook_id = str(webhook_id)
    if not isinstance(webhook_id, str) or not webhook_id:
        raise RuntimeError(f"'{args.key}' does not hold a webhook id")
    if args.json is not None:
        try:
            body = json.loads(args.json)
        except ValueError as e:
            raise RuntimeError(f"--json is not valid JSON: {e}") from None
    else:
        body = parse_pairs(args.data, "--data")
    path = "/api/webhook/" + urllib.parse.quote(webhook_id, safe="")
    status, reply = post_webhook(args.method, path, body)
    out = {"key": args.key, "method": args.method, "status": status}
    if reply is not None:
        out["reply"] = reply
    print_output(out, args.format)
    if status >= 400:
        sys.exit(1)


def run_add(args):
    value = sys.stdin.read().rstrip("\n") if args.value == "-" else args.value
    if not value:
        raise RuntimeError("refusing to add an empty value")
    append(args.key, value, args.comment)
    print_output({"key": args.key, "added": True}, args.format)


def run_get(args):
    print_output({"key": args.key, "value": lookup(args.key)}, args.format)


def main():
    parser = argparse.ArgumentParser(
        prog="ha-secrets",
        description="Work with secrets.yaml without reading or editing it by hand.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser(
        "keys", parents=[FORMAT_PARENT], help="List secret names, never values"
    )
    p.add_argument("--search", metavar="TEXT", help="Filter by name or comment")
    p.set_defaults(func=run_keys)

    p = sub.add_parser(
        "webhook",
        parents=[FORMAT_PARENT],
        help="Generate a webhook id and store it under KEY",
    )
    p.add_argument("key")
    p.add_argument("--comment", metavar="TEXT", help="Comment line(s) above it")
    p.set_defaults(func=run_webhook)

    p = sub.add_parser(
        "fire",
        parents=[FORMAT_PARENT],
        help="Send a test request to the webhook stored under KEY",
    )
    p.add_argument("key")
    body = p.add_mutually_exclusive_group()
    body.add_argument(
        "--data",
        action="append",
        metavar="KEY=VALUE",
        help="Body field; value parsed as JSON when possible (repeatable)",
    )
    body.add_argument("--json", metavar="BODY", help="Whole JSON body")
    p.add_argument(
        "--method", choices=["POST", "PUT"], default="POST", help="(default: POST)"
    )
    p.set_defaults(func=run_fire)

    p = sub.add_parser(
        "add", parents=[FORMAT_PARENT], help="Append KEY with a literal value"
    )
    p.add_argument("key")
    p.add_argument("value", help="The value, or - to read it from stdin")
    p.add_argument("--comment", metavar="TEXT", help="Comment line(s) above it")
    p.set_defaults(func=run_add)

    p = sub.add_parser("get", parents=[FORMAT_PARENT], help="Print one value")
    p.add_argument("key")
    p.set_defaults(func=run_get)

    run_cli(parser)


if __name__ == "__main__":
    main()
