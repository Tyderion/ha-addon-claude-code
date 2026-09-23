# shellcheck shell=bash
if [[ -z "$TMUX" ]]; then
  exec tmux -u new -A -s homeassistant bash -l
fi
# shellcheck source=/dev/null
[[ -f ~/.bashrc ]] && . ~/.bashrc
