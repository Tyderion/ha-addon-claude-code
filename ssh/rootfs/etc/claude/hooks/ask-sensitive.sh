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
#   ha-entities rename
#                 changing an entity_id breaks every automation, script and
#                 dashboard that still uses the old one
#   ha-integrations delete / disable
#                 removing or unloading an integration takes its devices and
#                 entities with it
#                 Each asks unless that command segment is a --dry-run (which
#                 only reports what would change; one inside a `#` comment
#                 does not count). A permission rule could
#                 not tell the two apart. The tool is found anywhere in a
#                 segment, quotes removed, so loops, xargs, `timeout`,
#                 `bash -c "..."` and path or python3 forms all count.
#   ha-secrets get / add
#                 get prints a secret's value; add stores a literal value the
#                 user should see first. Found the same way, but with no
#                 --dry-run exemption. The other ha-secrets commands never
#                 show a value (webhook prints only the id it just generated)
#                 and pass.
#   ha-dashboard delete
#                 permanent; only a `get` backup restores it. No dry-run
#                 exemption (the tool has none). `set` stays prompt-free,
#                 since editing dashboards is routine and the skill backs up
#                 first.
#   ha-service --unsafe
#                 the services ha-service refuses without the flag (Core
#                 restart/stop, hassio.*, recorder purges, shell_command.*).
#                 A permission rule cannot match a flag in the middle of a
#                 command, which is why the old `Bash(*--unsafe*)` rule never
#                 fired and was retired.
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
    cat head tail less more jq rg grep egrep fgrep ls find wc stat file
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

# Strips leading VAR=value assignments and wrapper commands (sudo, env, ...)
# from a single command and prints its words, one per line
command_words() {
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
    ((${#words[@]})) && printf '%s\n' "${words[@]}"
}

# True if a single command (no separators) cannot write anything. sort
# writes with -o (also inside a cluster such as -uo) or --output; uniq writes
# to its second operand, so it passes only with at most one non-flag word
# (option values such as `-f 1` count too, which errs on the side of asking).
read_only() {
    local -a words
    local w operands=0
    mapfile -t words < <(command_words "$1")
    ((${#words[@]})) || return 0
    [[ " ${READ_COMMANDS[*]} " == *" ${words[0]} "* ]] || return 1
    case ${words[0]} in
        find) [[ " ${words[*]} " != *" -"@(delete|exec|execdir|ok|okdir|fprint|fprint0|fprintf|fls)" "* ]] ;;
        sort)
            for w in "${words[@]:1}"; do
                [[ ${w} == --output* ]] && return 1
                [[ ${w} == -[!-]* && ${w} == *o* ]] && return 1
            done
            return 0
            ;;
        uniq)
            for w in "${words[@]:1}"; do
                [[ ${w} == -?* ]] || operands=$((operands + 1))
            done
            ((operands <= 1))
            ;;
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

# Prints the command without shell comments: an unquoted `#` that starts a
# word, up to the end of its line. Quoted text, backslash escapes and a `#`
# inside a word (`a#b`, `$#`, `${#x}`) are kept.
strip_comments() {
    local s=$1 out='' c prev=' ' state=none i
    local -r word_start=$' \t\n;&|()'
    for ((i = 0; i < ${#s}; i++)); do
        c=${s:i:1}
        case ${state} in
            comment)
                [[ ${c} == $'\n' ]] || continue
                state=none
                ;;
            none)
                case ${c} in
                    '#') [[ ${word_start} == *"${prev}"* ]] && state=comment && continue ;;
                    "'") state=single ;;
                    '"') state=double ;;
                    \\) c+=${s:i+1:1} i=$((i + 1)) ;;
                esac
                ;;
            single) [[ ${c} == "'" ]] && state=none ;;
            double)
                case ${c} in
                    \\) c+=${s:i+1:1} i=$((i + 1)) ;;
                    '"') state=none ;;
                esac
                ;;
        esac
        out+=${c}
        prev=${c}
        ((${#c} == 1)) || prev=x # an escaped character is never a word start
    done
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

[[ ${cmd} == *.storage* || ${cmd} == *ha-entities* || ${cmd} == *ha-integrations* || ${cmd} == *ha-secrets* || ${cmd} == *ha-service* || ${cmd} == *ha-dashboard* ]] || exit 0
shopt -s extglob
bare=$(strip_single_quotes "${cmd}") \
    || ask "This shell command could not be parsed, and it touches .storage, the entity registry, integrations, secrets or services."
# Drop fd duplications (2>&1, >&2, <&3, >&-) and turn the both-streams forms
# (&>, >&FILE) into a plain `>`, so the split below only sees real `&`
# separators and every file redirect keeps its target
bare=$(printf '%s' "${bare}" | sed -E 's/[0-9]*[<>]&[[:space:]]*[0-9-]+//g; s/&>/>/g; s/>&/>/g')
# One command per line: split on ; & | newlines, $( ), backticks, ( )
segments=$(printf '%s\n' "${bare}" | sed -E 's/\$\(|[;&|()`]/\n/g')

# Destructive tool subcommands. Comments go first, so a `# --dry-run` note
# cannot pass for the flag. Quotes are then dropped outright rather than
# stripped with their contents, so `bash -c "ha-integrations delete x"` and
# xargs/loop forms still show the tool and its subcommand as words.
loose=$(strip_comments "${cmd}" | tr -d "\"'" | sed -E 's/\$\(|[;&|()`]/\n/g')
while IFS= read -r segment; do
    read -ra words <<< "${segment}"
    reason=''
    for ((i = 0; i < ${#words[@]}; i++)); do
        tool=${words[i]##*/}
        case "${tool%.py} ${words[i + 1]-}" in
            'ha-entities rename')
                reason="Changing an entity_id breaks every automation, script and dashboard that still uses the old one."
                ;;
            'ha-integrations delete')
                reason="Deleting an integration removes its devices and entities; automations, scripts and dashboards that use them break."
                ;;
            'ha-integrations disable')
                reason="Disabling an integration unloads it; its entities stay unavailable until it is enabled again."
                ;;
            'ha-secrets get')
                ask "This prints a value from secrets.yaml, which holds your Home Assistant credentials."
                ;;
            'ha-secrets add')
                ask "This stores a new value in secrets.yaml, which holds your Home Assistant credentials."
                ;;
            'ha-dashboard delete')
                ask "Deleting a dashboard removes it and all its cards for good; only a backup taken with ha-dashboard get brings it back."
                ;;
        esac
        if [[ ${tool%.py} == ha-service && " ${words[*]} " == *" --unsafe "* ]]; then
            ask "This service call can restart or stop Home Assistant, run a shell command or purge recorded history."
        fi
    done
    [[ -z ${reason} || " ${words[*]} " == *" --dry-run "* ]] || ask "${reason}"
done <<< "${loose}"

if [[ ${cmd} == *.storage* ]]; then
    redirects_safe "${bare}" \
        || ask "This shell command may write into Home Assistant's .storage directory (its internal state)."
    while IFS= read -r segment; do
        [[ -z ${segment//[[:space:]]/} ]] && continue
        read_only "${segment}" \
            || ask "This shell command touches Home Assistant's .storage directory (its internal state) with something other than a read."
    done <<< "${segments}"
fi

exit 0
