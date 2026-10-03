"""Shared harness for the Python tool tests (stdlib only).

load_ha_lib() imports the real ha_lib, for testing the library itself.
load_tool() imports a tool from rootfs/usr/local/bin with a fake `ha_lib`
namespace: the test's fakes for the connection layer (ha_result, ha_http, ...)
plus the real, connection-free helpers (print_output, run_cli, ...). Every call
executes the tool afresh, so module-level caches never leak between tests.
run_tool() runs its main() the way the shell would and captures the outcome.
"""

import importlib.util
import io
import json
import os
import sys
import types
from contextlib import redirect_stdout

BIN = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "rootfs", "usr", "local", "bin"
)

# What the tools import from ha_lib that needs no connection
SHARED = (
    "FORMAT_PARENT",
    "json_or_str",
    "parse_pairs",
    "print_output",
    "run_cli",
)


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_ha_lib():
    """Load a fresh copy of the real rootfs/usr/local/bin/ha_lib.py."""
    if "yaml" not in sys.modules:
        try:
            import yaml  # noqa: F401
        except ImportError:
            # Every call in the tests uses --format json
            sys.modules["yaml"] = types.ModuleType("yaml")
    return _load("real_ha_lib", os.path.join(BIN, "ha_lib.py"))


def load_tool(name, **fakes):
    """Load rootfs/usr/local/bin/<name>.py with `fakes` as its ha_lib."""
    real = load_ha_lib()
    sys.modules["ha_lib"] = types.SimpleNamespace(
        **{n: getattr(real, n) for n in SHARED}, **fakes
    )
    return _load(name.replace("-", "_"), os.path.join(BIN, f"{name}.py"))


def run_tool(tool, prog, *argv):
    """Run tool.main() with argv plus --format json.

    Returns (exit_code, parsed_json_or_None, stderr).
    """
    out, err = io.StringIO(), io.StringIO()
    old_argv, old_err = sys.argv, sys.stderr
    sys.argv, sys.stderr = [prog, *argv, "--format", "json"], err
    code = 0
    try:
        with redirect_stdout(out):
            tool.main()
    except SystemExit as e:
        code = e.code or 0
    finally:
        sys.argv, sys.stderr = old_argv, old_err
    text = out.getvalue()
    return code, (json.loads(text) if text.strip() else None), err.getvalue()
