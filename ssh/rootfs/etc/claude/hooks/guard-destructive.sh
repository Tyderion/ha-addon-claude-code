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
# those are things the user genuinely asks for. Reading .storage (`sed -n`,
# `cp` out of it) is not blocked; ask-sensitive.sh asks for anything there
# that is not a known read.
#
# The command is read with backslash-newline continuations joined and fd
# duplications (`2>&1`, `>&2`) dropped, then split into one segment per
# command. A relative rm target that means "this directory" (`.`, `*`, `./*`)
# is resolved against the payload's `.cwd`, or a preceding `cd` to an absolute
# or home path in the same command.
#
# Contract: exit 0 allows, exit 2 blocks and hands the stderr text to the model.
# Fail-open on anything unexpected (unparseable stdin, missing jq) — a broken
# guard must not wedge the terminal.
# ==============================================================================
set -uo pipefail

# Mapped directories that must never be handed to a recursive or forced rm.
# The filesystem root and the home directory are checked in check_rm.
readonly -a RM_MAPPED_TARGETS=(
    /homeassistant /config /share /data /addon_configs /addons /backup /media
    /ssl /root /etc /usr /bin /sbin /lib /var
)

readonly RE_MKFS='(^|[;&|(]|[[:space:]])(sudo[[:space:]]+)?mkfs'
readonly RE_DD_DEV='(^|[;&|(]|[[:space:]])(sudo[[:space:]]+)?dd[[:space:]][^;&|]*of=/dev/'
readonly RE_REDIR_DEV='>[[:space:]]*/dev/(sd|nvme|mmcblk|disk|hd)'
readonly RE_NET_PIPE='(curl|wget)[^;&|]*\|[[:space:]]*(sudo[[:space:]]+)?(ba|z|a|k)?sh([[:space:]]|$)'
# Write tools that block whenever .storage follows them; sed, cp and install
# are checked per segment in check_storage_write
readonly RE_STORAGE_CMD='(^|[;&|(]|[[:space:]])(tee|dd|mv|truncate|chmod|chown)[[:space:]][^;&|]*\.storage/'
readonly RE_STORAGE_REDIR='>[|&]?[[:space:]]*[^;&|[:space:]]*\.storage/'
# A redirect word: operator plus an attached target, if any
readonly RE_REDIR_WORD='^[0-9]*[<>]+[|]?(.*)$'

block() {
    printf 'BLOCKED by the add-on destructive guard: %s\n' "$1" >&2
    printf 'This is enforced by a hook and cannot be approved interactively. Use a different approach, or make the change through the Home Assistant UI.\n' >&2
    exit 2
}

