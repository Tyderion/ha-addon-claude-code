#!/usr/bin/env bash
# shellcheck shell=bash
# ==============================================================================
# PreToolUse[Bash] hook — confirm shell commands that touch sensitive files
#
# The permission rules in settings.json only see Claude's file tools. The same
# files are just as reachable from the shell (`printf >>`, `sed -i`, a python
# one-liner, `cd x && rm y`), and auto mode approves that as routine
# /homeassistant work. A hook "ask" forces the prompt in every mode that
# prompts at all, auto mode included.
#
#   secrets.yaml  any command that names it asks, read or write alike
#   .storage      Home Assistant's internal state. Reading it is routine (the
#                 registries answer a lot of questions), so a command that
#                 names it passes only when every part of it is a known
#                 read-only command and output is redirected nowhere but /tmp
#                 or /dev/null. Anything else asks: the user sees exactly what
#                 would touch HA's state. Known write tools are hard-blocked
#                 before this by guard-destructive.sh.
#
# A command that reaches a file without naming it (`grep -r password
# /homeassistant`) is not caught; this closes the common paths, not every path.
# Single-quoted text is dropped before parsing (it cannot run anything, and it
# is where jq filters put their `|` and `>`). Double-quoted text is kept, so a
# `$( )` or `>` in it counts, which errs on the side of asking.
#
# Contract: print a PreToolUse "ask" decision and exit 0, or exit 0 silently
# to leave the decision to the permission rules. Fail-open on bad input.
# ==============================================================================
set -uo pipefail

# Commands that cannot write files (checked flags aside, see read_only)
readonly -a READ_COMMANDS=(
    cat head tail less more jq yq rg grep egrep fgrep ls find wc stat file
    diff cmp sort uniq cut column tr nl od hexdump strings md5sum sha1sum
    sha256sum du basename dirname realpath readlink cd pwd echo printf test
    '[' '[[' true false
)
# Leading words that run the next word as the command
readonly -a PREFIXES=(sudo command builtin time nice nohup env)

ask() {
    jq -nc --arg reason "$1" '{
        hookSpecificOutput: {
            hookEventName: "PreToolUse",
            permissionDecision: "ask",
            permissionDecisionReason: $reason
        }
    }'
    exit 0
}

# True if a single command (no separators) cannot write anything
read_only() {
    local -a words
    read -ra words <<< "$1"
    while ((${#words[@]})); do
        case ${words[0]} in
            *=*) words=("${words[@]:1}") ;;
            *)
                [[ " ${PREFIXES[*]} " == *" ${words[0]} "* ]] || break
                words=("${words[@]:1}")
                ;;
        esac
    done
    ((${#words[@]})) || return 0
    [[ " ${READ_COMMANDS[*]} " == *" ${words[0]} "* ]] || return 1
    case ${words[0]} in
        find) [[ " ${words[*]} " != *" -"@(delete|exec|execdir|ok|okdir|fprint|fprint0|fprintf|fls)" "* ]] ;;
        sort) [[ " ${words[*]} " != *" -o"* && " ${words[*]} " != *" --output"* ]] ;;
        *) return 0 ;;
    esac
}

# Prints the command with single-quoted strings replaced by Q, keeping
# backslash escapes and double-quoted text. Fails on an unterminated quote.
strip_single_quotes() {
    local s=$1 out='' c state=none i
    for ((i = 0; i < ${#s}; i++)); do
        c=${s:i:1}
        case ${state} in
            none)
                case ${c} in
                    "'") state=single out+=Q ;;
                    '"') state=double out+=${c} ;;
                    \\) out+=${c}${s:i+1:1} i=$((i + 1)) ;;
                    *) out+=${c} ;;
                esac
                ;;
            single) [[ ${c} == "'" ]] && state=none ;;
            double)
                case ${c} in
                    \\) out+=${c}${s:i+1:1} i=$((i + 1)) ;;
                    '"') state=none out+=${c} ;;
                    *) out+=${c} ;;
                esac
                ;;
        esac
    done
    [[ ${state} == none ]] || return 1
    printf '%s' "${out}"
}

# True if every output redirect goes to /dev/null, /tmp, or another descriptor
redirects_safe() {
    local rest=$1 target
    local re='[0-9&]?>>?[|]?[[:space:]]*([^[:space:];&|<>()]+)'
    while [[ ${rest} =~ ${re} ]]; do
        target=${BASH_REMATCH[1]}
        rest=${rest#*"${BASH_REMATCH[0]}"}
        case ${target} in
            /dev/null | /dev/stdout | /dev/stderr | /tmp/* | '&'[0-9] | [0-9]) ;;
            *) return 1 ;;
        esac
    done
}

input=$(cat) || exit 0
command -v jq > /dev/null 2>&1 || exit 0

cmd=$(printf '%s' "${input}" | jq -r 'select(.tool_name == "Bash") | .tool_input.command // empty' 2> /dev/null)
[[ -z ${cmd} ]] && exit 0

if [[ ${cmd} == *secrets.yaml* ]]; then
    ask "This shell command touches secrets.yaml, which holds your Home Assistant credentials."
fi

if [[ ${cmd} == *.storage* ]]; then
    shopt -s extglob
    bare=$(strip_single_quotes "${cmd}") \
        || ask "This shell command touches Home Assistant's .storage directory and could not be parsed."
    redirects_safe "${bare}" \
        || ask "This shell command may write into Home Assistant's .storage directory (its internal state)."
    # One command per line: split on ; & | newlines, $( ), backticks, ( )
    segments=$(printf '%s\n' "${bare}" | sed -E 's/\$\(|[;&|()`]/\n/g')
    while IFS= read -r segment; do
        [[ -z ${segment//[[:space:]]/} ]] && continue
        read_only "${segment}" \
            || ask "This shell command touches Home Assistant's .storage directory (its internal state) with something other than a read."
    done <<< "${segments}"
fi

exit 0
