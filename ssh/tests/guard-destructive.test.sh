#!/usr/bin/env bash
# shellcheck shell=bash
# ==============================================================================
# Table test for hooks/guard-destructive.sh
#
# Reads guard-destructive.cases.tsv (`expect<TAB>command`) and feeds each case
# to the hook as a PreToolUse[Bash] payload, with .cwd set when the case has
# a third column. `block` expects exit 2, `allow` expects exit 0. One-off
# cases below cover multi-line commands, which a TSV cell cannot hold, and the
# Write/Edit path.
#
# Run: bash ssh/tests/guard-destructive.test.sh
# ==============================================================================
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly HERE
readonly HOOK="${HERE}/../rootfs/etc/claude/hooks/guard-destructive.sh"
readonly CASES="${HERE}/guard-destructive.cases.tsv"

# Exit 2 is the hook's block signal; anything else lets the call through
classify() {
    [[ $1 -eq 2 ]] && echo block || echo allow
}

# shellcheck source=hook-table.sh
source "${HERE}/hook-table.sh"

run_table

# A backslash-newline continues the command; a bare newline separates two
check block '[continuation] rm -rf \⏎ /share' \
    "$(bash_payload $'rm -rf \\\n /share')"
check block '[continuation] rm -rf /tmp/a \⏎   /homeassistant' \
    "$(bash_payload $'rm -rf /tmp/a \\\n   /homeassistant')"
check allow '[newline] rm -rf /tmp/x⏎ls /' \
    "$(bash_payload $'rm -rf /tmp/x\nls /')"

check block '[Edit] /homeassistant/.storage/lovelace' \
    "$(edit_payload /homeassistant/.storage/lovelace)"
check allow '[Edit] /homeassistant/automations.yaml' \
    "$(edit_payload /homeassistant/automations.yaml)"
check allow '[unparseable stdin fails open]' 'not json'

finish
