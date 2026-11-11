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

# Line continuations join, as in bash (the table cannot hold a newline)
check ask '[ha apps \⏎ uninstall x]' "$(bash_payload $'ha apps \\\n  uninstall core_mosquitto')"
check ask '[ha --raw-json \⏎ apps rm x]' "$(bash_payload $'ha --raw-json \\\n  apps rm core_mosquitto')"
check ask '[ha-integrations \⏎ delete x]' "$(bash_payload $'ha-integrations \\\n  delete hue')"
check pass '[ha core logs \⏎ -n 50]' "$(bash_payload $'ha core logs \\\n  -n 50')"
# Bash does not continue a comment line or an escaped backslash at line end
check ask '[comment ending in \ then ha-integrations delete]' "$(bash_payload $'ha apps logs x -n 5 \\\n  # tail only \\\nha-integrations delete hue')"
check ask '[echo C:\\ then ha core restart]' "$(bash_payload $'echo C:\\\\\nha core restart')"
check ask '[echo C:\\ then ha-integrations delete]' "$(bash_payload $'echo C:\\\\\nha-integrations delete hue')"
# An apostrophe in a heredoc unbalances the quotes; with ha in it, ask
check ask '[heredoc apostrophe hides ha core restart]' "$(bash_payload $'cat > /share/notes.md <<EOF\nGabriel\'s lamp\nEOF\necho \'step #2\'; ha core restart')"
check pass '[Edit] /homeassistant/secrets.yaml' \
    "$(edit_payload /homeassistant/secrets.yaml)"
check pass '[unparseable stdin fails open]' 'not json'

finish
