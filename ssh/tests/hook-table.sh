# shellcheck shell=bash
# ==============================================================================
# Shared engine for the hook table tests (sourced, not run)
#
# The caller sets HOOK (the hook script) and CASES (a TSV of
# `expect<TAB>command[<TAB>cwd]`; the optional cwd becomes the payload's .cwd)
# and defines classify(): given the hook's exit code and stdout, print the
# result word to compare with `expect`. It then calls run_table for the TSV,
# check for any one-off cases, and finish for the summary and exit status.
# ==============================================================================

failures=0
total=0

# check EXPECT LABEL PAYLOAD: feed PAYLOAD to the hook and compare classify()
check() {
    local expect=$1 label=$2 payload=$3 out rc got
    total=$((total + 1))
    out=$(printf '%s' "${payload}" | bash "${HOOK}" 2> /dev/null)
    rc=$?
    got=$(classify "${rc}" "${out}")
    if [[ ${got} == "${expect}" ]]; then
        printf 'ok    %-6s %s\n' "${got}" "${label}"
    else
        printf 'FAIL  want=%-6s got=%-6s %s\n' "${expect}" "${got}" "${label}"
        failures=$((failures + 1))
    fi
}

# run_table: one PreToolUse[Bash] check per `expect<TAB>command[<TAB>cwd]`
# line of CASES
run_table() {
    local expect cmd cwd
    while IFS=$'\t' read -r expect cmd cwd; do
        [[ -z ${expect} || ${expect} == \#* ]] && continue
        check "${expect}" "${cmd}${cwd:+  [cwd ${cwd}]}" "$(bash_payload "${cmd}" "${cwd}")"
    done < "${CASES}"
}

# bash_payload COMMAND [CWD]: a PreToolUse[Bash] payload, with .cwd if given
bash_payload() {
    jq -nc --arg c "$1" --arg w "${2-}" \
        '{tool_name: "Bash", tool_input: {command: $c}} + if $w == "" then {} else {cwd: $w} end'
}

# edit_payload FILE_PATH: a PreToolUse[Edit] payload
edit_payload() {
    jq -nc --arg p "$1" '{tool_name:"Edit",tool_input:{file_path:$p}}'
}

finish() {
    printf '\n%d/%d passed\n' "$((total - failures))" "${total}"
    exit $((failures > 0))
}
