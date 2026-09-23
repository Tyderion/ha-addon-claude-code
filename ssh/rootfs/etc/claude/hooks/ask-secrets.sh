#!/usr/bin/env bash
# shellcheck shell=bash
# ==============================================================================
# PreToolUse[Bash] hook — confirm shell commands that touch secrets.yaml
#
# The `ask` rules in settings.json cover secrets.yaml for the Read and Edit
# tools only. Claude is just as likely to use the shell (`cat`, `printf >>`,
# `sed -i`, a python one-liner), and in auto mode the classifier approves that
# as routine /homeassistant work, so the ask rule never fires. A hook "ask"
# forces the prompt in every mode that prompts at all, auto mode included.
#
# Any Bash command that names a secrets.yaml file is sent to the user,
# read or write alike. A command that reaches the file without naming it
# (`grep -r password /homeassistant`) is not caught; this closes the common
# path, not every path.
#
# Contract: print a PreToolUse "ask" decision and exit 0, or exit 0 silently
# to leave the decision to the permission rules. Fail-open on bad input.
# ==============================================================================
set -uo pipefail

input=$(cat) || exit 0
command -v jq > /dev/null 2>&1 || exit 0

cmd=$(printf '%s' "${input}" | jq -r 'select(.tool_name == "Bash") | .tool_input.command // empty' 2> /dev/null)
[[ ${cmd} == *secrets.yaml* ]] || exit 0

jq -nc '{
    hookSpecificOutput: {
        hookEventName: "PreToolUse",
        permissionDecision: "ask",
        permissionDecisionReason: "This shell command touches secrets.yaml, which holds your Home Assistant credentials."
    }
}'
