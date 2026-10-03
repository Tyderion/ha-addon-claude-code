#!/usr/bin/env python3
"""Unit tests for `ha-integrations`.

The WebSocket and REST layers (ha_lib) are replaced by an in-memory fake
Home Assistant: config entries, registries, translations, and scripted
config/options flows that behave like Home Assistant's flow manager (form,
menu, create_entry, abort, external). The tests run anywhere with the
standard library only; PyYAML is stubbed if it is missing, since every call
here uses --format json.

Run: python3 ssh/tests/test_ha_integrations.py
"""

import copy
import json
import os
import sys
import tempfile
import unittest

from toolharness import load_tool, run_tool

CONFIG_FLOW = "/api/config/config_entries/flow"
OPTIONS_FLOW = "/api/config/config_entries/options/flow"


def entry(entry_id, domain, title, **extra):
    base = {
        "entry_id": entry_id,
        "domain": domain,
        "title": title,
        "state": "loaded",
        "source": "user",
        "disabled_by": None,
        "reason": None,
        "supports_options": False,
        "supports_reconfigure": False,
        "supports_unload": True,
        "supported_subentry_types": {},
        "pref_disable_polling": False,
        "pref_disable_new_entities": False,
        "num_subentries": 0,
        "created_at": 0,
        "modified_at": 0,
    }
    base.update(extra)
    return base


ENTRIES = [
    entry(
        "hue1",
        "hue",
        "Hue Bridge",
        supports_options=True,
        supports_reconfigure=True,
    ),
    entry("sh1", "shelly", "Plug Kitchen"),
    entry("sh2", "shelly", "Plug Office", state="setup_retry"),
]
DEVICES = [{"id": "d1", "name": "Bridge", "config_entries": ["hue1"]}]
ENTITIES = [
    {"entity_id": "light.desk", "config_entry_id": "hue1"},
    {"entity_id": "switch.plug", "config_entry_id": "sh1"},
]
TRANSLATIONS = {
    "component.hue.options.step.init.title": "Hue options",
    "component.hue.options.step.init.data.allow_unreachable": "Allow unreachable",
    "component.hue.options.step.init.data_description.allow_unreachable": "Help",
    "component.mqtt.config.step.broker.data.broker": "Broker address",
    "component.mqtt.config.step.broker.description": "Connect to {name}",
    "component.mqtt.config.error.cannot_connect": "Failed to connect",
    "component.homeassistant.config.abort.single_instance_allowed": "Only one allowed",
}

PASSWORD = {"text": {"type": "password"}}


class FakeTimeout(RuntimeError):
    pass


class FakeHTTPError(RuntimeError):
    def __init__(self, method, path, status, body):
        self.status = status
        self.body = body
        super().__init__(f"{method} {path} failed: HTTP {status}")


def form(step_id, fields, errors=None, **extra):
    return {
        "type": "form",
        "step_id": step_id,
        "data_schema": fields,
        "errors": errors,
        "description_placeholders": extra.pop("placeholders", None),
        **extra,
    }


class HueOptions:
    """Options flow pre-filling current options, password as suggested_value.

    Saving replaces the options with exactly the submitted data, as Home
    Assistant's OptionsFlowManager does.
    """

    def __init__(self, ha, entry_id):
        self.ha, self.entry_id = ha, entry_id

    def start(self):
        opts = self.ha.options[self.entry_id]
        return form(
            "init",
            [
                {
                    "name": "allow_unreachable",
                    "required": False,
                    "type": "boolean",
                    "default": opts.get("allow_unreachable", False),
                },
                {
                    "name": "password",
                    "required": False,
                    "selector": PASSWORD,
                    "description": {"suggested_value": opts.get("password")},
                },
                {
                    "name": "code",
                    "required": False,
                    "type": "string",
                    "description": {"suggested_value": opts.get("code")},
                },
            ],
        )

    def submit(self, data):
        if self.ha.fail_options_start_after_save:
            self.ha.options_start_error = True
        self.ha.options[self.entry_id] = {
            k: v for k, v in data.items() if k not in self.ha.ignore_option_fields
        }
        self.ha.bump(self.entry_id)
        return {"type": "create_entry", "title": "", "result": True}


