#!/bin/bash

# Read JSON input from stdin
input=$(cat)

# Extract values from JSON in one jq call (one value per line):
# model, current dir relative to the project dir, context window percentage
mapfile -t fields < <(echo "$input" | jq -r '
    .context_window as $cw |
    (.workspace.project_dir | tostring) as $project |
    (.workspace.current_dir | tostring) as $current |
    (.model.display_name | tostring),
    (if $current == $project then ""
     elif ($current | startswith($project + "/")) then $current[($project | length) + 1:]
     else $current
     end),
    (if $cw.current_usage == null then 0
     else (($cw.current_usage.input_tokens // 0)
         + ($cw.current_usage.cache_creation_input_tokens // 0)
         + ($cw.current_usage.cache_read_input_tokens // 0)) * 100 / $cw.context_window_size | floor
     end)')
model=${fields[0]}
rel_dir=${fields[1]}
pct=${fields[2]}

# Colors
CYAN='\033[36m'
GREEN='\033[32m'
YELLOW='\033[33m'
LAVENDER='\033[38;2;178;185;244m'
RESET='\033[0m'

# Get Home Assistant version
ha_version=$(ha core info --raw-json 2> /dev/null | jq -r '.data.version // empty')

# Build ASCII progress bar (10 chars wide)
bar_width=10
filled=$((pct * bar_width / 100))
empty=$((bar_width - filled))
bar="[$(printf '%*s' "$filled" '' | tr ' ' '=')$(printf '%*s' "$empty" '' | tr ' ' '-')]"
context_info="${LAVENDER}${bar}${RESET} ${pct}%"

# Build status line: optional directory and HA version, then model and context
parts=()
if [ -n "$rel_dir" ]; then
    parts+=("${CYAN}${rel_dir}${RESET}")
fi
if [ -n "$ha_version" ]; then
    parts+=("${GREEN}HA ${ha_version}${RESET}")
fi

status=""
if [ ${#parts[@]} -gt 0 ]; then
    status="${parts[*]} | "
fi
status="${status}${YELLOW}${model}${RESET} | ${context_info}"

printf '%b' "$status"