# check_rm SEGMENT DIR: block if SEGMENT (one command, no separators) runs rm,
# bare, by path or as `\rm`, after any prefix (sudo, command, xargs, ...),
# with a recursive or force flag anywhere before `--`, and any of its own
# operands is a protected target. Only the words after `rm` count, so
# `cd ~ && rm -rf x` and `rm -rf /tmp/x && ls /` are left alone. Operands are
# compared with every quote character, a trailing `/*` and trailing slashes
# stripped, so `/`, `/*`, `"/"` and `//` all reduce to "", `/share/` and
# `"/share"/` to `/share`. An operand meaning the current directory or its
# contents (`.`, `*`, `./*`, `.*`) becomes DIR when DIR is known; any other
# relative operand is left alone.
check_rm() {
    local -a words
    local i w flagged=0 opts=1 dir=$2
    read -ra words <<< "$1"
    for ((i = 0; i < ${#words[@]}; i++)); do
        w=${words[i]//[\"\'\\]/}
        [[ ${w} == rm || ${w} == */rm ]] && break
    done
    ((i < ${#words[@]})) || return 0

    local -a operands=()
    for w in "${words[@]:i+1}"; do
        if ((opts)) && [[ ${w} == -?* ]]; then
            case ${w} in
                --) opts=0 ;;
                --recursive | --force | --no-preserve-root) flagged=1 ;;
                --*) ;;
                *[rRf]*) flagged=1 ;;
            esac
            continue
        fi
        operands+=("${w}")
    done
    ((flagged)) || return 0

    for w in "${operands[@]}"; do
        w=${w//[\"\']/}
        case ${w} in
            . | ./ | '*' | './*' | '.*' | './.*') [[ -n ${dir} ]] && w=${dir} ;;
        esac
        [[ ${w} == */\* ]] && w=${w%\*}
        while [[ ${w} == */ ]]; do w=${w%/}; done
        # shellcheck disable=SC2016 # literal $HOME, as typed in the command
        case ${w} in
            '' | '~' | '$HOME' | '${HOME}')
                block "a recursive delete targeting the filesystem root or the home directory (${cmd})."
                ;;
        esac
        if [[ " ${RM_MAPPED_TARGETS[*]} " == *" ${w} "* ]]; then
            block "a recursive delete of a mapped Home Assistant directory (${cmd}). Delete individual files instead."
        fi
    done
}

# True if WORD (quotes already removed) is a path into or onto .storage
is_storage() {
    [[ $1 == *.storage || $1 == *.storage/* ]]
}

# check_storage_write SEGMENT: block if SEGMENT edits .storage in place with
# sed (-i, -i.bak, --in-place, or a short-flag cluster with i such as -Ei)
# or copies into it with cp or install, meaning a .storage path is the
# destination: the -t/--target-directory value, else the last operand (every
# operand for install -d). Redirects and their targets are not operands.
# Reads pass: `sed -n 1p .storage/x`, `cp .storage/x /tmp/`.
check_storage_write() {
    local -a words args operands=() dests=()
    local i j w c tool='' target='' inplace=0 dirs=0 opts=1
    read -ra words <<< "$1"
    for ((i = 0; i < ${#words[@]}; i++)); do
        w=${words[i]//[\"\'\\]/}
        case ${w##*/} in
            sed | cp | install)
                tool=${w##*/}
                break
                ;;
        esac
    done
    [[ -n ${tool} ]] || return 0

    args=("${words[@]:i+1}")
    for ((i = 0; i < ${#args[@]}; i++)); do
        w=${args[i]//[\"\']/}
        if [[ ${w} =~ ${RE_REDIR_WORD} ]]; then
            [[ -z ${BASH_REMATCH[1]} ]] && i=$((i + 1))
            continue
        fi
        if ! ((opts)) || [[ ${w} != -?* ]]; then
            operands+=("${w}")
            continue
        fi
        case ${w} in
            --) opts=0 ;;
            --in-place*) inplace=1 ;;
            --target-directory=*) target=${w#*=} ;;
            --target-directory)
                i=$((i + 1))
                w=${args[i]-}
                target=${w//[\"\']/}
                ;;
            --directory) dirs=1 ;;
            --*) ;;
            *)
                # A short-flag cluster. sed: i (the rest is its suffix).
                # cp/install: install's d, and t, S, m, o, g, which take a
                # value, attached or as the next word.
                for ((j = 1; j < ${#w}; j++)); do
                    c=${w:j:1}
                    if [[ ${tool} == sed ]]; then
                        [[ ${c} == i ]] && inplace=1 && break
                        continue
                    fi
                    [[ ${tool} == install && ${c} == d ]] && dirs=1
                    [[ ${c} == [tSmog] ]] || continue
                    if ((j + 1 < ${#w})); then
                        [[ ${c} == t ]] && target=${w:j+1}
                    else
                        i=$((i + 1))
                        w=${args[i]-}
                        [[ ${c} == t ]] && target=${w//[\"\']/}
                    fi
                    break
                done
                ;;
        esac
    done

    case ${tool} in
        sed) ((inplace)) && dests=("${operands[@]}") ;;
        *)
            if [[ -n ${target} ]]; then
                dests=("${target}")
            elif ((dirs)); then
                dests=("${operands[@]}")
            elif ((${#operands[@]})); then
                dests=("${operands[-1]}")
            fi
            ;;
    esac
    for w in "${dests[@]}"; do
        is_storage "${w}" \
            && block "writing into Home Assistant's .storage directory from the shell (${cmd})."
    done
    return 0
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
dir=$(printf '%s' "${input}" | jq -r '.cwd // empty' 2> /dev/null)

# Join line continuations, drop fd duplications (2>&1, >&2, <&3, >&-) and
# turn the both-streams forms (&>, >&FILE) into a plain `>`, so a `&` left
# over is a real separator and a redirect keeps its target
normalized=$(printf '%s' "${cmd//$'\\\n'/ }" | sed -E 's/[0-9]*[<>]&[[:space:]]*[0-9-]+//g; s/&>/>/g; s/>&/>/g')

# Collapse whitespace so a multi-line or oddly spaced command matches the same
# patterns as a one-liner. A trailing space lets patterns that end on
# whitespace fire on the last word.
flat=$(printf '%s ' "${normalized}" | tr '\n\t' '  ' | tr -s ' ')

# One check per command: split on ; & | ( ) newlines and backticks. A `cd`
# moves the directory that `.`/`*` operands resolve to; one whose target is
# not absolute or home-based makes it unknown.
while IFS= read -r segment; do
    read -ra words <<< "${segment}"
    if [[ ${words[0]-} == cd ]]; then
        target=${words[1]-}
        target=${target//[\"\']/}
        # shellcheck disable=SC2016 # literal $HOME, as typed in the command
        case ${target} in
            '' | '~' | '$HOME' | '${HOME}') dir='~' ;;
            /* | \~/*) dir=${target} ;;
            *) dir='' ;;
        esac
        continue
    fi
    check_rm "${segment}" "${dir}"
    check_storage_write "${segment}"
done < <(printf '%s\n' "${normalized}" | sed -E 's/[;&|()`]/\n/g')

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