class MqttConfig:
    """Config flow: a menu, then a form that validates the broker."""

    def __init__(self, ha, _handler):
        self.ha = ha

    def start(self):
        if self.ha.mqtt_single_instance:
            return {
                "type": "abort",
                "reason": "single_instance_allowed",
                "translation_domain": "homeassistant",
            }
        return {"type": "menu", "step_id": "user", "menu_options": ["broker", "addon"]}

    def submit(self, data):
        if "next_step_id" in data:
            return self.broker_form()
        if not isinstance(data.get("port", 1883), int):
            raise FakeHTTPError(
                "POST", "flow", 400, {"errors": {"port": "expected int"}}
            )
        self.ha.mqtt_input = data
        if data["broker"] == "bad":
            return self.broker_form(errors={"base": "cannot_connect"})
        self.ha.entries.append(entry("mq1", "mqtt", data["broker"]))
        return {
            "type": "create_entry",
            "title": data["broker"],
            "result": self.ha.entries[-1],
        }

    def broker_form(self, errors=None):
        return form(
            "broker",
            [
                {"name": "broker", "required": True, "type": "string"},
                {"name": "port", "required": False, "type": "integer", "default": 1883},
                {"name": "password", "required": False, "selector": PASSWORD},
            ],
            errors=errors,
            placeholders={"name": "Mosquitto"},
        )


class ThreadConfig:
    """A config flow that creates its entry on start, with no form."""

    def __init__(self, ha, _handler):
        self.ha = ha

    def start(self):
        self.ha.entries.append(entry("th1", "thread", "Thread"))
        return {
            "type": "create_entry",
            "title": "Thread",
            "result": self.ha.entries[-1],
        }


class OAuthConfig:
    def __init__(self, ha, _handler):
        pass

    def start(self):
        return {"type": "external", "step_id": "auth", "url": "https://example/auth"}


class HueReconfigure:
    def __init__(self, ha, _handler):
        self.ha = ha

    def start(self):
        return form(
            "reconfigure",
            [
                {
                    "name": "host",
                    "required": True,
                    "type": "string",
                    "description": {"suggested_value": self.ha.hue_host},
                }
            ],
        )

    def submit(self, data):
        self.ha.hue_host = data["host"]
        self.ha.bump("hue1")
        if self.ha.reconfigure_timeout:
            raise FakeTimeout("no answer")
        return {"type": "abort", "reason": self.ha.reconfigure_reason}


