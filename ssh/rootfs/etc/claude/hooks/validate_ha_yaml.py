#!/usr/bin/env python3
"""PostToolUse[Write|Edit|MultiEdit] hook - validate edited Home Assistant YAML.

Reads the Claude Code hook payload on stdin. When the edited file is a YAML
file inside a Home Assistant directory, it is parsed with a loader that
tolerates HA's custom tags (``!secret``, ``!include*``, ``!input``) but
rejects duplicate mapping keys - the classic footgun where a second
``automation:`` block silently discards the first.

On failure the diagnosis is written to stderr and the hook exits 2, which is
how a PostToolUse hook hands feedback back to Claude. Anything else exits 0
and stays silent, so a valid edit costs nothing.

Style checks are deliberately out of scope: this catches breakage, not
formatting. Run ``yamllint`` for that.
"""

import json
import os
import sys
from collections.abc import Hashable

# Roots whose YAML is loaded by Home Assistant itself. Edits elsewhere
# (/share scratch files, add-on configs) are none of this hook's business.
WATCHED_ROOTS = ("/homeassistant", "/config")

# Internal HA storage is JSON-with-a-.storage-path and never hand-edited;
# custom_components ship their own vendored YAML we should not police.
SKIP_PARTS = (".storage", "node_modules", ".git")

MAX_BYTES = 4 * 1024 * 1024


def _load_payload() -> dict:
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return {}


def _target_path(payload: dict) -> str | None:
    tool_input = payload.get("tool_input") or {}
    path = tool_input.get("file_path") or tool_input.get("path")
    if not isinstance(path, str) or not path:
        return None

    path = os.path.abspath(path)
    if not path.endswith((".yaml", ".yml")):
        return None
    # Check both the literal and the resolved path: /homeassistant is itself a
    # bind mount, and a config dir reached through a symlink still counts.
    candidates = {path, os.path.realpath(path)}
    if not any(
        candidate == root or candidate.startswith(root + "/")
        for candidate in candidates
        for root in WATCHED_ROOTS
    ):
        return None
    if any(part in SKIP_PARTS for part in path.split(os.sep)):
        return None
    if not os.path.isfile(path) or os.path.getsize(path) > MAX_BYTES:
        return None
    return path


def _build_loader(yaml):
    """SafeLoader that ignores HA tags and rejects duplicate keys."""

    class HomeAssistantLoader(yaml.SafeLoader):
        def construct_mapping(self, node, deep=False):
            seen: set = set()
            for key_node, _value_node in node.value:
                key = self.construct_object(key_node, deep=deep)
                if not isinstance(key, Hashable):
                    continue
                if key in seen:
                    raise yaml.constructor.ConstructorError(
                        "while constructing a mapping",
                        node.start_mark,
                        f"found duplicate key {key!r} - the later one wins and "
                        "the earlier block is silently discarded",
                        key_node.start_mark,
                    )
                seen.add(key)
            return super().construct_mapping(node, deep)

    # Every HA tag starts with "!" - swallow them all rather than keeping a
    # list that goes stale as integrations add their own.
    HomeAssistantLoader.add_multi_constructor("!", lambda *_args: None)
    return HomeAssistantLoader


def main() -> int:
    payload = _load_payload()
    path = _target_path(payload)
    if path is None:
        return 0

    try:
        import yaml
    except ImportError:
        return 0

    loader = _build_loader(yaml)
    try:
        with open(path, encoding="utf-8") as handle:
            for _document in yaml.load_all(handle, Loader=loader):
                pass
    except UnicodeDecodeError:
        return 0
    except yaml.MarkedYAMLError as err:
        where = ""
        if err.problem_mark is not None:
            where = (
                f" at line {err.problem_mark.line + 1}, "
                f"column {err.problem_mark.column + 1}"
            )
        print(
            f"YAML validation failed for {path}{where}:\n"
            f"  {err.problem or err}\n"
            f"  {err.context or ''}\n"
            "Fix the file before reloading or restarting Home Assistant.",
            file=sys.stderr,
        )
        return 2
    except yaml.YAMLError as err:
        print(f"YAML validation failed for {path}:\n  {err}", file=sys.stderr)
        return 2
    except OSError:
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
