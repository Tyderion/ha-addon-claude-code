#!/usr/bin/env bash
# shellcheck shell=bash
# ==============================================================================
# Table test for hooks/ask-sensitive.sh
#
# Reads ask-sensitive.cases.tsv (`expect<TAB>command`) and feeds each case to
# the hook as a PreToolUse[Bash] payload. `ask` expects a permissionDecision
# of "ask" on stdout, `pass` expects no output; both expect exit 0. One extra
# case checks that a non-Bash tool is left to the permission rules.
#
# Run: bash ssh/tests/ask-sensitive.test.sh
# ==============================================================================
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly HERE
readonly HOOK="${HERE}/../rootfs/etc/claude/hooks/ask-sensitive.sh"
readonly CASES="${HERE}/ask-sensitive.cases.tsv"

# Silent exit 0 is "pass"; otherwise the hook's permissionDecision
classify() {
    local rc=$1 out=$2 got=pass
    if [[ -n ${out} ]]; then
        got=$(printf '%s' "${out}" | jq -r '.hookSpecificOutput.permissionDecision // "invalid"' 2> /dev/null)
    fi
    [[ ${rc} -ne 0 ]] && got="exit-${rc}"
    echo "${got}"
}

# shellcheck source=hook-table.sh
source "${HERE}/hook-table.sh"

run_table

check pass '[Edit] /homeassistant/secrets.yaml' \
    "$(edit_payload /homeassistant/secrets.yaml)"
check pass '[unparseable stdin fails open]' 'not json'

finish
