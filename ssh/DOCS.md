# Home Assistant App: SSH & Claude Code Terminal

This app allows you to log in to your Home Assistant instance using
SSH or a Web Terminal, giving you access to your folders and
also includes a command-line tool to do things like restart, update,
and check your instance.

This fork includes [Claude Code][claude-code], an AI-powered coding assistant
that can help you optimize your Home Assistant configuration, write automations,
and troubleshoot issues directly from the terminal.

Based on the [SSH app by Home Assistant Community Apps][hass-ssh],
this version focuses on security, usability, and AI-assisted configuration.

## WARNING

The SSH & Claude Code Terminal app is very powerful and gives you access
to almost all tools and hardware of your system.

While this app is created and maintained with care and with security in mind,
in the wrong or inexperienced hands, it could damage your system.

## Features

This app, of course, provides an SSH server, based on [OpenSSH][openssh] and
a web-based Terminal (which can be included in your Home Assistant frontend) as
well. Additionally, it comes out of the box with the following:

- Access your command line right from the Home Assistant frontend!
- A secure default configuration of SSH:
  - Only allows login by the configured user, even if more users are created.
  - Only uses known secure ciphers and algorithms.
  - Limits login attempts to hold off brute-force attacks better.
- Comes with an SSH compatibility mode option to allow older clients to connect.
- Support for Mosh allowing roaming and supports intermittent connectivity.
- SFTP support is disabled by default but is user configurable.
- Compatible if Home Assistant was installed via the generic Linux installer.
- Username is configurable, so `root` is no longer mandatory.
- Persists custom SSH client settings & keys between app restarts
- Log levels for allowing you to triage issues easier.
- Hardware access to your audio, uart/serial devices and GPIO pins.
- Runs with more privileges, allowing you to debug and test more situations.
- Has access to the dbus of the host system.
- Has the option to access the Docker instance running on the host system.
- Runs on host level network, allowing you to open ports or run little daemons.
- Have custom Alpine packages installed on start. This allows you to install
  your favorite tools, which will be available every single time you log in.
- Execute custom commands on app start so that you can customize the
  shell to your likings.
- [ZSH][zsh] as its default shell. Easier to use for the beginner, more advanced
  for the more experienced user. It even comes preloaded with
  ["Oh My ZSH"][ohmyzsh], with some plugins enabled as well.
- Contains a sensible set of tools right out of the box: curl, Wget, RSync, GIT,
  Nmap, Mosquitto client, MariaDB/MySQL client, Awake ("wake on LAN"), Nano,
  Vim, tmux, and a bunch commonly used networking tools.
- [Claude Code][claude-code] pre-installed for AI-assisted Home Assistant
  configuration and automation development.
- [yamllint][yamllint] included for validating YAML configuration files.

## Installation

This app is not part of the official Home Assistant app store.
To install it, you need to add this repository as a custom repository:

1. Open your Home Assistant instance.
1. Navigate to **Settings** → **Apps** → **Install App**.
1. Click the menu (three dots) in the top right corner.
1. Select **Repositories**.
1. Add the following URL:
   ```
   https://github.com/Tyderion/ha-addon-claude-code
   ```
1. Click **Add** and then **Close**.
1. Refresh the page and find "SSH & Claude Code Terminal" in the app store.
1. Click **Install**.
1. Configure the `username` and `password`/`authorized_keys` options.
1. Start the "SSH & Claude Code Terminal" app.
1. Check the logs of the app to see if everything went well.

## Configuration

**Note**: _Remember to restart the app when the configuration is changed._

SSH app configuration:

```yaml
log_level: info
ssh:
  username: homeassistant
  password: ""
  authorized_keys:
    - ssh-ed25519 AASDJKJKJFWJFAFLCNALCMLAK234234.....
  sftp: false
  compatibility_mode: false
  allow_agent_forwarding: false
  allow_remote_port_forwarding: false
  allow_tcp_forwarding: false
zsh: true
share_sessions: true
packages:
  - build-base
init_commands:
  - ls -la
claude_md: []
claude_permission_mode: auto
```

**Note**: _This is just an example, don't copy and paste it! Create your own!_

### Option: `log_level`

The `log_level` option controls the level of log output by the app and can
be changed to be more or less verbose, which might be useful when you are
dealing with an unknown issue. Possible values are:

- `trace`: Show every detail, like all called internal functions.
- `debug`: Shows detailed debug information.
- `info`: Normal (usually) interesting events.
- `warning`: Exceptional occurrences that are not errors.
- `error`: Runtime errors that do not require immediate action.
- `fatal`: Something went terribly wrong. App becomes unusable.

