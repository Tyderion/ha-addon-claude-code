# Home Assistant App: SSH & Claude Code Terminal

[![License][license-shield]](LICENSE.md)

![Supports aarch64 Architecture][aarch64-shield]
![Supports amd64 Architecture][amd64-shield]

[Claude Code][claude-code] set up to work on one Home Assistant instance: it starts in your configuration directory, knows your entities, services and integrations through bundled tools, and runs behind guardrails that keep it away from Home Assistant's internal state and your credentials. Underneath is a full SSH server and web terminal.

![Web Terminal in the Home Assistant Frontend](images/screenshot.png)

[:books: Read the full documentation][docs]

## WARNING

This app runs as root with access to almost all tools and hardware of your system, and Claude Code acts with those rights. The guardrails below block the most damaging operations and ask before the risky ones, but they are not a sandbox. Review what Claude proposes, keep backups, and use the permission mode that matches how much you want to approve by hand.

## What Claude Code gets

**Tools that talk to Home Assistant's own APIs**, so Claude looks things up instead of guessing and never edits `.storage` by hand. They are on `PATH` and covered by skills that tell Claude when to use which:

| Skill               | Tool                            | What it does                                                                        |
| ------------------- | ------------------------------- | ----------------------------------------------------------------------------------- |
| `FindEntities`      | `ha-entities`                   | Find entities, read their state, list areas, domains, scripts and automations       |
| `FindReferences`    | `ha-entities refs`              | What uses an entity or device: automations, scripts, dashboards, templates, YAML    |
| `UpdateEntity`      | `ha-entities update` / `rename` | Rename entities and devices, move them to areas, label, hide, disable, change ids   |
| `ManageAreas`       | `ha-areas`                      | List, create, rename and delete areas, floors and labels                            |
| `CallService`       | `ha-service`                    | Look up a service's real fields and call it                                         |
| `SetState`          | `ha-state`                      | Set helpers, counters, timers and vars with validation and read-back                |
| `QueryHistory`      | `ha-history`                    | Recorded history, who or what changed it, and long-term statistics                  |
| `DebugAutomation`   | `ha-trace`                      | Why an automation did or didn't run, from its traces                                |
| `TestTemplate`      | `ha-template`                   | Render Jinja against live state; device, area and label membership                  |
| `ManageIntegration` | `ha-integrations`               | Add, configure, reload, disable or remove integrations through config flows         |
| `ManageSecrets`     | `ha-secrets`                    | List secret names, create and test-fire webhook ids, without opening `secrets.yaml` |
| `EditDashboard`     | `ha-dashboard`                  | Read and write Lovelace dashboards through the API                                  |
| `ReloadConfig`      | `ha-reload`                     | Hot-reload YAML, and decide when a restart is really needed                         |
| `ManageSystem`      | `ha-system`, `ha apps`          | Pending updates, repairs, and restarting, updating or reading the logs of apps      |

**Guardrails**, as hooks and permission rules:

- **Blocked outright, in every permission mode:** recursive deletes of a mapped directory, `mkfs`/`dd` onto a device, piping a download into a shell, the usual shell writes into `.storage` (`tee`, `sed -i`, `cp`/`mv` into it, redirects) and any edit there with Claude's file tools.
- **Asks you first, in every mode except `bypassPermissions`:** any command or edit that names `secrets.yaml`, non-read access to `.storage`, `ha-entities rename`, `ha-integrations delete`/`disable` and `ha-areas delete` (a `--dry-run` runs without asking), `ha-secrets get`/`add`, `ha-service --unsafe` (which `update.install` needs), `ha-dashboard delete`, and every `ha` CLI command except reads and a few routine ones, in any of its spellings (`ha apps uninstall`, `ha addon remove`, `ha ha restart`, `ha backup rm`, ...).
- **Checked after every edit:** a YAML file Claude edits under `/homeassistant` with its file tools is parsed at once, and syntax errors or duplicate keys come back to Claude before it reloads anything.