class FakeHA:
    def __init__(self):
        self.entries = copy.deepcopy(ENTRIES)
        self.options = {
            "hue1": {"allow_unreachable": False, "password": "hunter2", "code": "0000"}
        }
        self.reconfigure_reason = "reconfigure_successful"
        self.reconfigure_timeout = False
        self.fail_options_start_after_save = False
        self.options_start_error = False
        self.hue_host = "10.0.0.2"
        self.ignore_option_fields = set()
        self.mqtt_single_instance = False
        self.mqtt_input = None
        self.flows = {}
        self.aborted = []
        self.calls = []
        self.next_id = 0

    # -- WebSocket -------------------------------------------------------
    def ws(self, command):
        kind = command["type"]
        self.calls.append(command)
        if kind == "config_entries/get":
            return copy.deepcopy(self.entries)
        if kind == "config_entries/get_single":
            e = self.find(command["entry_id"])
            if e is None:
                raise RuntimeError(
                    "'config_entries/get_single' failed: Config entry not found (not_found)"
                )
            return {"config_entry": copy.deepcopy(e)}
        if kind == "config_entries/update":
            e = self.find(command["entry_id"])
            for k, v in command.items():
                if k not in ("type", "entry_id"):
                    e[k] = v
            return {"config_entry": copy.deepcopy(e), "require_restart": False}
        if kind == "config_entries/disable":
            e = self.find(command["entry_id"])
            e["disabled_by"] = command["disabled_by"]
            e["state"] = "not_loaded" if command["disabled_by"] else "loaded"
            return {"require_restart": False}
        if kind == "config/device_registry/list":
            return copy.deepcopy(DEVICES)
        if kind == "config/entity_registry/list":
            return copy.deepcopy(ENTITIES)
        if kind == "frontend/get_translations":
            return {"resources": TRANSLATIONS}
        if kind == "config_entries/flow/progress":
            return [
                {
                    "flow_id": "f9",
                    "handler": "esphome",
                    "step_id": "discovery_confirm",
                    "context": {
                        "source": "zeroconf",
                        "title_placeholders": {"name": "Living Room Sensor"},
                    },
                }
            ]
        raise AssertionError(f"unexpected WS command {kind}")

    def bump(self, entry_id):
        self.find(entry_id)["modified_at"] += 1

    def find(self, entry_id):
        return next((e for e in self.entries if e["entry_id"] == entry_id), None)

    # -- REST ------------------------------------------------------------
    def http(self, method, path, body=None, timeout=60):
        self.calls.append((method, path, body))
        if path.startswith("/api/config/config_entries/flow_handlers"):
            return ["hue", "mqtt", "shelly"]
        if path.startswith("/api/config/config_entries/entry/"):
            entry_id = path.split("/")[5]
            if method == "DELETE":
                self.entries = [e for e in self.entries if e["entry_id"] != entry_id]
                return {"require_restart": False}
            return {"require_restart": False}
        if method == "POST" and path in (CONFIG_FLOW, OPTIONS_FLOW):
            return self.start_flow(path, body)
        flow_id = path.rsplit("/", 1)[1]
        if method == "DELETE":
            if self.flows.pop(flow_id, None) is None:
                raise FakeHTTPError(method, path, 404, {"message": "Invalid flow"})
            self.aborted.append(flow_id)
            return {"message": "Flow aborted"}
        flow = self.flows[flow_id]
        return self.track(flow_id, flow.submit(body or {}))

    def start_flow(self, path, body):
        handler = body["handler"]
        if path == OPTIONS_FLOW:
            if self.options_start_error:
                raise FakeHTTPError("POST", path, 500, {"message": "boom"})
            flow = HueOptions(self, handler)
        elif "entry_id" in body:
            flow = HueReconfigure(self, handler)
        elif handler == "mqtt":
            flow = MqttConfig(self, handler)
        elif handler == "thread":
            flow = ThreadConfig(self, handler)
        elif handler == "nest":
            flow = OAuthConfig(self, handler)
        else:
            raise FakeHTTPError(
                "POST", path, 404, {"message": "Invalid handler specified"}
            )
        self.next_id += 1
        flow_id = f"f{self.next_id}"
        self.flows[flow_id] = flow
        return self.track(flow_id, flow.start())

    def track(self, flow_id, result):
        result = {**result, "flow_id": flow_id, "handler": "x"}
        if result["type"] in ("create_entry", "abort"):
            self.flows.pop(flow_id, None)
        return result


class Base(unittest.TestCase):
    def setUp(self):
        self.fake = FakeHA()
        self.tool = load_tool(
            "ha-integrations",
            ha_result=self.fake.ws,
            ha_http=self.fake.http,
            HAHTTPError=FakeHTTPError,
            HATimeout=FakeTimeout,
        )

    def run_tool(self, *argv):
        """Run main() with argv; return (exit_code, parsed_json_or_None, stderr)."""
        return run_tool(self.tool, "ha-integrations", *argv)

    def assertNoOpenFlows(self):
        self.assertEqual(self.fake.flows, {}, "a flow was left open")


class ReadTest(Base):
    def test_list_failing(self):
        code, out, _ = self.run_tool("list", "--failing")
        self.assertEqual(code, 0)
        self.assertEqual([e["entry_id"] for e in out["entries"]], ["sh2"])

    def test_resolve_by_title_and_unique_domain(self):
        _, out, _ = self.run_tool("show", "hue bridge")
        self.assertEqual(out["entry_id"], "hue1")
        self.assertEqual(out["entities"], ["light.desk"])
        _, out, _ = self.run_tool("show", "hue")
        self.assertEqual(out["entry_id"], "hue1")

    def test_ambiguous_domain_lists_candidates(self):
        code, _, err = self.run_tool("show", "shelly")
        self.assertEqual(code, 1)
        self.assertIn("sh1", err)
        self.assertIn("sh2", err)

    def test_discovered(self):
        _, out, _ = self.run_tool("discovered")
        self.assertEqual(out["flows"][0]["name"], "Living Room Sensor")


