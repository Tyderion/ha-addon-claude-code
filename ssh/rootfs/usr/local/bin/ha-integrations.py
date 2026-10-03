#!/usr/bin/env python3
"""ha-integrations — Inspect, add, configure and remove Home Assistant integrations.

Usage:
  ha-integrations list [--domain DOMAIN] [--search TEXT] [--state STATE]
                       [--failing]
  ha-integrations show <entry>
  ha-integrations handlers [--search TEXT] [--helpers]
  ha-integrations discovered
  ha-integrations schema add <domain>
  ha-integrations schema options|reconfigure <entry>
  ha-integrations add <domain> [--step INPUT ...]
  ha-integrations options <entry> [--step INPUT ...]
  ha-integrations reconfigure <entry> [--step INPUT ...]
  ha-integrations update <entry> [--title TITLE] [--polling | --no-polling]
                         [--new-entities | --no-new-entities] [--dry-run]
  ha-integrations disable <entry> [--dry-run]
  ha-integrations enable <entry>
  ha-integrations reload <entry>
  ha-integrations delete <entry> [--dry-run]

All commands accept --format yaml|json (default: yaml).

An integration instance is a config entry, which Home Assistant keeps in
.storage/core.config_entries. Everything here goes through Home Assistant's
own config entry API (WebSocket and REST), which applies changes live and
never touches .storage. That API never returns an entry's stored
credentials, and password fields are masked in everything this tool prints.

<entry> is an entry_id, an entry title, or a domain that has exactly one
entry (title and domain match case-insensitively). An ambiguous value lists
the candidates.

`add`, `options` and `reconfigure` drive a config flow: the multi-step
dialog the UI shows. Each --step is the input for the next step, in order:
a JSON object for a form, or an option id for a menu. A string value of
"!secret NAME" in a form is read from secrets.yaml and sent to Home
Assistant without being printed. The run stops at the first step it cannot
complete (a form with no --step left for it, a validation error, an abort,
or an external step such as an OAuth login) and aborts the flow, so a
stopped run saves nothing; the output then shows that step's fields with
their labels, help texts and current values. `schema` shows a flow's first
step and aborts, without submitting anything.

`options` and `reconfigure` print each submitted field before and after,
and read the result back by reopening the flow and comparing the form's
pre-filled values. `update`, `disable`, `enable` and `delete` read the
entry back too. A read-back mismatch exits 1.
"""

import argparse
import datetime
import functools
import json
import os
import re
import sys
import time

import yaml

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
from ha_lib import (
    FORMAT_PARENT,
    HAHTTPError,
    HATimeout,
    ha_http,
    ha_result,
    print_output,
    run_cli,
)

HA_CONFIG = "/homeassistant"
SECRETS_FILE = os.path.join(HA_CONFIG, "secrets.yaml")
CONFIG_FLOW = "/api/config/config_entries/flow"
OPTIONS_FLOW = "/api/config/config_entries/options/flow"
FAILING_STATES = ("setup_error", "setup_retry", "migration_error", "failed_unload")
# Field names whose values are masked even without a password selector
SECRET_NAME_RE = re.compile(
    r"password|passphrase|passwd|secret|token|api_?key|private_?key|credential"
    r"|(^|_)(pin|psk|key)($|_)",
    re.IGNORECASE,
)
SECRET_REF_RE = re.compile(r"^!secret\s+(\S+)$")
MASK = "********"
MISSING = object()
PROGRESS_TIMEOUT = 120
PROGRESS_POLL = 2
# Submitting a step can mean Home Assistant connecting to a device first
SUBMIT_TIMEOUT = 180


# ── entries ─────────────────────────────────────────────────────────────────


def all_entries():
    return ha_result({"type": "config_entries/get"}) or []


def resolve_entry(value, entries=None):
    """Map an entry_id, title or single-entry domain to its config entry."""
    entries = all_entries() if entries is None else entries
    for e in entries:
        if e["entry_id"] == value:
            return e
    wanted = value.strip().lower()
    for field in ("title", "domain"):
        matches = [e for e in entries if (e.get(field) or "").lower() == wanted]
        if len(matches) == 1:
            return matches[0]
        if matches:
            listing = "; ".join(
                f"{e['entry_id']} ({e['domain']}: {e.get('title')})" for e in matches
            )
            raise RuntimeError(
                f"'{value}' matches {len(matches)} entries, pass an entry_id: {listing}"
            )
    raise RuntimeError(
        f"no integration entry '{value}' (try `ha-integrations list --search TEXT`)"
    )


def get_single(entry_id):
    """Return the entry, or None if it no longer exists."""
    try:
        result = ha_result({"type": "config_entries/get_single", "entry_id": entry_id})
    except RuntimeError as e:
        if "not_found" in str(e) or "not found" in str(e).lower():
            return None
        raise
    return (result or {}).get("config_entry")


