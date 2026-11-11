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
#   ha-areas delete
#                 an area, floor or label leaves every device, entity and area
#                 that had it, and config that targets it stops doing anything
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
#                 restart/stop, hassio.*, recorder purges, shell_command.*,
#                 update.install). A permission rule cannot match a flag in the
#                 middle of a command, which is why the old `Bash(*--unsafe*)`
#                 rule never fired and was retired.
#   ha (the Supervisor CLI)
#                 settings.json allows `Bash(ha:*)`, and its literal ask rules
#                 match one spelling each, while the CLI takes dozens (`apps` is
#                 also `addons`/`addon`/`ad`, `uninstall` is also `rm`/`del`,
#                 `core` is also `ha`) and root flags anywhere (`ha --raw-json
#                 apps rm x`). So this is an allowlist: everything under `ha`
#                 asks except the reads and routine commands in HA_CLI_PASS,
#                 and a verb a later CLI adds asks until it is listed there.
#                 The `ha` word is found as a command, after wrappers (`sudo`,
#                 `timeout 5`, `bash -c`, `xargs`), with quotes and backslashes
#                 removed; as an argument to a text tool or an ha-* tool
#                 (`rg ha`, `ha-entities search ha`) it is data. Flags take the
#                 next word as their value the way cobra does. A word the table
#                 does not know, `$verb` included, asks; so does a `$HA`
#                 command word, unbalanced quotes, and a group under `xargs`
#                 that would take its verb from stdin. Not caught: `eval`, a copied or renamed binary, a text
#                 tool that runs commands (`awk 'system(...)'`), and python3
#                 posting to http://supervisor with SUPERVISOR_TOKEN.
#                 The container is the trust boundary; this guards the
#                 spellings a model actually types. settings.json keeps
#                 literal ask rules for the common spellings (`ha apps
#                 uninstall`, `ha core restart`, ...) for when this hook
#                 cannot run (no jq).
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

# The `ha` CLI commands that run without asking, from its cobra tree
# (github.com/home-assistant/cli, cmd/*.go): `kind path aliases...`. G is a
# group: descend into a listed child, pass when nothing follows, ask on any
# other word (a write verb, or one this table does not know yet). R is a read
# or routine command: the words after it are its arguments.
readonly HA_CLI_PASS='
R  info                     in inf
R  banner                   ba
R  available-updates        updates available_updates
R  refresh-updates          refresh refresh_updates
R  help
R  completion
G  apps                     app addons addon add-on add-ons ad
R  apps/info                in
R  apps/logs                log lg
R  apps/stats               status stat
R  apps/changelog           cl ch
R  apps/start               run st
G  audio                    snd sound
R  audio/info               in inf
R  audio/logs               log lg
R  audio/stats              status stat st
G  authentication           auth au
R  authentication/list      ls
G  backups                  backup back bk snapshots snapshot snap shot sn
R  backups/info             in inf
R  backups/new              create backup
R  backups/reload           refresh re
G  cli
R  cli/info                 in inf
R  cli/stats                status stat
G  core                     homeassistant home-assistant ha
R  core/check               validate chk ch
R  core/info                in inf
R  core/logs                log lg
R  core/stats               status stat st
R  core/start               run
G  dns
R  dns/info                 in inf
R  dns/logs                 log lg
R  dns/stats                status stat
G  docker                   do
R  docker/info              in inf
G  hardware                 hw
R  hardware/info            in inf
R  hardware/audio           sounds snd au
G  host                     ho
R  host/info                in inf
G  host/disks               disk
R  host/disks/usage         us use
R  host/logs                log lg
G  jobs                     job tasks task
R  jobs/info                in inf
G  mounts                   mount mnts mnt
R  mounts/info              in inf
G  multicast                mcast mc
R  multicast/info           in inf
R  multicast/logs           log lg
R  multicast/stats          status stat
G  network                  net
R  network/info             in inf
R  network/scan             accesspoints wifi
G  observer
R  observer/info            in inf
R  observer/stats           status stat
G  os                       hassos
R  os/info                  in inf
G  os/config                conf cfg
G  os/config/swap           sw
R  os/config/swap/info      in
G  os/datadisk              data
R  os/datadisk/list         in inf info show
G  resolution               resolutions res
R  resolution/info          in inf
R  resolution/healthcheck   evaluate run
G  resolution/issue         is trouble
R  resolution/issue/suggestions su solutions
G  security                 secure sec
R  security/info            in inf
G  store                    shop stor
R  store/reload             refresh re
G  supervisor               super su
R  supervisor/info          in inf
R  supervisor/logs          log lg
R  supervisor/stats         status stat st
R  supervisor/available-updates available_updates updates
R  supervisor/reload        refresh re
G  time                     ntp timedate
R  time/info                in inf
'
declare -A HA_CHILD=() HA_KIND=([root]=G)
while read -r k path aliases; do
    [[ -z ${k} ]] && continue
    parent=${path%/*}
    [[ ${parent} == "${path}" ]] && parent=root
    HA_KIND[${path}]=${k}
    for a in "${path##*/}" ${aliases}; do
        HA_CHILD["${parent} ${a}"]=${path}
    done
