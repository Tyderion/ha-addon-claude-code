#!/usr/bin/env bash
# shellcheck shell=bash
# ==============================================================================
# PreToolUse[Bash] hook — normalise ha-* tool invocations to their PATH names
#
# Claude regularly reaches for a path form of the bundled CLI tools
# (`./ha-entities`, `/usr/local/bin/ha-service`, `python3 ha-state.py`).
# Every one of those misses the `Bash(ha-entities:*)` allow rules, so it
# either prompts the user or is denied outright, after which the model tends
# to fall back to hand-rolled `ha_lib` scripts instead of the real tool.
#
# This hook rewrites those forms back to the bare executable name before the
# permission layer sees them. Rewriting only happens in command position, so
# `cat /usr/local/bin/ha-entities.py` and `rg ha-state /homeassistant` are
# left alone.
#
# The matching `deny` rules in settings.json are kept as a backstop for the
# case where the running Claude Code build ignores `updatedInput`.
# ==============================================================================
set -uo pipefail

readonly TOOLS='ha-entities|ha-dashboard|ha-trace|ha-history|ha-template|ha-service|ha-state|ha-reload'

input=$(cat)

command=$(printf '%s' "${input}" | jq -r '.tool_input.command // empty' 2> /dev/null)
[[ -z ${command} ]] && exit 0

# Cheap bail-out: nothing to do unless a bundled tool name appears at all.
[[ ${command} == *ha-* ]] || exit 0

# Command position is the start of a line or the tail of a separator token
# (`;` `&` `&&` `|` `||` `(` `$(`). sed is line-based, so `^` covers newlines.
#   \1  separator            \2  leading whitespace
#   \3  interpreter prefix   \5  path prefix
#   \8  tool name            \9  .py suffix
rewritten=$(
    printf '%s' "${command}" | sed -E \
        "s#(^|[;&|(])([[:space:]]*)((python3?|bash|sh)[[:space:]]+)?((\.{0,2}/)([A-Za-z0-9_.-]+/)*\.?)?(${TOOLS})(\.py)?#\1\2\8#g"
)

[[ ${rewritten} == "${command}" ]] && exit 0

jq -n --arg cmd "${rewritten}" '{
    hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecisionReason:
            "Rewrote a path-form ha-* call to its PATH name; the bundled tools are always invoked bare.",
        updatedInput: { command: $cmd }
    }
}'