def supports(entry):
    flags = []
    if entry.get("supports_options"):
        flags.append("options")
    if entry.get("supports_reconfigure"):
        flags.append("reconfigure")
    if entry.get("supported_subentry_types"):
        flags.append("subentries")
    if entry.get("supports_unload"):
        flags.append("reload")
    return flags


def summary(entry):
    """The compact view used by `list` and in command outputs."""
    out = {
        "entry_id": entry["entry_id"],
        "domain": entry["domain"],
        "title": entry.get("title"),
        "state": entry.get("state"),
    }
    if entry.get("disabled_by"):
        out["disabled_by"] = entry["disabled_by"]
    if entry.get("reason"):
        out["reason"] = entry["reason"]
    if entry.get("source") not in (None, "user"):
        out["source"] = entry["source"]
    flags = supports(entry)
    if flags:
        out["supports"] = flags
    return out


def owned_items(entry_id):
    """Return the devices and entities that belong to an entry."""
    devices = [
        {"device_id": d["id"], "name": d.get("name_by_user") or d.get("name")}
        for d in ha_result({"type": "config/device_registry/list"}) or []
        if entry_id in (d.get("config_entries") or [])
    ]
    entities = sorted(
        e["entity_id"]
        for e in ha_result({"type": "config/entity_registry/list"}) or []
        if e.get("config_entry_id") == entry_id
    )
    return devices, entities


def iso(ts):
    if isinstance(ts, (int, float)):
        return datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).isoformat()
    return ts


# ── translations ────────────────────────────────────────────────────────────


@functools.cache
def _resources(domain, category):
    """English translation resources for one integration and category.

    Fetched once per domain and category. Labels are a convenience: when the
    lookup fails the result is empty and the output carries field names only.
    """
    try:
        result = ha_result(
            {
                "type": "frontend/get_translations",
                "language": "en",
                "category": category,
                "integration": [domain],
            }
        )
        return (result or {}).get("resources") or {}
    except RuntimeError:
        return {}


def translator(domain, category):
    """Return t(path) looking up component.<domain>.<category>.<path> in English.

    When the lookup fails, t() returns None and the output simply carries field
    names only.
    """
    resources = _resources(domain, category)
    prefix = f"component.{domain}.{category}."

    def t(path, placeholders=None):
        text = resources.get(prefix + path)
        if text and placeholders:
            for key, value in placeholders.items():
                text = text.replace("{" + key + "}", str(value))
        return text

    t.category = category
    return t


def without_none(d):
    return {k: v for k, v in d.items() if v is not None}


# ── form schema ─────────────────────────────────────────────────────────────


def is_secret_field(field):
    selector = field.get("selector") or {}
    text = selector.get("text") if isinstance(selector, dict) else None
    if isinstance(text, dict) and text.get("type") == "password":
        return True
    return bool(SECRET_NAME_RE.search(str(field.get("name", ""))))


def prefill(field):
    """Return the value the UI would pre-fill, or MISSING."""
    description = field.get("description")
    if isinstance(description, dict) and "suggested_value" in description:
        return description["suggested_value"]
    return field.get("default", MISSING)


def flatten_fields(fields, prefix=""):
    """Yield (dotted_name, field) for every field, descending into sections."""
    for field in fields or []:
        name = prefix + str(field.get("name"))
        if field.get("type") == "expandable":
            yield from flatten_fields(field.get("schema"), name + ".")
        else:
            yield name, field


def render_field(field, t, path):
    name = field.get("name")
    if field.get("type") == "expandable":
        return without_none(
            {
                "name": name,
                "section": True,
                "label": t(f"{path}.sections.{name}.name"),
                "fields": [
                    render_field(f, t, f"{path}.sections.{name}")
                    for f in field.get("schema") or []
                ],
            }
        )
    out = {
        "name": name,
        "required": bool(field.get("required")),
        "label": t(f"{path}.data.{name}"),
        "help": t(f"{path}.data_description.{name}"),
    }
    for key, value in field.items():
        if key not in ("name", "required", "optional", "default", "description"):
            out[key] = value
    current = prefill(field)
    if current is not MISSING:
        out["current"] = MASK if is_secret_field(field) and current else current
    return without_none(out)


def render_step(result, t):
    """Turn a flow result into what Claude needs to answer the step."""
    step_id = result.get("step_id")
    placeholders = result.get("description_placeholders") or {}
    path = f"step.{step_id}"
    out = {
        "step_id": step_id,
        "type": result.get("type"),
        "title": t(f"{path}.title", placeholders),
        "description": t(f"{path}.description", placeholders),
    }
    if result.get("type") == "menu":
        options = result.get("menu_options") or []
        labels = options if isinstance(options, dict) else {}
        out["options"] = {
            opt: labels.get(opt) or t(f"{path}.menu_options.{opt}") or opt
            for opt in options
        }
        out["answer_with"] = "--step OPTION"
    else:
        out["fields"] = [
            render_field(f, t, path) for f in result.get("data_schema") or []
        ]
        if result.get("last_step") is not None:
            out["last_step"] = result["last_step"]
        out["answer_with"] = (
            "--step '<JSON object>': fields you leave out keep their current "
            "value; null leaves one empty"
        )
    if result.get("errors"):
        out["errors"] = render_errors(result["errors"], t)
    return without_none(out)