Please note that each level automatically includes log messages from a
more severe level, e.g., `debug` also shows `info` messages. By default,
the `log_level` is set to `info`, which is the recommended setting unless
you are troubleshooting.

Using `trace` or `debug` log levels puts the SSH and Terminal daemons into
debug mode. While SSH is running in debug mode, it will be only able to
accept one single connection at the time.

### Option group `ssh`

---

The following options are for the option group: `ssh`. These settings
only apply to the SSH daemon.

#### Option `ssh`: `username`

This option allows you to change to username the use when you log in via SSH.
It is only utilized for the authentication; you will be the `root` user after
you have authenticated. Using `root` as the username is possible, but not
recommended. Usernames will be converted to lower case as per recommended
practises.

**Note**: _Due to limitations, you will need to set this option to `root` in
order to be able to enable the SFTP capabilities._

#### Option `ssh`: `password`

Sets the password to log in with. Leaving it empty disables authenticating with
a password. Using public key authentication instead of password authentication
is highly recommended from a security point of view.

#### Option `ssh` `authorized_keys`

Add one or more public keys to your SSH server to use with authentication.
This is the recommended over setting a password.

Please take a look at the awesome [documentation created by GitHub][github-ssh]
about using public/private key pairs and how to create them.

**Note**: _Please ensure the keys are specified as a list by pasting within the
`[]` comma delimited._

#### Option `ssh`: `sftp`

When set to `true` the app will enable SFTP support on the SSH daemon.
Please only enable it when you plan on using it.

**Note**: _Due to limitations, you will need to set the username to `root` in
order to be able to enable the SFTP capabilities._

#### Option `ssh`: `compatibility_mode`

This SSH app focuses on security and has therefore only enabled known
secure encryption methods. However, some older clients do not support these.
Setting this option to `true` will enable the original default set of methods,
allowing those clients to connect.

**Note**: _Enabling this option, lowers the security of your SSH server!_

#### Option `ssh`: `allow_agent_forwarding`

Specifies whether ssh-agent forwarding is permitted or not.

**Note**: _Enabling this option, lowers the security of your SSH server!
Nevertheless, this warning is debatable._

#### Option `ssh`: `allow_remote_port_forwarding`

Specifies whether remote hosts are allowed to connect to ports forwarded
for the client.

**Note**: _Enabling this affects all remote forwardings, so think carefully
before doing this._

#### Option `ssh`: `allow_tcp_forwarding`

Specifies whether TCP forwarding is permitted or not.

**Note**: _Enabling this option, lowers the security of your SSH server!
Nevertheless, this warning is debatable._

### Shared settings

---

The following options are shared between both the SSH and the Web Terminal.

#### Option: `zsh`

The app has ZSH pre-installed and configured as the default shell.
However, ZSH might not be your preferred choice. By setting this option to
`false`, you will disable ZSH and the app will fallback to Bash instead.

#### Option: `share_sessions`

By default, the terminal session between the web client and SSH is shared.
This allows you to pick up where you left your terminal from either of those.

This option allows you to disable this behavior by setting it to `false`, which
effectively sets SSH to behave as it used to be.

#### Option: `packages`

Allows you to specify additional [Alpine packages][alpine-packages] to be
installed in your shell environment (e.g., Python, Joe, Irssi).

**Note**: _Adding many packages will result in a longer start-up
time for the app._

#### Option: `init_commands`

Customize your shell environment even more with the `init_commands` option.
Add one or more shell commands to the list, and they will be executed every
single time this app starts.

#### Option: `claude_md`

Define the contents of your `CLAUDE.md` file through the app configuration.
Each line of the file is a separate entry in the list. When configured, this
file is written to `/homeassistant/CLAUDE.md` on every app start.

Example:

```yaml
claude_md:
  - "# My Home Assistant"
  - ""
  - "## Integrations"
  - "- Zigbee2MQTT for Zigbee devices"
  - "- ESPHome for custom sensors"
  - ""
  - "## Notes"
  - "- Don't modify automations starting with system_"
```

If left empty, the file is not touched, allowing you to edit it directly via
the File Editor app or VS Code.

#### Option: `claude_permission_mode`

Controls how much Claude Code asks before it acts. This sets
`permissions.defaultMode` in the persistent settings file on every app start,
so it is the one place to change the behaviour.

- `auto` (default) — Claude decides for itself whether an operation is
  routine, using the description of this container in the `autoMode` section
  of the settings file. Routine Home Assistant work (reading and editing
  config, running the `ha-*` tools, throwaway `python3` analysis, piped
  investigation commands) runs without prompting; the `ask` rules and the
  destructive guard hook still apply.