class OptionsTest(Base):
    def test_change_reports_before_after_and_reads_back(self):
        code, out, _ = self.run_tool(
            "options", "hue1", "--step", '{"allow_unreachable": true, "password": "x"}'
        )
        self.assertEqual(code, 0, out)
        self.assertEqual(out["status"], "saved")
        self.assertTrue(out["verified"])
        self.assertEqual(
            out["changes"]["allow_unreachable"], {"before": False, "after": True}
        )
        self.assertEqual(
            out["changes"]["password"], {"before": "********", "after": "********"}
        )
        self.assertEqual(out["submitted"][0]["input"]["password"], "********")
        self.assertEqual(self.fake.options["hue1"]["allow_unreachable"], True)
        self.assertNoOpenFlows()

    def test_without_steps_shows_form_and_aborts(self):
        code, out, _ = self.run_tool("options", "hue1")
        self.assertEqual(code, 1)
        self.assertEqual(out["status"], "needs_input")
        fields = {f["name"]: f for f in out["step"]["fields"]}
        self.assertEqual(fields["allow_unreachable"]["label"], "Allow unreachable")
        self.assertEqual(fields["allow_unreachable"]["current"], False)
        self.assertEqual(fields["password"]["current"], "********")
        self.assertNotIn("hunter2", json.dumps(out))
        self.assertEqual(len(self.fake.aborted), 1)
        self.assertNoOpenFlows()

    def test_omitted_fields_keep_their_current_value(self):
        code, out, _ = self.run_tool(
            "options", "hue1", "--step", '{"allow_unreachable": true}'
        )
        self.assertEqual(code, 0, out)
        self.assertEqual(
            self.fake.options["hue1"],
            {"allow_unreachable": True, "password": "hunter2", "code": "0000"},
        )
        self.assertEqual(out["submitted"][0]["kept"], ["password", "code"])
        self.assertEqual(list(out["changes"]), ["allow_unreachable"])
        self.assertNotIn("hunter2", json.dumps(out))

    def test_null_leaves_a_field_out(self):
        code, _, _ = self.run_tool("options", "hue1", "--step", '{"code": null}')
        self.assertEqual(code, 0)
        self.assertNotIn("code", self.fake.options["hue1"])

    def test_secret_ref_in_plain_field_is_never_printed(self):
        if not hasattr(sys.modules["yaml"], "safe_load"):
            self.skipTest("PyYAML not installed")
        with tempfile.TemporaryDirectory() as d:
            secrets = os.path.join(d, "secrets.yaml")
            with open(secrets, "w") as f:
                f.write("alarm_code: '4711'\n")
            self.tool.SECRETS_FILE = secrets
            code, out, _ = self.run_tool(
                "options", "hue1", "--step", '{"code": "!secret alarm_code"}'
            )
        self.assertEqual(code, 0, out)
        self.assertEqual(self.fake.options["hue1"]["code"], "4711")
        self.assertEqual(
            out["changes"]["code"],
            {"before": "********", "after": "!secret alarm_code"},
        )
        self.assertNotIn("4711", json.dumps(out))
        self.assertNotIn("0000", json.dumps(out))

    def test_read_back_error_still_reports_the_save(self):
        self.fake.fail_options_start_after_save = True
        code, out, _ = self.run_tool(
            "options", "hue1", "--step", '{"allow_unreachable": true}'
        )
        self.assertEqual(code, 0, out)
        self.assertEqual(out["status"], "saved")
        self.assertIsNone(out["verified"])
        self.assertIn("read-back failed", out["notes"][0])

    def test_read_back_mismatch_fails(self):
        self.fake.ignore_option_fields = {"allow_unreachable"}
        code, out, _ = self.run_tool(
            "options", "hue1", "--step", '{"allow_unreachable": true}'
        )
        self.assertEqual(code, 1)
        self.assertFalse(out["verified"])

    def test_entry_without_options_refused(self):
        code, _, err = self.run_tool("options", "sh1")
        self.assertEqual(code, 1)
        self.assertIn("has no options", err)