def render_errors(errors, t):
    if not isinstance(errors, dict):
        return errors
    return {
        field: without_none({"code": code, "text": t(f"error.{code}")})
        if isinstance(code, str)
        else code
        for field, code in errors.items()
    }


# ── step input ──────────────────────────────────────────────────────────────


@functools.cache
def load_secrets():
    try:
        with open(SECRETS_FILE, encoding="utf-8") as f:
            data = yaml.safe_load(f)
    except FileNotFoundError:
        raise RuntimeError(f"!secret used but {SECRETS_FILE} does not exist") from None
    return data if isinstance(data, dict) else {}


def resolve_secrets(value):
    """Return (value to send, value to print) with !secret refs resolved.

    The printable copy keeps the "!secret NAME" text. secrets.yaml is read
    (once) only when a reference is found.
    """
    if isinstance(value, dict):
        pairs = {k: resolve_secrets(v) for k, v in value.items()}
        return {k: p[0] for k, p in pairs.items()}, {k: p[1] for k, p in pairs.items()}
    if isinstance(value, list):
        pairs = [resolve_secrets(v) for v in value]
        return [p[0] for p in pairs], [p[1] for p in pairs]
    if isinstance(value, str) and (m := SECRET_REF_RE.match(value)):
        secrets = load_secrets()
        if m.group(1) not in secrets:
            raise RuntimeError(f"no '{m.group(1)}' in {SECRETS_FILE}")
        return secrets[m.group(1)], value
    return value, value


def is_secret_ref(value):
    return isinstance(value, str) and bool(SECRET_REF_RE.match(value))


def mask_input(shown, fields):
    """Mask secret fields in a printable copy of form input."""
    if not isinstance(shown, dict):
        return shown
    by_name = {str(f.get("name")): f for f in fields or []}
    out = {}
    for key, v in shown.items():
        field = by_name.get(str(key), {"name": key})
        if field.get("type") == "expandable" and isinstance(v, dict):
            out[key] = mask_input(v, field.get("schema"))
        elif is_secret_ref(v) or v is None:
            out[key] = v  # the reference, never the resolved value
        elif is_secret_field(field):
            out[key] = MASK
        else:
            out[key] = v
    return out


def fill_omitted(given, fields, prefix=""):
    """Complete form input the way the UI does.

    The UI submits every field with its pre-filled value unless the user
    changes it, and options flows store exactly what is submitted, so a
    field left out of --step would otherwise be dropped from the saved
    options. Fields left out get their pre-filled value; an explicit null
    leaves a field out. Returns (payload, names of the fields filled in).
    """
    given = dict(given)
    payload, kept = {}, []
    for field in fields or []:
        name = str(field.get("name"))
        if field.get("type") == "expandable":
            inner = given.pop(name, {})
            if isinstance(inner, dict):
                sub, sub_kept = fill_omitted(
                    inner, field.get("schema"), f"{prefix}{name}."
                )
                if sub:
                    payload[name] = sub
                kept += sub_kept
            elif inner is not None:
                payload[name] = inner
            continue
        if name in given:
            value = given.pop(name)
            if value is not None:
                payload[name] = value
            continue
        current = prefill(field)
        if current is not MISSING:
            payload[name] = current
            kept.append(prefix + name)
    payload.update(given)  # unknown keys: let Home Assistant reject them
    return payload, kept


def parse_step(raw):
    """Parse one --step value: a JSON object for a form, else a menu option."""
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    return value if isinstance(value, (dict, str)) else raw


def flat_input(value, fields):
    """Flatten form input to {dotted_name: value}, descending into sections only.

    Matches flatten_fields, so a field whose own value is an object (a
    location, a duration) stays one entry.
    """
    sections = {
        str(f.get("name")): f.get("schema")
        for f in fields or []
        if f.get("type") == "expandable"
    }
    out = {}
    for key, v in (value or {}).items():
        if str(key) in sections and isinstance(v, dict):
            for name, inner in flat_input(v, sections[str(key)]).items():
                out[f"{key}.{name}"] = inner
        else:
            out[str(key)] = v
    return out


def same(a, b):
    if a == b:
        return True
    try:
        return float(a) == float(b)
    except (TypeError, ValueError):
        return str(a) == str(b)


# ── flows ───────────────────────────────────────────────────────────────────


