# lockin

[![CI](https://github.com/madhusudan-kulkarni/lockin/actions/workflows/ci.yml/badge.svg)](https://github.com/madhusudan-kulkarni/lockin/actions)
[![PyPI](https://img.shields.io/pypi/v/lockin-blocker)](https://pypi.org/project/lockin-blocker/)

Block distracting websites on Linux. No proxy, no browser extension, no MITM
certificate.

lockin writes blocked domains to `/etc/hosts` and rejects QUIC/HTTP3 (UDP 443)
via nftables or iptables for **every destination** on the machine. A systemd
watchdog re-applies the block about once a minute.

## Quick start

Linux with systemd. Run lockin as yourself. The tool calls `sudo` for
`/etc/hosts` and firewall rules. Do **not** run `sudo lockin`.

```bash
uv tool install lockin-blocker
lockin start --for 2h
lockin status
```

**Browsers close on start.** Save your work first. Reopen them after start so
they pick up DoH-disabled policies. Default mode is **hardcore**. `lockin stop`
is refused. Use `lockin unlock --now` to end early, or `lockin start --soft` if
you want `lockin stop` to work.

The command is `lockin`. The PyPI package is `lockin-blocker`.

## Install

Python 3.11+, systemd, and nftables (or iptables).

```bash
uv tool install lockin-blocker          # recommended
pip install lockin-blocker
./install.sh                            # same as uv/pip from PyPI, not a local checkout
lockin update                           # upgrade the CLI package
```

From a git clone, use `./scripts/dev-install` instead of `install.sh`.

Read [CHANGELOG](CHANGELOG.md) when you upgrade.

## Existing users

The first `lockin start` or `lockin list` copies packaged `rules.yaml` to
`~/.config/lockin/rules.yaml` **once**. Later upgrades do not merge new
defaults into that file. Edit your copy after reading the changelog.

If you have more than one rule and no `default` key, pass `--rule` every time,
or add `default: social`, so `lockin start --for 2h` works.

## Usage

```
lockin start --for 2h                     Start with the default rule
lockin start --rule social --for 30m      Named blocklist
lockin start --rule social,news --for 2h  Stack blocklists
lockin start --until 17:00                Block until a clock time
lockin start --soft --for 30m             Allow lockin stop
lockin status                             Remaining time (wall clock)
lockin status --json                      Machine-readable status
lockin extend 30                          Add 30 minutes
lockin unlock 30                          Early unlock after a cooldown (default 30)
lockin unlock --now                       End now
lockin stop                               End block (soft sessions only)
lockin list                               List rules
lockin doctor                             Installation health
lockin cleanup                            Strip leftovers (ends a live session)
lockin uninstall                          Remove system files
lockin update                             Upgrade the CLI package
```

Durations are `30m`, `2h`, `1h30m`. Times are `17:00` or `9:30pm`.

### `lockin status --json`

When idle: `{"active": false}`.

When live:

| Key | Meaning |
|-----|---------|
| `active` | `true` |
| `rule_name` | Active rule(s), comma-joined if stacked |
| `end` | ISO end time (wall clock) |
| `remaining_seconds` | Seconds until `end` |
| `hosts` | `"active"` or `"missing"` |
| `hosts_count` | Domains in `/etc/hosts` |
| `firewall` | `"active"`, `"inactive"`, or `"unknown"` |
| `block_type` | Legacy `"blacklist"`. Every rule is a blocklist. |

### Expiry and teardown

`lockin status` is wall clock. Hosts, firewall, and policies come down on the
next watchdog tick (about 60s after `end`), not at the exact second. After a
reboot, QUIC can work until the first tick.

`lockin update` upgrades the CLI only. The copy under
`/usr/local/lib/lockin/pkg` refreshes on the next `lockin start`.

### Notifications

Expiry, soft `stop`, and `unlock --now` try `notify-send`. If it is missing,
the block still ends.

## Rules

Edit `~/.config/lockin/rules.yaml`. Every rule is a **blocklist**. Listed
hostnames go into `/etc/hosts`. lockin expands a few common subdomains and
aliases. No globs. No allowlist. A legacy `whitelists:` key is still loaded as
blocklists.

```yaml
default: social

blacklists:
  social:
    - twitter.com
    - reddit.com
```

## Firewall backends

**nftables** is the one `lockin status` can verify. **iptables** still rejects
UDP 443, but `firewall` in status JSON stays `"unknown"` because probe only
lists the nft table.

## Browser policies

lockin writes enterprise policies that turn off DNS-over-HTTPS. **Snap and
Flatpak Firefox** often ignore `/etc/firefox/policies`. Use distro Firefox, or
close and reopen after policies land. Browsers are killed on start and at
expiry. You reopen them.

## Troubleshooting

**Hosts missing during a live block.** Wait about a minute for the watchdog.
`lockin cleanup` ends the session.

**Sites still blocked after expiry.** Wait for the next tick, then
`lockin cleanup` if leftovers remain.

**`lockin stop` refused.** Hardcore mode. Use `lockin unlock --now` or wait.

**`lockin doctor` fails.** Fix the failed checks. Use `lockin cleanup` for
leftovers when no session should be running.

## Uninstall

```bash
lockin uninstall
uv tool uninstall lockin-blocker
```

## License

MIT
