#!/usr/bin/env bash
# shellcheck shell=bash
# ==============================================================================
# PreToolUse[Bash|Write|Edit|MultiEdit] hook — unconditional destructive guard
#
# The permission rules in settings.json are the day-to-day gate, but they are
# mode-dependent: `bypassPermissions` skips them entirely, and a user editing
# their persistent settings.json can drop a rule by accident. Hooks always run,
# whatever the mode, so this is the backstop that holds.
#
# It blocks only operations that are never legitimate from inside this add-on:
# recursive deletion of a mapped Home Assistant directory, filesystem and raw
# device writes, piping the network into a shell, and hand-editing HA's
# internal .storage. Everything merely *consequential* (core restart, host
# reboot, backup restore, addon uninstall) stays in the `ask` list, because
# those are things the user genuinely asks for.
#
# Contract: exit 0 allows, exit 2 blocks and hands the stderr text to the model.
# Fail-open on anything unexpected (unparseable stdin, missing jq) — a broken
# guard must not wedge the terminal.
# ==============================================================================
set -uo pipefail

# A recursive-and-forced rm, in any flag order, with or without a sudo prefix.
readonly RE_RM_FORCE='(^|[;&|(]|[[:space:]])(sudo[[:space:]]+)?rm[[:space:]]+((-[a-zA-Z]*[rR][a-zA-Z]*[[:space:]]+)?-[a-zA-Z]*f|(-[a-zA-Z]*f[a-zA-Z]*[[:space:]]+)?-[a-zA-Z]*[rR]|--recursive|--force|--no-preserve-root)'
# Targets that must never be handed to a recursive delete.
readonly RE_RM_ROOT="[[:space:]][\"']?(/|~|[$]HOME)(/?[*])?[\"']?[[:space:]]*([;&|]|$)"
readonly RE_RM_MAPPED="[[:space:]][\"']?/(homeassistant|config|share|data|addon_configs|addons|backup|media|ssl|root|etc|usr|bin|sbin|lib|var)(/?[*])?[\"']?[[:space:]]*([;&|]|$)"

readonly RE_MKFS='(^|[;&|(]|[[:space:]])(sudo[[:space:]]+)?mkfs'
readonly RE_DD_DEV='(^|[;&|(]|[[:space:]])(sudo[[:space:]]+)?dd[[:space:]][^;&|]*of=/dev/'
readonly RE_REDIR_DEV='>[[:space:]]*/dev/(sd|nvme|mmcblk|disk|hd)'
readonly RE_NET_PIPE='(curl|wget)[^;&|]*\|[[:space:]]*(sudo[[:space:]]+)?(ba|z|a|k)?sh([[:space:]]|$)'
readonly RE_STORAGE_CMD='(^|[;&|(]|[[:space:]])(tee|sed|dd|cp|mv|truncate|install|chmod|chown)[[:space:]][^;&|]*\.storage/'
readonly RE_STORAGE_REDIR='>[[:space:]]*[^;&|[:space:]]*\.storage/'

block() {
    printf 'BLOCKED by the add-on destructive guard: %s\n' "$1" >&2
    printf 'This is enforced by a hook and cannot be approved interactively. Use a different approach, or make the change through the Home Assistant UI.\n' >&2
    exit 2
}

input=$(cat) || exit 0
command -v jq > /dev/null 2>&1 || exit 0

tool=$(printf '%s' "${input}" | jq -r '.tool_name // empty' 2> /dev/null)

case "${tool}" in
    Write | Edit | MultiEdit)
        path=$(printf '%s' "${input}" | jq -r '.tool_input.file_path // empty' 2> /dev/null)
        [[ -z ${path} ]] && exit 0
        if [[ ${path} == */.storage/* || ${path} == */.storage ]]; then
            block "writing to Home Assistant's internal .storage directory (${path}). Dashboards go through ha-dashboard, everything else through the Home Assistant UI."
        fi
        exit 0
        ;;
    Bash) ;;
    *) exit 0 ;;
esac

cmd=$(printf '%s' "${input}" | jq -r '.tool_input.command // empty' 2> /dev/null)
[[ -z ${cmd} ]] && exit 0

# Collapse whitespace so a multi-line or oddly spaced command matches the same
# patterns as a one-liner. A trailing space lets the "end of argument" branches
# of the target patterns fire on the last word.
flat=$(printf '%s ' "${cmd}" | tr '\n\t' '  ' | tr -s ' ')

if [[ ${flat} =~ ${RE_RM_FORCE} ]]; then
    if [[ ${flat} =~ ${RE_RM_ROOT} ]]; then
        block "a recursive delete targeting the filesystem root or the home directory (${cmd})."
    fi
    if [[ ${flat} =~ ${RE_RM_MAPPED} ]]; then
        block "a recursive delete of a mapped Home Assistant directory (${cmd}). Delete individual files instead."
    fi
fi

if [[ ${flat} =~ ${RE_MKFS} ]]; then
    block "a mkfs invocation (${cmd}). This container shares the host's devices."
fi

if [[ ${flat} =~ ${RE_DD_DEV} ]]; then
    block "a dd write to a device node (${cmd})."
fi

if [[ ${flat} =~ ${RE_REDIR_DEV} ]]; then
    block "a redirect onto a raw block device (${cmd})."
fi

if [[ ${flat} =~ ${RE_NET_PIPE} ]]; then
    block "piping downloaded content into a shell (${cmd}). Download it to a file, read it, then run it."
fi

if [[ ${flat} =~ ${RE_STORAGE_CMD} ]] || [[ ${flat} =~ ${RE_STORAGE_REDIR} ]]; then
    block "writing into Home Assistant's .storage directory from the shell (${cmd})."
fi

exit 0