class Flow:
    """One config, options or reconfigure flow, aborted unless it finishes."""

    def __init__(self, base, start_body):
        self.base = base
        self.start_body = start_body
        self.flow_id = None

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.abort()
        return False

    def start(self):
        body = {**self.start_body, "show_advanced_options": True}
        try:
            result = ha_http("POST", self.base, body, timeout=SUBMIT_TIMEOUT)
        except HAHTTPError as e:
            if e.status == 404:
                handler = self.start_body["handler"]
                raise RuntimeError(
                    f"'{handler}' has no config flow here: either no such integration "
                    "(see `ha-integrations handlers --search TEXT`) or it is set up "
                    "in YAML. "
                    f"({e})"
                ) from None
            raise
        return self._track(result)

    def submit(self, payload):
        try:
            result = ha_http(
                "POST", f"{self.base}/{self.flow_id}", payload, timeout=SUBMIT_TIMEOUT
            )
        except HATimeout:
            # Home Assistant may still be running the step, and a reconfigure
            # step saves inside it. Aborting now could race that save, so the
            # flow is left alone and the caller checks the entry instead.
            self.flow_id = None
            raise
        return self._track(result)

    def refresh(self):
        return self._track(ha_http("GET", f"{self.base}/{self.flow_id}"))

    def _track(self, result):
        result = result or {}
        self.flow_id = result.get("flow_id") or self.flow_id
        if result.get("type") in ("create_entry", "abort"):
            self.flow_id = None  # Home Assistant has already closed it
        return result

    def abort(self):
        if self.flow_id is None:
            return
        flow_id, self.flow_id = self.flow_id, None
        try:
            ha_http("DELETE", f"{self.base}/{flow_id}")
        except RuntimeError:
            pass  # already gone

    def wait_for_progress(self, result):
        deadline = time.monotonic() + PROGRESS_TIMEOUT
        while result.get("type") == "progress":
            if time.monotonic() > deadline:
                return None
            time.sleep(PROGRESS_POLL)
            result = self.refresh()
        return result


def flow_target(kind, value):
    """Return (flow base url, start body, domain, entry or None) for a flow."""
    if kind == "add":
        return CONFIG_FLOW, {"handler": value}, value, None
    entry = resolve_entry(value)
    if kind == "options":
        if not entry.get("supports_options"):
            raise RuntimeError(
                f"{entry['domain']} '{entry.get('title')}' has no options; "
                "try `reconfigure` if it supports that (see `show`)"
            )
        return OPTIONS_FLOW, {"handler": entry["entry_id"]}, entry["domain"], entry
    if not entry.get("supports_reconfigure"):
        raise RuntimeError(
            f"{entry['domain']} '{entry.get('title')}' cannot be reconfigured; "
            "try `options` if it has them, or delete and add it again"
        )
    body = {"handler": entry["domain"], "entry_id": entry["entry_id"]}
    return CONFIG_FLOW, body, entry["domain"], entry


def run_flow(flow, steps, t):
    """Walk a flow through `steps`.

    Returns (status, details). "done" means Home Assistant finished the flow
    (created or saved something); every other status leaves it open, and the
    caller's `with` block aborts it.
    """
    submitted = []
    forms = []  # (step result, flat explicit input, flat printable input)
    result = flow.start()
    remaining = [parse_step(s) for s in steps]
    just_submitted = False

    def stop(status, **extra):
        return status, {"submitted": submitted, "forms": forms, **extra}

    while True:
        kind = result.get("type")
        if kind == "progress":
            result = flow.wait_for_progress(result)
            if result is None:
                return stop(
                    "timeout", note=f"still in progress after {PROGRESS_TIMEOUT}s"
                )
            continue

        if kind == "form" and just_submitted and result.get("errors"):
            return stop("rejected", step=render_step(result, t))

        if kind in ("form", "menu"):
            if not remaining:
                return stop("needs_input", step=render_step(result, t))
            value = remaining.pop(0)
            step_id = result.get("step_id")
            if kind == "menu":
                if isinstance(value, dict):
                    value = value.get("next_step_id")
                options = list(result.get("menu_options") or [])
                if value not in options:
                    return stop(
                        "invalid",
                        error=f"'{value}' is not an option of menu '{step_id}'",
                        step=render_step(result, t),
                    )
                payload, record = {"next_step_id": value}, {"input": value}
            else:
                if not isinstance(value, dict):
                    return stop(
                        "invalid",
                        error=f"form '{step_id}' needs a JSON object, got {value!r}",
                        step=render_step(result, t),
                    )
                fields = result.get("data_schema")
                explicit, shown = resolve_secrets(value)
                payload, kept = fill_omitted(explicit, fields)
                record = {"input": mask_input(shown, fields)}
                if kept:
                    record["kept"] = kept
                forms.append(
                    (
                        result,
                        {
                            k: v
                            for k, v in flat_input(explicit, fields).items()
                            if v is not None
                        },
                        flat_input(shown, fields),
                    )
                )
            try:
                next_result = flow.submit(payload)
            except HATimeout:
                submitted.append({"step_id": step_id, **record})
                return stop(
                    "timeout",
                    note=f"no answer to step '{step_id}' within {SUBMIT_TIMEOUT}s; "
                    "Home Assistant may still be working on it",
                )
            except HAHTTPError as e:
                if e.status != 400:
                    raise
                # Schema validation failed: current releases answer
                # {"errors": {field: message}}, older ones a plain message.
                # These are messages, not translation keys.
                body = e.body if isinstance(e.body, dict) else {"message": e.body}
                return stop(
                    "invalid",
                    errors=body.get("errors"),
                    error=body.get("message"),
                    step=render_step(result, t),
                )
            submitted.append({"step_id": step_id, **record})
            result, just_submitted = next_result, True
            continue

        extra = {"unused_steps": len(remaining)} if remaining else {}
        if kind == "create_entry":
            return stop("done", result=result, **extra)
        if kind == "abort":
            reason = result.get("reason")
            placeholders = result.get("description_placeholders")
            path = f"abort.{reason}"
            domain_t = result.get("translation_domain")
            text = (
                domain_t and translator(domain_t, t.category)(path, placeholders)
            ) or t(path, placeholders)
            details_reason = without_none({"code": reason, "text": text})
            if str(reason).endswith("_successful"):
                return stop("done", reason=details_reason, **extra)
            return stop("aborted", reason=details_reason, **extra)
        if kind == "external":
            return stop(
                "external",
                note="this step needs a browser (usually an OAuth login), which this "
                "tool cannot do; the flow has been aborted and its link no longer "
                "works. Set the integration up in the Home Assistant UI",
            )
        return stop("unexpected", note=f"unexpected flow result type '{kind}'")