done <<< "${HA_CLI_PASS}"
# Flags of the `ha` CLI that take no value. Like cobra, any other flag written
# without `=` takes the next word as its value, wherever it stands.
readonly -a HA_BOOL_FLAGS=(--raw-json --no-progress --help -h --)
# Commands whose `ha` arguments are text, not a command to run
readonly -a TEXT_COMMANDS=(
    echo printf grep egrep fgrep rg cat head tail jq yq sed awk git wc sort
    uniq cut tr less more diff column test '[' '[['
)

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
                    '$') [[ ${s:i+1:1} == "'" ]] && state=ansi c+="'" i=$((i + 1)) ;;
                    "'") state=single ;;
                    '"') state=double ;;
                    \\)
                        # A line continuation joins the lines, as in bash
                        [[ ${s:i+1:1} == $'\n' ]] && i=$((i + 1)) && continue
                        c+=${s:i+1:1} i=$((i + 1))
                        ;;
                esac
                ;;
            single) [[ ${c} == "'" ]] && state=none ;;
            ansi) # $'...': a backslash escapes the next character, \' included
                case ${c} in
                    \\) c+=${s:i+1:1} i=$((i + 1)) ;;
                    "'") state=none ;;
                esac
                ;;
            double)
                case ${c} in
                    \\)
                        [[ ${s:i+1:1} == $'\n' ]] && i=$((i + 1)) && continue
                        c+=${s:i+1:1} i=$((i + 1))
                        ;;
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

# True if `$1` is a flag that takes the next word as its value
ha_value_flag() {
    [[ $1 == -* && $1 != *=* && " ${HA_BOOL_FLAGS[*]} " != *" $1 "* ]]
}