- `default` — the stock Claude Code behaviour. Everything that is not matched
  by an explicit `allow` rule prompts you. Safest, and by far the noisiest,
  because the shapes Claude actually writes (heredocs, pipes,
  `cd x && y`) never match a prefix rule.
- `acceptEdits` — like `default`, but file edits inside the working directory
  are approved automatically while commands still prompt.
- `bypassPermissions` — nothing prompts. The `deny` and `ask` rules are
  skipped entirely; only the destructive guard hook still holds, because
  hooks run in every mode. Use this only if you understand that Claude then
  has the same reach into your Home Assistant instance that you do over SSH.

```yaml
claude_permission_mode: auto
```

## Using Claude Code

This app comes with [Claude Code][claude-code] pre-installed, an AI-powered
coding assistant from Anthropic that can help you with Home Assistant
configuration.

### Getting Started

1. Open the terminal (via SSH or Web Terminal)
2. Claude Code starts automatically in `/homeassistant`
3. On first use, run `/login` to authenticate via your browser
4. Start asking questions about your Home Assistant configuration

The status line at the bottom shows your Home Assistant version, the AI model,
and context window usage.

### Example Use Cases

- Writing and debugging automations
- Optimizing YAML configurations
- Understanding complex templates
- Troubleshooting integration issues
- Converting automations between formats

### Pre-configured Permissions