def changes_from_forms(forms):
    """Return {field: {before, after}} for explicitly submitted fields that changed."""
    changes = {}
    for result, flat, shown in forms:
        fields = dict(flatten_fields(result.get("data_schema")))
        for name, after in flat.items():
            field = fields.get(name, {"name": name})
            before = prefill(field)
            if before is not MISSING and same(before, after):
                continue
            ref = shown.get(name) if is_secret_ref(shown.get(name)) else None
            secret = bool(ref) or is_secret_field(field)
            change = {}
            if before is not MISSING:
                change["before"] = MASK if secret and before else before
            change["after"] = ref or (MASK if secret else after)
            changes[name] = change
    return changes


def read_back(base, start_body, submitted, forms):
    """Reopen the flow and compare the first submitted form's pre-fills.

    Menu choices made before that form are replayed to reach it; nothing is
    submitted past it. Returns (verified, checked_fields): verified is None
    when the form does not pre-fill any of the submitted fields.
    """
    if not forms:
        return None, []
    first_form, wanted, _ = forms[0]
    with Flow(base, start_body) as flow:
        result = flow.start()
        for step in submitted:
            if result.get("type") == "form":
                break
            if result.get("type") != "menu" or result.get("step_id") != step["step_id"]:
                return None, []
            result = flow.submit({"next_step_id": step["input"]})
        if result.get("type") != "form" or result.get("step_id") != first_form.get(
            "step_id"
        ):
            return None, []
        fields = dict(flatten_fields(result.get("data_schema")))
        checked, mismatched = [], []
        for name, value in wanted.items():
            field = fields.get(name)
            current = prefill(field) if field else MISSING
            if current is MISSING:
                continue
            checked.append(name)
            if not same(current, value):
                mismatched.append(name)
    if not checked:
        return None, []
    return not mismatched, checked


def entry_stamps(domain, entry):
    """Return {entry_id: modified_at} for the entry a flow touches.

    For `add` that is every entry of the domain, so a new one shows up.
    """
    try:
        entries = all_entries()
    except RuntimeError:
        return None
    if entry:
        return {
            e["entry_id"]: e.get("modified_at")
            for e in entries
            if e["entry_id"] == entry["entry_id"]
        }
    return {
        e["entry_id"]: e.get("modified_at") for e in entries if e["domain"] == domain
    }


def changed_entries(before, domain, entry):
    after = entry_stamps(domain, entry)
    if before is None or after is None:
        return []
    return [i for i, stamp in after.items() if before.get(i) != stamp]


def flow_output(kind, target, status, details):
    output = {"flow": kind, "target": target, "status": status}
    if details.get("submitted"):
        output["submitted"] = details["submitted"]
    for key in ("step", "errors", "error", "reason", "note", "unused_steps"):
        if details.get(key) is not None:
            output[key] = details[key]
    return output


