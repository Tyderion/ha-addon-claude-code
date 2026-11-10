#!/usr/bin/env python3
"""Unit tests for `ha-secrets`.

Each test points the tool at its own secrets.yaml in a temporary directory.
post_webhook is replaced by a fake that records the request, so `fire` can be
checked without Home Assistant. Standard library plus PyYAML.

Run: python3 ssh/tests/test_ha_secrets.py
"""

import io
import json
import os
import sys
import tempfile
import unittest

import yaml
from toolharness import load_tool, run_tool

SECRETS = """\
# Router admin login
router_password: hunter2

# DDNS updater container on the NAS.
# Must match HA_WEBHOOK_ID in its stack.
ddns_webhook_id: abc123
plain: 1234
"""


class Secrets(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.dir.name, "secrets.yaml")
        self.write(SECRETS)
        self.requests = []

        def post_webhook(method, path, body):
            self.requests.append((method, path, body))
            return 200, None

        self.tool = load_tool("ha-secrets")
        self.tool.SECRETS_FILE = self.path
        self.tool.post_webhook = post_webhook

    def tearDown(self):
        self.dir.cleanup()

    def write(self, text):
        with open(self.path, "w") as f:
            f.write(text)

    def read(self):
        with open(self.path) as f:
            return f.read()

    def run_ok(self, *argv):
        code, out, err = run_tool(self.tool, "ha-secrets", *argv)
        self.assertEqual(code, 0, err)
        return out

    def run_fail(self, *argv):
        code, out, err = run_tool(self.tool, "ha-secrets", *argv)
        self.assertEqual(code, 1)
        return err


class Keys(Secrets):
    def test_lists_names_and_comments_never_values(self):
        code, out, err = run_tool(self.tool, "ha-secrets", "keys")
        self.assertEqual(code, 0, err)
        self.assertEqual(
            out["keys"],
            [
                {"key": "router_password", "comment": "Router admin login"},
                {
                    "key": "ddns_webhook_id",
                    "comment": "DDNS updater container on the NAS. "
                    "Must match HA_WEBHOOK_ID in its stack.",
                },
                {"key": "plain"},
            ],
        )
        printed = json.dumps(out)
        for value in ("hunter2", "abc123", "1234"):
            self.assertNotIn(value, printed)

    def test_search_matches_name_or_comment(self):
        out = self.run_ok("keys", "--search", "nas")
        self.assertEqual([e["key"] for e in out["keys"]], ["ddns_webhook_id"])

    def test_missing_file_is_empty(self):
        os.remove(self.path)
        self.assertEqual(self.run_ok("keys")["keys"], [])

    def test_broken_file_fails(self):
        self.write("a: [unclosed\n")
        self.assertIn("does not parse", self.run_fail("keys"))


class Webhook(Secrets):
    def test_appends_a_new_id_and_prints_it(self):
        out = self.run_ok("webhook", "x3_webhook_id", "--comment", "X3 reader")
        webhook_id = out["webhook_id"]
        self.assertRegex(webhook_id, r"^[A-Za-z0-9]{32}$")
        self.assertEqual(out["path"], f"/api/webhook/{webhook_id}")
        self.assertEqual(out["yaml"], "webhook_id: !secret x3_webhook_id")
        text = self.read()
        self.assertTrue(text.startswith(SECRETS), "existing lines changed")
        self.assertTrue(text.endswith(f"\n# X3 reader\nx3_webhook_id: {webhook_id}\n"))
        self.assertEqual(yaml.safe_load(text)["x3_webhook_id"], webhook_id)

    def test_ids_differ(self):
        a = self.run_ok("webhook", "a")["webhook_id"]
        b = self.run_ok("webhook", "b")["webhook_id"]
        self.assertNotEqual(a, b)

    def test_existing_key_is_refused_and_file_untouched(self):
        self.assertIn("already exists", self.run_fail("webhook", "ddns_webhook_id"))
        self.assertEqual(self.read(), SECRETS)

    def test_bad_name_is_refused(self):
        for key in ("1abc", "a-b", "a b", "x: y"):
            self.assertIn("not a usable name", self.run_fail("webhook", key))
        self.assertEqual(self.read(), SECRETS)

    def test_creates_the_file(self):
        os.remove(self.path)
        out = self.run_ok("webhook", "first")
        self.assertEqual(self.read(), f"first: {out['webhook_id']}\n")

    def test_file_without_trailing_newline(self):
        self.write("a: b")
        out = self.run_ok("webhook", "c")
        self.assertEqual(
            yaml.safe_load(self.read()), {"a": "b", "c": out["webhook_id"]}
        )


