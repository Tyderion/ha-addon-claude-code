# shellcheck shell=bash
# Read by interactive Bash shells (`zsh: false`); login shells get here via
# ~/.bash_profile, or ~/.bash_login when session sharing is disabled.

# Start in Home Assistant config directory
cd /homeassistant || true

# Auto-start Claude Code (only in interactive, non-nested shells)
if [[ $- == *i* ]] && [[ -z "$CLAUDE_RUNNING" ]]; then
  export CLAUDE_RUNNING=1
  claude-autostart
fi