def finish_flow(
    args, kind, status, details, *, base, start_body, domain, entry, stamps, schema
):
    """Report a flow run, reading back whatever Home Assistant saved."""
    output = flow_output(kind, args.target, status, details)
    if entry:
        output["entry"] = summary(entry)
    notes = []

    changed = []
    if status != "done" and (details.get("submitted") or status == "timeout"):
        # A flow can save and still end in an abort with a custom reason,
        # or save while the tool timed out waiting; the entry tells.
        changed = changed_entries(stamps, domain, entry)
        if changed:
            notes.append(
                f"Home Assistant saved a change although the flow ended with "
                f"'{status}'; treat it as applied"
            )
    if status != "done" and not changed:
        if schema and status == "needs_input":
            output["status"] = "schema"
            output["note"] = "nothing was submitted; the flow has been aborted"
            output.pop("submitted", None)
            print_output(output, args.format)
            return
        print_output(output, args.format)
        sys.exit(1)
    if schema:
        notes.append("the flow finished without asking for anything")

    if kind == "add":
        result = details.get("result") or {}
        created_id = (result.get("result") or {}).get("entry_id") or (
            changed[0] if changed else None
        )
        output["status"] = "created" if created_id else "finished"
        if created_id:
            try:
                fetched = get_single(created_id)
            except RuntimeError as e:
                fetched = None
                notes.append(f"could not read the new entry back: {e}")
            output["entry"] = summary(
                fetched
                or result.get("result")
                or {"entry_id": created_id, "domain": domain}
            )
            output["verified"] = fetched is not None
            if fetched and fetched.get("state") != "loaded":
                notes.append(
                    f"the entry is '{fetched.get('state')}'; check `ha core logs` "
                    "for why it did not load"
                )
    else:
        output["status"] = "saved" if kind == "options" else "reconfigured"
        output["changes"] = changes_from_forms(details.get("forms") or [])
        try:
            verified, checked = read_back(
                base,
                start_body,
                details.get("submitted") or [],
                details.get("forms") or [],
            )
        except (RuntimeError, KeyError, TypeError) as e:
            verified, checked = None, []
            notes.append(f"saved, but the read-back failed: {e}")
        else:
            if verified is None:
                notes.append(
                    "not read back: the reopened form does not pre-fill the "
                    "submitted fields"
                )
        output["verified"] = verified
        if checked:
            output["verified_fields"] = checked
        try:
            after = get_single(entry["entry_id"])
        except RuntimeError:
            after = None
        if after:
            output["entry"] = summary(after)
    if details.get("unused_steps"):
        notes.append(
            f"the flow finished with {details['unused_steps']} --step value(s) unused"
        )
    if notes:
        output["notes"] = notes
    print_output(output, args.format)
    if output.get("verified") is False:
        sys.exit(1)


def cmd_flow(args):
    """Run add/options/reconfigure; `schema` is the same run with nothing submitted."""
    schema = args.command == "schema"
    kind = args.flow if schema else args.command
    base, start_body, domain, entry = flow_target(kind, args.target)
    stamps = entry_stamps(domain, entry)
    t = translator(domain, "options" if kind == "options" else "config")
    with Flow(base, start_body) as flow:
        status, details = run_flow(flow, [] if schema else args.step or [], t)
    finish_flow(
        args,
        kind,
        status,
        details,
        base=base,
        start_body=start_body,
        domain=domain,
        entry=entry,
        stamps=stamps,
        schema=schema,
    )


# ── read-only commands ──────────────────────────────────────────────────────


def cmd_list(args):
    entries = all_entries()
    total = len(entries)
    if args.domain:
        entries = [e for e in entries if e["domain"] == args.domain.lower()]
    if args.search:
        needle = args.search.lower()
        entries = [
            e
            for e in entries
            if needle in e["domain"].lower() or needle in (e.get("title") or "").lower()
        ]
    if args.state:
        entries = [e for e in entries if e.get("state") == args.state.lower()]
    if args.failing:
        entries = [e for e in entries if e.get("state") in FAILING_STATES]
    entries.sort(key=lambda e: (e["domain"], (e.get("title") or "").lower()))
    print_output(
        {
            "total": total,
            "returned": len(entries),
            "entries": [summary(e) for e in entries],
        },
        args.format,
    )


def cmd_show(args):
    entry = resolve_entry(args.entry)
    devices, entities = owned_items(entry["entry_id"])
    output = summary(entry)
    output.update(
        {
            "created_at": iso(entry.get("created_at")),
            "modified_at": iso(entry.get("modified_at")),
            "polling": not entry.get("pref_disable_polling"),
            "add_new_entities": not entry.get("pref_disable_new_entities"),
            "devices": devices,
            "entities": entities,
        }
    )
    if entry.get("num_subentries"):
        output["subentries"] = (
            ha_result(
                {
                    "type": "config_entries/subentries/list",
                    "entry_id": entry["entry_id"],
                }
            )
            or []
        )
    print_output(without_none(output), args.format)


def cmd_handlers(args):
    kind = "helper" if args.helpers else "integration"
    handlers = ha_http("GET", f"/api/config/config_entries/flow_handlers?type={kind}")
    handlers = sorted(handlers or [])
    if args.search:
        handlers = [h for h in handlers if args.search.lower() in h]
    print_output(
        {
            "type": kind,
            "count": len(handlers),
            "handlers": handlers,
            "note": "domains that can be set up with `ha-integrations add`; "
            "integrations configured only in YAML are not listed",
        },
        args.format,
    )