**Pre-configured permissions** for the tools above, with `auto` permission mode by default, so routine work runs without a prompt for every command.

**Options** to name the session, continue the last conversation, start the session when the app starts, connect it to [Remote Control][claude-remote-control], pick the permission mode, and write your own `CLAUDE.md`. Login, history and settings live in `/share/.claude` (and `/share/.claude.json`) and survive restarts and app updates; Claude Code's own updates do too, in `/data/claude-versions`.

## Installation

This app is not part of the official Home Assistant app repository. To install it, add this repository as a custom repository:

1. Open your Home Assistant instance
2. Navigate to **Settings** → **Apps** → **Install App**
3. Click the menu (three dots) in the top right corner
4. Select **Repositories**
5. Add the following URL:
   ```
   https://github.com/Tyderion/ha-addon-claude-code
   ```
6. Click **Add** and then **Close**
7. Refresh the page and find "SSH & Claude Code Terminal" in the app store
8. Click **Install**

After installation, configure your username and password or SSH keys, then start the app.

## Getting started

1. Open the terminal from the sidebar (or log in over SSH).
2. Claude Code starts in `/homeassistant`.
3. On first use, run `/login` to authenticate in your browser.
4. Ask about your setup: "why didn't the hallway lights turn on last night?", "add the bedroom temperature to my overview dashboard", "make a webhook my NAS can call".

The status line shows your Home Assistant version, the model and the context usage.

## The terminal underneath

The app is a fork of the [Advanced SSH & Web Terminal app][upstream] and keeps all of it: a hardened OpenSSH server (configurable user, SFTP, Mosh, compatibility mode), the web terminal, ZSH with Oh My ZSH, tmux, the `ha` CLI, common network and database tools, extra Alpine packages and init commands on start, and access to hardware, dbus and optionally Docker. The [documentation][docs] covers every option.

## Support

[Open an issue][issue] for bugs and feature requests. For general Home Assistant questions, the [Home Assistant Discord][discord-ha] and [/r/homeassistant][reddit] are good places.

## Development

The repository layout and conventions are in [CLAUDE.md](CLAUDE.md). Tooling runs through [pixi](https://pixi.sh):

```sh
pixi run fmt         # format markdown, shell scripts and Python
pixi run fmt-check   # check formatting without writing
pixi run test        # hook tables, the claude wrapper and the Python tool tests
```

There is no local image build: CI builds it, and to try a change for real, install your fork as a custom repository in Home Assistant. Contribution guidelines are in [.github/CONTRIBUTING.md](.github/CONTRIBUTING.md).

## Authors & contributors

This fork is maintained by [Tyderion][tyderion]. It builds on [Jan Nicklas][jantimon]'s Claude Code fork of the [Advanced SSH & Web Terminal app][upstream], which [Franck Nijhof][frenck] created. For everyone who contributed, see [the contributors page][contributors].

## License

MIT License

Copyright (c) 2017-2026 Franck Nijhof

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

[aarch64-shield]: https://img.shields.io/badge/aarch64-yes-green.svg
[amd64-shield]: https://img.shields.io/badge/amd64-yes-green.svg
[claude-code]: https://claude.ai/code
[claude-remote-control]: https://code.claude.com/docs/en/remote-control
[contributors]: https://github.com/Tyderion/ha-addon-claude-code/graphs/contributors
[discord-ha]: https://discord.gg/c5DvZ4e
[docs]: https://github.com/Tyderion/ha-addon-claude-code/blob/main/ssh/DOCS.md
[frenck]: https://github.com/frenck
[issue]: https://github.com/Tyderion/ha-addon-claude-code/issues
[jantimon]: https://github.com/jantimon
[license-shield]: https://img.shields.io/github/license/Tyderion/ha-addon-claude-code.svg
[reddit]: https://reddit.com/r/homeassistant
[tyderion]: https://github.com/Tyderion
[upstream]: https://github.com/hassio-addons/app-ssh