class Add(Secrets):
    def test_value_stays_a_string(self):
        self.assertEqual(
            self.run_ok("add", "pin", "0042"), {"key": "pin", "added": True}
        )
        self.assertEqual(yaml.safe_load(self.read())["pin"], "0042")

    def test_awkward_value_reads_back(self):
        value = "p@ss: #word 'with' \"quotes\""
        self.run_ok("add", "tricky", value)
        self.assertEqual(yaml.safe_load(self.read())["tricky"], value)

    def test_value_from_stdin(self):
        old = sys.stdin
        sys.stdin = io.StringIO("from-stdin\n")
        try:
            self.run_ok("add", "token", "-")
        finally:
            sys.stdin = old
        self.assertEqual(yaml.safe_load(self.read())["token"], "from-stdin")

    def test_value_not_printed(self):
        self.assertNotIn("s3cret", json.dumps(self.run_ok("add", "k", "s3cret")))

    def test_empty_value_is_refused(self):
        self.assertIn("empty", self.run_fail("add", "k", ""))

    def test_failed_read_back_is_undone(self):
        real = self.tool.parse
        calls = []

        def parse(text):
            calls.append(text)
            return real(text) if len(calls) == 1 else {}

        self.tool.parse = parse
        self.assertIn("undone", self.run_fail("add", "k", "v"))
        self.assertEqual(self.read(), SECRETS)


class Get(Secrets):
    def test_prints_the_value(self):
        self.assertEqual(
            self.run_ok("get", "router_password"),
            {"key": "router_password", "value": "hunter2"},
        )

    def test_missing_key(self):
        self.assertIn("no 'nope'", self.run_fail("get", "nope"))


class Fire(Secrets):
    def test_posts_to_the_stored_id_without_printing_it(self):
        out = self.run_ok("fire", "ddns_webhook_id", "--data", "ok=true")
        self.assertEqual(self.requests, [("POST", "/api/webhook/abc123", {"ok": True})])
        self.assertNotIn("abc123", json.dumps(out))
        self.assertEqual(out["status"], 200)

    def test_json_body_and_put(self):
        self.run_ok(
            "fire", "ddns_webhook_id", "--json", '{"a": [1]}', "--method", "PUT"
        )
        self.assertEqual(self.requests, [("PUT", "/api/webhook/abc123", {"a": [1]})])

    def test_default_body_is_empty_object(self):
        self.run_ok("fire", "ddns_webhook_id")
        self.assertEqual(self.requests[0][2], {})

    def test_error_status_exits_1(self):
        self.tool.post_webhook = lambda method, path, body: (405, "Method Not Allowed")
        code, out, _ = run_tool(self.tool, "ha-secrets", "fire", "ddns_webhook_id")
        self.assertEqual(code, 1)
        self.assertEqual(out["status"], 405)

    def test_missing_key(self):
        self.assertIn("no 'nope'", self.run_fail("fire", "nope"))
        self.assertEqual(self.requests, [])

    def test_bad_json(self):
        self.assertIn(
            "not valid JSON", self.run_fail("fire", "ddns_webhook_id", "--json", "{")
        )
        self.assertEqual(self.requests, [])


if __name__ == "__main__":
    unittest.main()
