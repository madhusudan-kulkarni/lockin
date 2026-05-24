# lockin

[![CI](https://github.com/madhusudan-kulkarni/lockin/actions/workflows/ci.yml/badge.svg)](https://github.com/madhusudan-kulkarni/lockin/actions)
[![PyPI](https://img.shields.io/pypi/v/lockin-blocker)](https://pypi.org/project/lockin-blocker/)

Block distracting websites at the system level.  No proxy, no browser
extension, no MITM certificate.

lockin writes blocked domains to `/etc/hosts` and blocks QUIC/HTTP3 via
nftables.  Every application on your system is affected until the timer
expires.  A systemd watchdog re-applies blocks every 60 seconds to
prevent tampering.

## Quick start

```bash
uv tool install lockin-blocker
lockin start --rule social --for 2h
lockin status
```

## Install

Requires Python ≥3.11, systemd, and nftables (or iptables).  `sudo` is
used for `/etc/hosts` writes and firewall rules.

```bash
uv tool install lockin-blocker          # recommended (uv)
pip install lockin-blocker              # pip / pipx
```

Or install the latest from git:

```bash
uv tool install git+https://github.com/madhusudan-kulkarni/lockin.git
```

## Usage

```
lockin start --rule <name> --for 30m    Start a blocking session
lockin start --rule <name> --until 17:00  Block until a specific time
lockin start --soft --rule <name> --for 30m  Allow early stop
lockin status                             Show remaining time
lockin extend 30                          Add 30 minutes to current block
lockin unlock 30                          Queue early unlock (30 min cooldown)
lockin unlock --now                       Emergency immediate unlock
lockin stop                               End the block (--soft mode only)
lockin list                               List all rules
lockin doctor                             Check installation health
lockin cleanup                            Remove leftovers from crashes
lockin uninstall                          Clean system files, print removal steps
```

Durations accept `30m`, `2h`, `1h30m`.  Times accept `17:00` or `9:30pm`.

## What happens during a block

1. Blocked domains are written to `/etc/hosts` and the file is locked
   with `chattr +i` — it cannot be edited, not even with `sudo`.
2. Browser enterprise policies are deployed to disable DNS-over-HTTPS
   in Firefox, Chrome, Chromium, Brave, and Edge.
3. Open browsers are **closed** so they pick up the DoH-disabled
   configuration on next launch.  You reopen them manually.
4. QUIC/HTTP3 (UDP 443) is rejected via nftables so browsers fall back
   to standard TCP/HTTPS, which respects `/etc/hosts`.
5. A systemd watchdog timer fires every 60 seconds to re-apply blocks
   if they are tampered with.
6. When the timer expires the watchdog removes all blocks, clears
   policies, and closes browsers so cached DNS entries are flushed.
   Reopen your browsers manually.

## Rules

Rules live in `~/.config/lockin/rules.yaml`.  A default file is
copied there on first run.  Edit it to add your own domains.

```yaml
whitelists:       # block everything EXCEPT these
  coding:
    - github.com
    - stackoverflow.com
    - docs.python.org

blacklists:       # allow everything EXCEPT these
  social:
    - twitter.com
    - facebook.com
    - reddit.com
    - youtube.com
```

## Troubleshooting

**Sites still load in Firefox.**  Firefox DNS-over-HTTPS was not
disabled.  Close Firefox and reopen it — the enterprise policy
deployed by lockin takes effect on the next launch.

**Sites still blocked after the timer expires.**  Run `lockin cleanup`
to force-remove leftover hosts entries and firewall rules.

**`lockin stop` fails with "Hardcore mode is active."**  You started
the block without `--soft`.  Use `lockin unlock --now` for emergency
access, or wait for the timer.

## Uninstall

```bash
lockin uninstall                     # removes systemd units, policies
uv tool uninstall lockin-blocker     # removes the binary
```

Or with pip:

```bash
lockin uninstall
pip uninstall lockin-blocker
```

## License

MIT