The default permission mode is `auto` (see
[`claude_permission_mode`](#option-claude_permission_mode)). The trust
boundary is the container, not the individual command: this app runs as root
and holds a Supervisor API token, so anything that can reach the Supervisor
can already restart Core and read every secret. Arguing over which binaries
Claude may invoke buys no safety, and in the stock `default` mode it bought a
prompt on nearly every command, because heredoc `python3` scripts, pipes and
`cd x && y` chains never match a prefix allow rule.

So the settings file describes the container to Claude instead, in an
`autoMode` block, and lets it approve routine Home Assistant work by itself:
reading and editing config under `/homeassistant`, running the bundled `ha-*`
tools, `sqlite3` queries against the recorder database, throwaway `python3`
and `bash` analysis, and read-only pipelines through `jq`, `rg` and friends.

Explicit rules still exist and still take precedence:

- **Read/Edit/Write**: `/homeassistant/**`, `/addon_configs/**`, `/share/**`
- **Read**: `/addons/**`, `/backup/**`, `/media/**`, `/ssl/**`
- **Bash**: the `ha` CLI, the bundled `ha-*` tools, `yamllint`, `sqlite3`,
  `python3`, `bluetoothctl`, read-only shell utilities and `git`
  subcommands, and `curl` GETs to `http://supervisor/*`

**Always asks first**, in every mode except `bypassPermissions`:
`ha core restart/stop/update`, `ha host reboot/shutdown`,
`ha backup restore`, `ha addons uninstall/stop`, `ha os update`,
`ha supervisor update`, `curl` POSTs to the Supervisor API (which can call
any service, restart Core, or restore a backup), and reading or writing
`secrets.yaml`.

**Denied outright**: edits to `/homeassistant/.storage/**`. That directory is
Home Assistant's internal state; dashboards go through `ha-dashboard` and
everything else through the UI.

These permissions live in `/share/.claude/settings.json` and persist across
restarts. New defaults are merged in additively on every start, so rules you
add by hand or with Claude's `/permissions` command are never dropped. The
one exception is a short list of rules the app itself shipped in earlier
versions and has since replaced (`/etc/claude/settings-stale.json`); those
are pruned by exact match, because they used a `Bash(cmd *)` glob form that
never actually matched anything and only made the file look protective.

### Guardrails

Three hooks ship with the app and are registered automatically in
`/share/.claude/settings.json`:

- **Destructive guard** — a `PreToolUse` hook that blocks a small set of
  operations outright, whatever the permission mode: recursive deletes
  targeting `/` or a mapped Home Assistant directory, `mkfs` and `dd` writes
  to device nodes, piping a download straight into a shell, and any shell
  write into `.storage`. Hooks run even under `bypassPermissions`, which is
  the point — this is the floor that holds when the permission rules are
  switched off. Merely consequential operations (restarts, reboots, backup
  restores) are deliberately _not_ here; those are things you legitimately
  ask for, so they sit in the `ask` list instead.
- **Tool path rewriting** — Claude reaching for `./ha-entities`,
  `/usr/local/bin/ha-service` or `python3 ha-state.py` has the command
  rewritten to the bare PATH name before it runs. Without this, those forms
  miss the allow rules, prompt you needlessly, and push Claude toward
  hand-rolled scripts instead of the real tools.
- **YAML validation** — every edit to a `.yaml` file under `/homeassistant`
  is parsed immediately. Home Assistant's custom tags (`!secret`, `!include*`,
  `!input`) are understood, and duplicate top-level keys are reported as
  errors because they silently discard the earlier block. Failures are handed
  straight back to Claude to fix. Style is not checked; run `yamllint` for that.

Unlike permissions, the `statusLine`, `hooks` and `autoMode` sections are
app-managed: they describe what the image ships and are overwritten from it on
every start, so custom hooks belong in a separate settings file.

### Custom Project Instructions

You can create a `CLAUDE.md` file in your Home Assistant config directory
(`/homeassistant/CLAUDE.md`) to give Claude context about your specific setup:

```markdown
# My Home Assistant Setup

## Integrations

- Zigbee2MQTT for Zigbee devices
- ESPHome for custom sensors

## Naming Conventions

- Automations: automation*<room>*<function>
- Scripts: script\_<action>

## Notes

- Don't modify automations starting with "system\_"
```

A template is available at `/etc/claude/CLAUDE.md.template` that you can copy
and customize.

### Session Persistence

Claude Code settings, history, and authentication persist across app restarts.
All data is stored in `/share/.claude/`.

### YAML Validation

This app also includes `yamllint` for validating your YAML files:

```bash
# Validate a specific file
yamllint /config/configuration.yaml

# Validate all YAML files in config
yamllint /config/*.yaml
```

### Hot Reload Configuration

Use `ha-reload` to apply YAML changes without restarting Home Assistant:

```bash
ha-reload
```

This is equivalent to Developer Tools → YAML → Quick Reload in the UI. It:

- Reloads all hot-reloadable YAML domains at once (see the
  `HomeAssistantReload` skill for the full list)
- Has no downtime (instant reload)

Validate your changes first with `yamllint` (and `ha core check` for
`configuration.yaml` changes). Use `ha core restart` only when adding new
integrations or changing logger/recorder/http settings.

### Built-in Skills

Claude Code comes with the `HomeAssistantReload` skill pre-installed. You can
invoke it with `/HomeAssistantReload` or Claude will automatically use it when
you ask to apply configuration changes.

The skill intelligently chooses between `ha-reload` (for YAML changes) and
`ha core restart` (for new integrations), and guides you through validation
before applying changes.

## Known issues and limitations

- When SFTP is enabled, the username MUST be set to `root`.
- If you want to use rsync for file transfer, the username MUST be set to
  `root`.

## Changelog & Releases

This repository keeps a change log using [GitHub's releases][releases]
functionality.

Releases are based on [Semantic Versioning][semver], and use the format
of `MAJOR.MINOR.PATCH`. In a nutshell, the version will be incremented
based on the following:

- `MAJOR`: Incompatible or major changes.
- `MINOR`: Backwards-compatible new features and enhancements.
- `PATCH`: Backwards-compatible bugfixes and package updates.

## Support

Got questions?

- [Open an issue][issue] on GitHub for bug reports and feature requests.
- The [Home Assistant Discord chat server][discord-ha] for general Home
  Assistant discussions and questions.
- Join the [Reddit subreddit][reddit] in [/r/homeassistant][reddit]

## Authors & contributors

This fork is maintained by [Jan Nicklas][jantimon].

The original app was created by [Franck Nijhof][frenck].

For a full list of all authors and contributors,
check [the contributors page][contributors].

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

[alpine-packages]: https://pkgs.alpinelinux.org/packages
[claude-code]: https://claude.ai/code
[contributors]: https://github.com/hassio-addons/app-ssh/graphs/contributors
[discord-ha]: https://discord.gg/c5DvZ4e
[discord]: https://discord.me/hassioaddons
[forum]: https://community.home-assistant.io/t/community-hass-io-add-on-ssh-web-terminal/33820?u=frenck
[frenck]: https://github.com/frenck
[github-ssh]: https://help.github.com/articles/connecting-to-github-with-ssh/
[hass-ssh]: https://github.com/home-assistant/addons/tree/master/ssh
[issue]: https://github.com/hassio-addons/app-ssh/issues
[jantimon]: https://github.com/jantimon
[ohmyzsh]: http://ohmyz.sh/
[openssh]: https://www.openssh.com/
[reddit]: https://reddit.com/r/homeassistant
[releases]: https://github.com/hassio-addons/app-ssh/releases
[semver]: https://semver.org/spec/v2.0.0.html
[yamllint]: https://yamllint.readthedocs.io/
[zsh]: https://en.wikipedia.org/wiki/Z_shell