def cmd_discovered(args):
    flows = ha_result({"type": "config_entries/flow/progress"}) or []
    out = []
    for f in flows:
        context = f.get("context") or {}
        placeholders = context.get("title_placeholders") or {}
        out.append(
            without_none(
                {
                    "domain": f.get("handler"),
                    "name": placeholders.get("name"),
                    "source": context.get("source"),
                    "step_id": f.get("step_id"),
                    "flow_id": f.get("flow_id"),
                }
            )
        )
    print_output(
        {
            "count": len(out),
            "flows": out,
            "note": "discovered devices waiting in Settings → Devices & services. "
            "Set one up with `ha-integrations add <domain>` and the details it asks "
            "for, or confirm it in the UI",
        },
        args.format,
    )


# ── entry mutations ─────────────────────────────────────────────────────────


def cmd_update(args):
    entry = resolve_entry(args.entry)
    wanted = {}
    if args.title is not None:
        wanted["title"] = args.title
    if args.polling is not None:
        wanted["pref_disable_polling"] = not args.polling
    if args.new_entities is not None:
        wanted["pref_disable_new_entities"] = not args.new_entities
    if not wanted:
        raise RuntimeError("nothing to change: pass at least one of the update flags")

    changes = {
        field: {"before": entry.get(field), "after": value}
        for field, value in wanted.items()
        if entry.get(field) != value
    }
    output = {"entry": summary(entry), "changes": changes}
    if not changes:
        output["note"] = "already set; nothing to do"
        print_output(output, args.format)
        return
    if args.dry_run:
        output["dry_run"] = True
        print_output(output, args.format)
        return

    result = ha_result(
        {
            "type": "config_entries/update",
            "entry_id": entry["entry_id"],
            **{f: wanted[f] for f in changes},
        }
    )
    after = (result or {}).get("config_entry") or {}
    mismatched = [f for f in changes if after.get(f) != wanted[f]]
    output["entry"] = summary(after or entry)
    output["verified"] = not mismatched
    notes = []
    if (result or {}).get("require_restart"):
        notes.append("Home Assistant needs a restart for this to take effect")
    if mismatched:
        notes.append(f"read-back differs for: {', '.join(mismatched)}")
    if notes:
        output["notes"] = notes
    print_output(output, args.format)
    if mismatched:
        sys.exit(1)


def set_disabled(args, disable):
    entry = resolve_entry(args.entry)
    wanted = "user" if disable else None
    output = {"entry": summary(entry)}
    if entry.get("disabled_by") == wanted:
        output["note"] = (
            f"already {'disabled' if disable else 'enabled'}; nothing to do"
        )
        print_output(output, args.format)
        return
    if disable:
        devices, entities = owned_items(entry["entry_id"])
        output["affects"] = {"devices": len(devices), "entities": entities}
        if getattr(args, "dry_run", False):
            output["dry_run"] = True
            output["note"] = "disabling unloads the integration; these entities go away"
            print_output(output, args.format)
            return

    result = ha_result(
        {
            "type": "config_entries/disable",
            "entry_id": entry["entry_id"],
            "disabled_by": wanted,
        }
    )
    after = get_single(entry["entry_id"]) or {}
    output["entry"] = summary(after or entry)
    output["verified"] = after.get("disabled_by") == wanted
    notes = []
    if (result or {}).get("require_restart"):
        notes.append("Home Assistant needs a restart for this to take full effect")
    if not disable and after.get("state") not in (None, "loaded"):
        notes.append(
            f"enabled but '{after.get('state')}'; check `ha core logs` for why"
        )
    if notes:
        output["notes"] = notes
    print_output(output, args.format)
    if not output["verified"]:
        sys.exit(1)


def cmd_disable(args):
    set_disabled(args, True)


def cmd_enable(args):
    set_disabled(args, False)


def cmd_reload(args):
    entry = resolve_entry(args.entry)
    try:
        result = ha_http(
            "POST", f"/api/config/config_entries/entry/{entry['entry_id']}/reload"
        )
    except HAHTTPError as e:
        if e.status == 403:
            raise RuntimeError(
                f"{entry['domain']} cannot be reloaded while running; "
                "it needs `ha core restart`"
            ) from None
        raise
    after = get_single(entry["entry_id"]) or entry
    output = {"entry": summary(after)}
    notes = []
    if (result or {}).get("require_restart"):
        notes.append("Home Assistant needs a restart to finish the reload")
    if after.get("state") != "loaded" and not after.get("disabled_by"):
        notes.append(f"reloaded but '{after.get('state')}'; check `ha core logs`")
    if notes:
        output["notes"] = notes
    print_output(output, args.format)


