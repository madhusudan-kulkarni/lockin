# Changelog

## 2026.8.2 (2026-08-24)

- `lockin start` tells you to reopen browsers now. It no longer prints Firefox
  Settings steps. Hardcore sessions mention `unlock --now`.
- Missing hosts during a live block points at the watchdog. It does not
  recommend `lockin cleanup`.
- iptables QUIC rules check before append, so watchdog ticks do not stack
  duplicate OUTPUT rejects.
- `lockin doctor` warns (still passes) when user rules have several names and
  no `default` key.
- README covers copy-once rules, expiry lag, Snap/Flatpak Firefox, and
  `install.sh` installing from PyPI.

## 2026.8.1 (2026-08-24)

- Hostname expansion for common subdomains (`m`, `old`, …) and aliases
  (`youtu.be`, `fb.com`, `old.reddit.com`). No glob matching.
- Stack rules with `--rule social,news` or repeated `-r`.
- Optional `--rule`. Packaged rules include `default: social`.
- `lockin status --json` for status bars.
- Desktop notification when a block ends (expiry, soft stop, `unlock --now`).

## 2026.8.0 (2026-08-24)

Breaking. Whitelist invert never worked. Every rule is a blocklist.
The `whitelists:` YAML key still loads as a blocklist alias.
Default `coding` / `email` rules are gone. Path and glob patterns in
the packaged file are gone.

- One `end_session` teardown for stop, `unlock --now`, cleanup, and uninstall.
  Expiry still runs `watchdog._cleanup`.
- `lockin cleanup` strips leftovers even when `state.json` is missing.
- Failed `start` rolls back hosts, nft, policies, and the watchdog.
- `unlock` queues an earlier end after a cooldown. It does not lengthen the
  block.
- `--until` accepts `9:30pm` as well as `17:00`.
- Watchdog runs the same `hosts` / `nat` / `policies` modules from a copy at
  `/usr/local/lib/lockin/pkg`.
- Removed unused `scheduler.py` and the hidden `reset` command.
- `lockin doctor` treats a live session as healthy and exits non-zero on
  failure.

## 1.0.0 (2026-05-24)

Initial release.