class AddTest(Base):
    def test_menu_then_form_with_secret(self):
        with tempfile.TemporaryDirectory() as d:
            secrets = os.path.join(d, "secrets.yaml")
            with open(secrets, "w") as f:
                f.write("mqtt_pw: s3cret\n")
            self.tool.SECRETS_FILE = secrets
            if not hasattr(sys.modules["yaml"], "safe_load"):
                self.skipTest("PyYAML not installed")
            code, out, _ = self.run_tool(
                "add",
                "mqtt",
                "--step",
                "broker",
                "--step",
                '{"broker": "core-mosquitto", "password": "!secret mqtt_pw"}',
            )
        self.assertEqual(code, 0, out)
        self.assertEqual(out["status"], "created")
        self.assertEqual(out["entry"]["entry_id"], "mq1")
        self.assertEqual(self.fake.mqtt_input["password"], "s3cret")
        self.assertEqual(out["submitted"][1]["input"]["password"], "!secret mqtt_pw")
        self.assertNotIn("s3cret", json.dumps(out))
        self.assertNoOpenFlows()

    def test_plain_password_is_masked(self):
        code, out, _ = self.run_tool(
            "add",
            "mqtt",
            "--step",
            "broker",
            "--step",
            '{"broker": "core-mosquitto", "password": "plain"}',
        )
        self.assertEqual(code, 0)
        self.assertEqual(out["submitted"][1]["input"]["password"], "********")

    def test_rejected_form_aborts_with_translated_error(self):
        code, out, _ = self.run_tool(
            "add", "mqtt", "--step", "broker", "--step", '{"broker": "bad"}'
        )
        self.assertEqual(code, 1)
        self.assertEqual(out["status"], "rejected")
        self.assertEqual(out["step"]["errors"]["base"]["text"], "Failed to connect")
        self.assertEqual(out["step"]["description"], "Connect to Mosquitto")
        self.assertNoOpenFlows()
        self.assertEqual(self.fake.find("mq1"), None)

    def test_schema_error_400_aborts(self):
        code, out, _ = self.run_tool(
            "add", "mqtt", "--step", "broker", "--step", '{"broker": "a", "port": "x"}'
        )
        self.assertEqual(code, 1)
        self.assertEqual(out["status"], "invalid")
        self.assertEqual(out["errors"]["port"], "expected int")
        self.assertNoOpenFlows()

    def test_unknown_menu_option(self):
        code, out, _ = self.run_tool("add", "mqtt", "--step", "nope")
        self.assertEqual(code, 1)
        self.assertEqual(out["status"], "invalid")
        self.assertEqual(sorted(out["step"]["options"]), ["addon", "broker"])
        self.assertNoOpenFlows()

    def test_form_needs_object(self):
        code, out, _ = self.run_tool("add", "mqtt", "--step", "broker", "--step", "x")
        self.assertEqual(code, 1)
        self.assertIn("needs a JSON object", out["error"])
        self.assertNoOpenFlows()

    def test_abort_reason(self):
        self.fake.mqtt_single_instance = True
        code, out, _ = self.run_tool("add", "mqtt")
        self.assertEqual(code, 1)
        self.assertEqual(out["status"], "aborted")
        self.assertEqual(out["reason"]["text"], "Only one allowed")
        self.assertEqual(self.fake.aborted, [])  # HA closed it; nothing to abort

    def test_external_step_aborts(self):
        code, out, _ = self.run_tool("add", "nest")
        self.assertEqual(code, 1)
        self.assertEqual(out["status"], "external")
        self.assertNotIn("url", out)
        self.assertNoOpenFlows()

    def test_unknown_handler(self):
        code, _, err = self.run_tool("add", "nosuch")
        self.assertEqual(code, 1)
        self.assertIn("has no config flow", err)

    def test_schema_submits_nothing(self):
        code, out, _ = self.run_tool("schema", "add", "mqtt")
        self.assertEqual(code, 0)
        self.assertEqual(out["status"], "schema")
        self.assertEqual(out["step"]["type"], "menu")
        posts = [c for c in self.fake.calls if isinstance(c, tuple) and c[0] == "POST"]
        self.assertEqual(len(posts), 1)  # only the start
        self.assertNoOpenFlows()


