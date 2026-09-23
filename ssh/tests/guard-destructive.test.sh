#!/usr/bin/env bash
# shellcheck shell=bash
# ==============================================================================
# Table test for hooks/guard-destructive.sh
#
# Reads guard-destructive.cases.tsv (`expect<TAB>command`) and feeds each case
# to the hook as a PreToolUse[Bash] payload. `block` expects exit 2, `allow`
# expects exit 0. Two extra cases cover the Write/Edit path.
#
# Run: bash ssh/tests/guard-destructive.test.sh
# ==============================================================================
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly HERE
readonly HOOK="${HERE}/../rootfs/etc/claude/hooks/guard-destructive.sh"
readonly CASES="${HERE}/guard-destructive.cases.tsv"

failures=0
total=0

check() {
    local expect=$1 label=$2 payload=$3 got rc
    total=$((total + 1))
    printf '%s' "${payload}" | bash "${HOOK}" > /dev/null 2>&1
    rc=$?
    got=allow
    [[ ${rc} -eq 2 ]] && got=block
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

check block '[Edit] /homeassistant/.storage/lovelace' \
    "$(jq -nc '{tool_name:"Edit",tool_input:{file_path:"/homeassistant/.storage/lovelace"}}')"
check allow '[Edit] /homeassistant/automations.yaml' \
    "$(jq -nc '{tool_name:"Edit",tool_input:{file_path:"/homeassistant/automations.yaml"}}')"
check allow '[unparseable stdin fails open]' 'not json'

printf '\n%d/%d passed\n' "$((total - failures))" "${total}"
exit $((failures > 0))
