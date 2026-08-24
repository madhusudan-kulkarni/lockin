# lockin

[![CI](https://github.com/madhusudan-kulkarni/lockin/actions/workflows/ci.yml/badge.svg)](https://github.com/madhusudan-kulkarni/lockin/actions)
[![PyPI](https://img.shields.io/pypi/v/lockin-blocker)](https://pypi.org/project/lockin-blocker/)

Block distracting websites at the system level. No proxy, no browser extension,
no MITM certificate.

lockin writes blocked domains to `/etc/hosts` and rejects QUIC/HTTP3 (UDP 443)
via nftables or iptables for **every destination** on the machine. A systemd
watchdog re-applies blocks every ~60 seconds.

## Quick start

Linux with systemd required. Run lockin as your normal user — `sudo` is used
internally for `/etc/hosts` and firewall rules. Do **not** run `sudo lockin`.

```bash
uv tool install lockin-blocker    # PyPI; ./install.sh does the same
lockin start --for 2h
lockin status
```

**Browsers close on start.** Save your work first. Reopen browsers after start
so they pick up DoH-disabled policies. Default mode is **hardcore**: `lockin
stop` is refused; use `lockin unlock --now` for emergency access, or
`lockin start --soft` if you want `lockin stop` to work.

## Install

Requires Python ≥3.11, systemd, and nftables (or iptables).

```bash
uv tool install lockin-blocker          # recommended
pip install lockin-blocker              # pip / pipx
./install.sh                            # wrapper around uv/pip from PyPI
lockin update                           # upgrade in place
```

See [CHANGELOG](CHANGELOG.md) when upgrading between releases.

## Existing users

On first `lockin start` or `lockin list`, lockin copies the packaged
`rules.yaml` to `~/.config/lockin/rules.yaml` **once**. Upgrades do not merge
new defaults into your file — review [CHANGELOG](CHANGELOG.md) and edit your
copy if needed.

If you have more than one rule and no `default:` key, pass `--rule` every
time or add e.g. `default: social` so `lockin start --for 2h` works.

## Usage

```
lockin start --for 2h                   Start with the default rule
lockin start --rule social --for 30m    Named blocklist
lockin start --rule social,news --for 2h  Stack blocklists
lockin start --until 17:00              Block until a clock time
lockin start --soft --for 30m           Allow lockin stop
lockin status                           Remaining time (wall clock)
lockin status --json                    Machine-readable status
lockin extend 30                        Add 30 minutes
lockin unlock 30                        Early unlock after cooldown
lockin unlock --now                     Emergency unlock
lockin stop                             End block (--soft only)
lockin list                             List rules
lockin doctor                           Installation health
lockin cleanup                          Remove leftovers (not during live block)
lockin uninstall                        Clean system files
lockin update                           Upgrade CLI package
```

Durations: `30m`, `2h`, `1h30m`. Times: `17:00` or `9:30pm`.

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

`block_type` is also present (legacy value `blacklist`; every rule is a
blocklist).

### Expiry and teardown

`lockin status` shows wall-clock time remaining. Actual teardown (hosts,
firewall, policies) runs on the next watchdog tick (~60s), not the instant
`end` passes. After reboot, QUIC may work until the first tick re-applies
rules.

`lockin update` upgrades the CLI only. The watchdog package copied to
`/usr/local/lib/lockin/pkg` updates on the next `lockin start`.

### Notifications

Desktop notifications (expiry, soft `stop`, `unlock --now`) use `notify-send`
when available. Best-effort only.

## Rules

Edit `~/.config/lockin/rules.yaml`. Every rule is a **blocklist** — listed
hostnames go to `/etc/hosts`. lockin also expands common subdomains and
aliases. No globs, no allowlist mode. Legacy `whitelists:` is loaded as
blocklists.

```yaml
default: social

blacklists:
  social:
    - twitter.com
    - reddit.com
```

## Firewall backends

**nftables** is the primary backend; `lockin status` can verify the lockin
table. **iptables** works as a fallback but `firewall` in status JSON is
`unknown` (probe only checks nft).

## Browser policies

lockin deploys enterprise policies to disable DNS-over-HTTPS. **Snap and
Flatpak Firefox** may ignore `/etc/firefox/policies` — use distro Firefox, or
close and reopen after policies are applied. Browsers are killed on start and
at expiry; reopen manually.

## Troubleshooting

**Hosts missing during a live block.** Wait for the watchdog (~1 min). Do not
run `lockin cleanup` — that ends the session.

**Sites still blocked after expiry.** Run `lockin cleanup`.

**`lockin stop` refused.** Hardcore mode. Use `lockin unlock --now` or wait.

**`lockin doctor` fails.** Fix failed checks; use `lockin cleanup` for
leftovers.

## Uninstall

```bash
lockin uninstall
uv tool uninstall lockin-blocker
```

## License

MIT