class SchemaCreatesTest(Base):
    def test_schema_reports_an_entry_created_on_start(self):
        code, out, _ = self.run_tool("schema", "add", "thread")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["status"], "created")
        self.assertEqual(out["entry"]["entry_id"], "th1")
        self.assertIn("without asking", out["notes"][0])


class ReconfigureTest(Base):
    def test_custom_abort_after_saving_counts_as_reconfigured(self):
        self.fake.reconfigure_reason = "reconfigured_restart_needed"
        code, out, _ = self.run_tool(
            "reconfigure", "hue1", "--step", '{"host": "10.0.0.9"}'
        )
        self.assertEqual(code, 0, out)
        self.assertEqual(out["status"], "reconfigured")
        self.assertEqual(out["reason"]["code"], "reconfigured_restart_needed")
        self.assertIn("saved a change", out["notes"][0])

    def test_timeout_after_saving_is_reported_and_flow_left_alone(self):
        self.fake.reconfigure_timeout = True
        code, out, _ = self.run_tool(
            "reconfigure", "hue1", "--step", '{"host": "10.0.0.9"}'
        )
        self.assertEqual(code, 0, out)
        self.assertEqual(out["status"], "reconfigured")
        # f1 is the timed-out flow; only the read-back flow (f2) is aborted
        self.assertNotIn("f1", self.fake.aborted)

    def test_rejected_without_saving_still_fails(self):
        self.fake.reconfigure_reason = "unique_id_mismatch"
        self.fake.bump = lambda entry_id: None  # nothing saved
        code, out, _ = self.run_tool(
            "reconfigure", "hue1", "--step", '{"host": "10.0.0.9"}'
        )
        self.assertEqual(code, 1)
        self.assertEqual(out["status"], "aborted")

    def test_successful_abort_counts_as_done(self):
        code, out, _ = self.run_tool(
            "reconfigure", "hue1", "--step", '{"host": "10.0.0.9"}'
        )
        self.assertEqual(code, 0, out)
        self.assertEqual(out["status"], "reconfigured")
        self.assertEqual(
            out["changes"]["host"], {"before": "10.0.0.2", "after": "10.0.0.9"}
        )
        self.assertTrue(out["verified"])
        self.assertNoOpenFlows()


class EntryTest(Base):
    def test_update_title(self):
        code, out, _ = self.run_tool("update", "hue1", "--title", "Bridge")
        self.assertEqual(code, 0)
        self.assertTrue(out["verified"])
        self.assertEqual(self.fake.find("hue1")["title"], "Bridge")

    def test_update_dry_run(self):
        _, out, _ = self.run_tool("update", "hue1", "--no-polling", "--dry-run")
        self.assertTrue(out["dry_run"])
        self.assertFalse(self.fake.find("hue1")["pref_disable_polling"])

    def test_disable_dry_run_then_disable_and_enable(self):
        _, out, _ = self.run_tool("disable", "hue1", "--dry-run")
        self.assertEqual(out["affects"]["entities"], ["light.desk"])
        self.assertIsNone(self.fake.find("hue1")["disabled_by"])
        code, out, _ = self.run_tool("disable", "hue1")
        self.assertEqual((code, out["verified"]), (0, True))
        self.assertEqual(self.fake.find("hue1")["disabled_by"], "user")
        code, out, _ = self.run_tool("enable", "hue1")
        self.assertEqual((code, out["verified"]), (0, True))

    def test_delete_dry_run_keeps_entry(self):
        _, out, _ = self.run_tool("delete", "sh1", "--dry-run")
        self.assertEqual(out["removes"]["entities"], ["switch.plug"])
        self.assertIsNotNone(self.fake.find("sh1"))

    def test_delete(self):
        code, out, _ = self.run_tool("delete", "sh1")
        self.assertEqual(code, 0)
        self.assertTrue(out["verified"])
        self.assertIsNone(self.fake.find("sh1"))


if __name__ == "__main__":
    unittest.main(verbosity=1)