def cmd_delete(args):
    entry = resolve_entry(args.entry)
    devices, entities = owned_items(entry["entry_id"])
    output = {
        "entry": summary(entry),
        "removes": {"devices": devices, "entities": entities},
    }
    if args.dry_run:
        output["dry_run"] = True
        output["note"] = (
            "deleting removes these devices and entities from Home Assistant. "
            "Check what still uses them with `ha-entities refs <entity> --device`"
        )
        print_output(output, args.format)
        return

    result = ha_http("DELETE", f"/api/config/config_entries/entry/{entry['entry_id']}")
    output["verified"] = get_single(entry["entry_id"]) is None
    notes = []
    if (result or {}).get("require_restart"):
        notes.append("Home Assistant needs a restart to finish removing it")
    if entities:
        notes.append(
            "automations, scripts and dashboards that used these entities now "
            "point at nothing; Home Assistant does not rewrite them"
        )
    if notes:
        output["notes"] = notes
    print_output(output, args.format)
    if not output["verified"]:
        sys.exit(1)


# ── cli ─────────────────────────────────────────────────────────────────────


def main():
    step_parent = argparse.ArgumentParser(add_help=False)
    step_parent.add_argument(
        "--step",
        action="append",
        metavar="INPUT",
        help="Input for the next flow step, in order: a JSON object for a form, "
        "an option id for a menu. Repeat once per step",
    )

    parser = argparse.ArgumentParser(
        prog="ha-integrations",
        description="Inspect, add, configure and remove Home Assistant integrations.",
    )
    sub = parser.add_subparsers(dest="command", metavar="command", required=True)

    p = sub.add_parser("list", parents=[FORMAT_PARENT], help="List integration entries")
    p.add_argument("--domain", help="Only entries of this integration domain")
    p.add_argument("--search", metavar="TEXT", help="Substring of domain or title")
    p.add_argument("--state", help="Only entries in this state (e.g. loaded)")
    p.add_argument(
        "--failing",
        action="store_true",
        help="Only entries that failed to set up, retry, or failed to unload",
    )
    p.set_defaults(func=cmd_list)

    p = sub.add_parser(
        "show", parents=[FORMAT_PARENT], help="One entry with its devices and entities"
    )
    p.add_argument("entry")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser(
        "handlers",
        parents=[FORMAT_PARENT],
        help="Domains that can be added with a config flow",
    )
    p.add_argument("--search", metavar="TEXT")
    p.add_argument("--helpers", action="store_true", help="List helper flows instead")
    p.set_defaults(func=cmd_handlers)

    p = sub.add_parser(
        "discovered",
        parents=[FORMAT_PARENT],
        help="Discovered devices and flows waiting to be set up",
    )
    p.set_defaults(func=cmd_discovered)

    p = sub.add_parser(
        "schema",
        parents=[FORMAT_PARENT],
        help="Show a flow's first step without submitting anything",
    )
    p.add_argument("flow", choices=["add", "options", "reconfigure"])
    p.add_argument("target", metavar="domain|entry")
    p.set_defaults(func=cmd_flow)

    for name, target, text in (
        ("add", "domain", "Set up a new integration entry through its config flow"),
        ("options", "entry", "Change an entry's options through its options flow"),
        ("reconfigure", "entry", "Change an entry's setup data (host, credentials)"),
    ):
        p = sub.add_parser(name, parents=[FORMAT_PARENT, step_parent], help=text)
        p.add_argument("target", metavar=target)
        p.set_defaults(func=cmd_flow)

    p = sub.add_parser(
        "update",
        parents=[FORMAT_PARENT],
        help="Rename an entry or change its polling / new-entity preferences",
    )
    p.add_argument("entry")
    p.add_argument("--title", help="New title")
    p.add_argument(
        "--polling",
        action=argparse.BooleanOptionalAction,
        help="Enable/disable polling",
    )
    p.add_argument(
        "--new-entities",
        action=argparse.BooleanOptionalAction,
        help="Add new entities enabled/disabled",
    )
    p.add_argument("--dry-run", action="store_true", help="Show without applying")
    p.set_defaults(func=cmd_update)

    p = sub.add_parser(
        "disable", parents=[FORMAT_PARENT], help="Disable an entry (unloads it)"
    )
    p.add_argument("entry")
    p.add_argument(
        "--dry-run", action="store_true", help="Only list what would go away"
    )
    p.set_defaults(func=cmd_disable)

    p = sub.add_parser(
        "enable", parents=[FORMAT_PARENT], help="Enable a disabled entry"
    )
    p.add_argument("entry")
    p.set_defaults(func=cmd_enable)

    p = sub.add_parser("reload", parents=[FORMAT_PARENT], help="Reload an entry")
    p.add_argument("entry")
    p.set_defaults(func=cmd_reload)

    p = sub.add_parser(
        "delete",
        parents=[FORMAT_PARENT],
        help="Delete an entry with its devices and entities",
    )
    p.add_argument("entry")
    p.add_argument(
        "--dry-run", action="store_true", help="Only list what would be removed"
    )
    p.set_defaults(func=cmd_delete)

    run_cli(parser, (KeyError, TypeError))


if __name__ == "__main__":
    main()
