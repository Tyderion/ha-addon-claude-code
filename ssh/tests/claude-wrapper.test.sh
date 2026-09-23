#!/usr/bin/env bash
# shellcheck shell=bash
# ==============================================================================
# Table test for usr/local/bin/claude (the session-name wrapper)
#
# Reads claude-wrapper.cases.tsv (`name<TAB>args<TAB>expected`), writes the
# name to an addon.env the way init-user does, and runs the wrapper against a
# stub binary that prints the argv it receives as `[a][b]...`. The stub's
# `--help` prints a Commands section, so subcommand detection is exercised
# end to end; a final case checks the fallback list when `--help` is useless.
#
# Run: bash ssh/tests/claude-wrapper.test.sh
# ==============================================================================
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly HERE
readonly WRAPPER="${HERE}/../rootfs/usr/local/bin/claude"
readonly CASES="${HERE}/claude-wrapper.cases.tsv"

WORK=$(mktemp -d)
readonly WORK
trap 'rm -rf "${WORK}"' EXIT

export CLAUDE_ADDON_BIN="${WORK}/claude-bin"
export CLAUDE_ADDON_ENV="${WORK}/addon.env"
export CLAUDE_ADDON_CACHE="${WORK}/cache"

cat > "${CLAUDE_ADDON_BIN}" << 'STUB'
#!/usr/bin/env bash
if [[ $# -eq 1 && $1 == --help && -z ${STUB_NO_HELP-} ]]; then
    cat << 'HELP'
Usage: claude [options] [command] [prompt]

Options:
  -n, --name <name>                                 Set a display name for this session
  -p, --print                                       Print response and exit

Commands:
  doctor                                            Check the health of your Claude Code auto-updater
  mcp                                               Configure and manage MCP servers
  plugin|plugins                                    Manage Claude Code plugins
  update|upgrade                                    Check for updates and install if available
                                                    (continuation line of a long description)
  help [command]                                    display help for command
HELP
    exit 0
fi
(($#)) && printf '[%s]' "$@"
STUB
chmod +x "${CLAUDE_ADDON_BIN}"

failures=0
total=0

check() {
    local name=$1 args=$2 expect=$3 got
    total=$((total + 1))
    if [[ ${name} == - ]]; then
        : > "${CLAUDE_ADDON_ENV}"
    else
        printf 'CLAUDE_SESSION_NAME=%q\n' "${name}" > "${CLAUDE_ADDON_ENV}"
    fi
    [[ ${args} == '()' ]] && args=''
    got=$(eval "bash \"${WRAPPER}\" ${args}")
    case ${got} in
        '') got='()' ;;
        Usage:*) got='(help text)' ;;
    esac
    if [[ ${got} == "${expect}" ]]; then
        printf 'ok    %-16s %s\n' "${name}" "${args}"
    else
        printf 'FAIL  %-16s %s\n      want: %s\n      got:  %s\n' \
            "${name}" "${args}" "${expect}" "${got}"
        failures=$((failures + 1))
    fi
}

while IFS=$'\t' read -r name args expect; do
    [[ -z ${name} || ${name} == \#* ]] && continue
    check "${name}" "${args}" "${expect}"
done < "${CASES}"

# `--help` without a Commands section falls back to the built-in list
rm -rf "${CLAUDE_ADDON_CACHE}"
STUB_NO_HELP=1 check 'Home Assistant' 'setup-token' '[setup-token]'
STUB_NO_HELP=1 check 'Home Assistant' 'hello' '[--name][Home Assistant][hello]'
[[ -z "$(ls -A "${CLAUDE_ADDON_CACHE}" 2> /dev/null)" ]] || {
    printf 'FAIL  a failed --help parse left a cache file behind\n'
    failures=$((failures + 1))
}

printf '\n%d/%d passed\n' "$((total - failures))" "${total}"
exit $((failures > 0))
