# CLAUDE.md

Home Assistant add-on: **SSH & Claude Code Terminal** — a fork of the community
"Advanced SSH & Web Terminal" add-on with Claude Code pre-installed. The repo is
an add-on repository (`repository.yaml`) containing one add-on in `ssh/`.

## Layout

- `ssh/config.yaml` — add-on manifest (options schema, ports, privileges, `map:` mounts)
- `ssh/Dockerfile`, `ssh/build.yaml` — image build on `ghcr.io/hassio-addons/base` (aarch64/amd64)
- `ssh/requirements.txt` — Python packages installed into the image
- `ssh/DOCS.md` — user-facing documentation; `ssh/.README.j2` — README template
- `ssh/rootfs/` — files copied verbatim into the container image:
  - `etc/s6-overlay/s6-rc.d/<service>/` — s6 services (`init-*` oneshots, `sshd`/`ttyd` longruns; dependencies via `dependencies.d/`, registered in `user/contents.d/`)
  - `etc/claude/` — Claude Code setup shipped to users: `settings.json` (permission rules, `autoMode` container description, hook registrations), `settings-stale.json` (old default rules pruned from users' persistent settings on start), `CLAUDE.md.template` (installed into `/homeassistant`), `statusline.sh`, `hooks/*`, `skills/*/SKILL.md`
  - `usr/local/bin/` — CLI tools: `ha-entities.py`, `ha-dashboard.py`, `ha-reload`, shared WebSocket lib `ha_lib.py`
- `ssh/tests/` — table tests for the shipped hooks (`*.cases.tsv` + `*.test.sh`); not copied into the image
- `.github/workflows/ci.yaml` — CI via shared `hassio-addons/workflows` (hadolint, shellcheck, yamllint, markdownlint per `.yamllint`/`.mdlrc`), plus format checks and hook tests

## Conventions

- Shell: s6 scripts start with `#!/command/with-contenv bashio` + `# shellcheck shell=bash`, use bashio helpers (`bashio::log.*`, `bashio::config`), `readonly` constants at top, and a `# ====` banner comment header.
- Shell formatting: shfmt with 4-space indent, `-bn -ci -sr` (binary ops at line start, indented case, redirect spaces).
- Python: standalone scripts, stdlib plus PyYAML only (docopt-style docstring header), formatted/linted with ruff; shared HA WebSocket access goes through `ha_lib.ha_call()`.
- Persistence pattern: user state lives under `/data` or `/share` and is symlinked/merged into `/root` by `init-user/run` — follow it when adding persisted config. The Claude settings merge there is additive for `permissions.{allow,ask,deny}`, image-managed for `statusLine`/`hooks`/`autoMode`, and option-driven for `permissions.defaultMode`; retiring a shipped default rule means adding it to `settings-stale.json`, since the merge can never drop one on its own.
- YAML files start with `---`; keep `config.yaml` `options:` and `schema:` in sync.
- Skills follow the Claude Code SKILL.md format: frontmatter `name` + `description` with "USE WHEN …" triggers.

## Commands

- `pixi run fmt` — format everything (`fmt-md` prettier, `fmt-sh` shfmt, `fmt-py` ruff)
- `pixi run fmt-check` — CI-style check without writing
- `pixi run test` — run the hook table tests
- No local image build; CI builds it on PRs. To test for real, install the repo as a custom add-on repository in Home Assistant.