# True unless one command segment runs the `ha` CLI with anything outside
# HA_CLI_PASS. The segment has quotes and backslashes removed already.
ha_cli_passes() {
    local -a words
    local i w prev='' node=root fed=0
    read -ra words <<< "$1"
    # A command word from a variable could be ha (`$HA core restart`); the
    # caller only gets here when the command has an `ha` word somewhere
    for w in "${words[@]}"; do
        [[ ${w} == *=* || " ${PREFIXES[*]} " == *" ${w} "* ]] || break
    done
    [[ ${w-} == \$* && ${w} != '$SUBST' ]] && return 1
    for ((i = 0; i < ${#words[@]}; i++)); do
        w=${words[i]##*/}
        [[ ${w} == ha ]] && break
        w=${w%.py}
        # ha is an argument to a text tool or a bundled ha-* tool
        [[ " ${TEXT_COMMANDS[*]} " == *" ${w} "* || ${w} == ha-* ]] && return 0
        # These append words from stdin, so a group may get its verb there
        # (`echo restart | xargs ha core`)
        [[ ${w} == xargs || ${w} == parallel ]] && fed=1
    done
    ((i < ${#words[@]})) || return 0
    # Help before `--` prints help and runs nothing, unless it is a flag's value
    for w in "${words[@]:i+1}"; do
        [[ ${w} == -- ]] && break
        [[ (${w} == --help || ${w} == -h) && -z ${prev} ]] && return 0
        prev=''
        ha_value_flag "${w}" && prev=${w}
    done

    for ((i = i + 1; i < ${#words[@]}; i++)); do
        w=${words[i]}
        [[ ${HA_KIND[${node}]} == R ]] && return 0
        # After `--` every word is an argument, never a command
        [[ ${w} == -- ]] && return 1
        # A redirect is not an argument: `2>/dev/null` goes, and a bare
        # `>` or `2>` takes the next word, its target, with it
        if [[ ${w} =~ ^[0-9]*[\<\>] ]]; then
            [[ ${w} =~ ^[0-9]*[\<\>]+\|?$ ]] && i=$((i + 1))
            continue
        fi
        if [[ ${w} == -* ]]; then
            ha_value_flag "${w}" && i=$((i + 1))
            continue
        fi
        # `list` is no verb, but models write `ha backups list`. Cobra stops at
        # the first word that is not a subcommand and hands the rest to the
        # group as arguments, which a group's own listing ignores (or it
        # prints help), so it is a read. Other unknown words still ask: they
        # may be verbs of a newer CLI.
        if [[ -z ${HA_CHILD["${node} ${w}"]-} && ${HA_KIND[${node}]} == G ]] \
            && [[ ${w} == list || ${w} == ls ]]; then
            return 0
        fi
        node=${HA_CHILD["${node} ${w}"]-}
        [[ -n ${node} ]] || return 1
    done
    [[ ${HA_KIND[${node}]} == R ]] || ((fed == 0))
}

input=$(cat) || exit 0
command -v jq > /dev/null 2>&1 || exit 0

cmd=$(printf '%s' "${input}" | jq -r 'select(.tool_name == "Bash") | .tool_input.command // empty' 2> /dev/null)
[[ -z ${cmd} ]] && exit 0
# For substring tests only: line continuations joined and quotes and
# backslashes dropped, so `ha-integr\ations` and `secrets.y''aml` still show
# the name bash runs. Joining can merge commands bash keeps apart (after a
# comment or `\\`), so never parse this
plain=$(printf '%s' "${cmd//$'\\\n'/}" | tr -d "\"'\\\\")

if [[ ${plain} == *secrets.yaml* ]]; then
    ask "This shell command touches secrets.yaml, which holds your Home Assistant credentials."
fi

# One command per line, for the tool checks below. Comments go first, so a
# `# --dry-run` note cannot pass for the flag. Quotes and backslashes are then
# dropped outright rather than stripped with their contents, so
# `bash -c "ha-integrations delete x"`, `ap\ps` and xargs/loop forms still
# show the tool and its subcommand as words. A command substitution leaves the
# word $SUBST behind, so `ha core $(echo restart)` does not end at `ha core`.
# fd duplications (2>&1, >&2) go and both-streams forms (&>, >&FILE) become
# `>` before the split, so their `&` cannot cut `ha backups 2>&1 restore x`
# into a harmless `ha backups` and a separate `1 restore x`.
loose_segments() {
    strip_comments "$1" | tr -d "\"'\\\\" \
        | sed -E 's/[0-9]*[<>]&[[:space:]]*[0-9-]+//g; s/&>/>/g; s/>&/>/g' \
        | sed -E 's/\$\(|`/ $SUBST\n/g; s/[;&|()]/\n/g'
}
loose=''

# strip_comments is slow on big heredocs, so only a command with an `ha` word
# in it is split for this check
ha_word='(^|[^[:alnum:]_.-])ha($|[^[:alnum:]_.-])'
if [[ ${plain} =~ ${ha_word} ]]; then
    strip_single_quotes "${cmd}" > /dev/null \
        || ask "This shell command runs or mentions the ha CLI, and its quotes could not be parsed."
    loose=$(loose_segments "${cmd}")
    while IFS= read -r segment; do
        ha_cli_passes "${segment}" \
            || ask "This ha command can change Home Assistant itself (restart, stop, update, remove or reconfigure apps, Core, the OS, backups or the Supervisor). Only reads and a few routine commands run without asking."
    done <<< "${loose}"
fi

[[ ${plain} == *.storage* || ${plain} == *ha-entities* || ${plain} == *ha-integrations* || ${plain} == *ha-secrets* || ${plain} == *ha-service* || ${plain} == *ha-dashboard* || ${plain} == *ha-areas* ]] || exit 0
shopt -s extglob
bare=$(strip_single_quotes "${cmd}") \
    || ask "This shell command could not be parsed, and it touches .storage, the entity registry, integrations, secrets, services or areas."
# Drop fd duplications (2>&1, >&2, <&3, >&-) and turn the both-streams forms
# (&>, >&FILE) into a plain `>`, so the split below only sees real `&`
# separators and every file redirect keeps its target
bare=$(printf '%s' "${bare}" | sed -E 's/[0-9]*[<>]&[[:space:]]*[0-9-]+//g; s/&>/>/g; s/>&/>/g')
# One command per line: split on ; & | newlines, $( ), backticks, ( )
segments=$(printf '%s\n' "${bare}" | sed -E 's/\$\(|[;&|()`]/\n/g')

# Destructive tool subcommands, found in the loose segments from above
[[ -n ${loose} ]] || loose=$(loose_segments "${cmd}")
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
            'ha-areas delete')
                reason="Deleting an area, floor or label takes it off every device, entity and area that has it; automations and dashboards that target it stop doing anything."
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
            ask "This service call can restart or stop Home Assistant, run a shell command, purge recorded history or install an update."
        fi
    done
    [[ -z ${reason} || " ${words[*]} " == *" --dry-run "* ]] || ask "${reason}"
done <<< "${loose}"

if [[ ${plain} == *.storage* ]]; then
    redirects_safe "${bare}" \
        || ask "This shell command may write into Home Assistant's .storage directory (its internal state)."
    while IFS= read -r segment; do
        [[ -z ${segment//[[:space:]]/} ]] && continue
        read_only "${segment}" \
            || ask "This shell command touches Home Assistant's .storage directory (its internal state) with something other than a read."
    done <<< "${segments}"
fi

exit 0
