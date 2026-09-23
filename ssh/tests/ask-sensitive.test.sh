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

failures=0
total=0

check() {
    local expect=$1 label=$2 payload=$3 out rc got
    total=$((total + 1))
    out=$(printf '%s' "${payload}" | bash "${HOOK}" 2> /dev/null)
    rc=$?
    got=pass
    if [[ -n ${out} ]]; then
        got=$(printf '%s' "${out}" | jq -r '.hookSpecificOutput.permissionDecision // "invalid"' 2> /dev/null)
    fi
    [[ ${rc} -ne 0 ]] && got="exit-${rc}"
    if [[ ${got} == "${expect}" ]]; then
        printf 'ok    %-6s %s\n' "${got}" "${label}"
    else
        printf 'FAIL  want=%-6s got=%-6s %s\n' "${expect}" "${got}" "${label}"
        failures=$((failures + 1))
    fi
}

while IFS=$'\t' read -r expect cmd; do
    [[ -z ${expect} || ${expect} == \#* ]] && continue
    check "${expect}" "${cmd}" "$(jq -nc --arg c "${cmd}" '{tool_name:"Bash",tool_input:{command:$c}}')"
done < "${CASES}"

check pass '[Edit] /homeassistant/secrets.yaml' \
    "$(jq -nc '{tool_name:"Edit",tool_input:{file_path:"/homeassistant/secrets.yaml"}}')"
check pass '[unparseable stdin fails open]' 'not json'

printf '\n%d/%d passed\n' "$((total - failures))" "${total}"
exit $((failures > 0))
