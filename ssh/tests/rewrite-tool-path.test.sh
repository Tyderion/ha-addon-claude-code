#!/usr/bin/env bash
# shellcheck shell=bash
# ==============================================================================
# Table test for hooks/rewrite-ha-tool-path.sh
#
# Reads rewrite-tool-path.cases.tsv (`expect<TAB>command`) and feeds each case
# to the hook as a PreToolUse[Bash] payload. `expect` is the rewritten command
# the hook hands back in updatedInput, or `unchanged` when it stays silent.
#
# Run: bash ssh/tests/rewrite-tool-path.test.sh
# ==============================================================================
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly HERE
readonly HOOK="${HERE}/../rootfs/etc/claude/hooks/rewrite-ha-tool-path.sh"
readonly CASES="${HERE}/rewrite-tool-path.cases.tsv"

# Silent exit 0 is "unchanged"; otherwise the command from updatedInput
classify() {
    local rc=$1 out=$2 got=unchanged
    if [[ -n ${out} ]]; then
        got=$(printf '%s' "${out}" | jq -r '.hookSpecificOutput.updatedInput.command // "invalid"' 2> /dev/null)
    fi
    [[ ${rc} -ne 0 ]] && got="exit-${rc}"
    echo "${got}"
}

# shellcheck source=hook-table.sh
source "${HERE}/hook-table.sh"

run_table

check unchanged '[unparseable stdin fails open]' 'not json'

finish
