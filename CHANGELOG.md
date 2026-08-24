# Changelog

## 2026.8.2 — 2026-08-24

- Ship-honesty pass: CLI copy, status messaging, README, doctor warnings.
- iptables QUIC rules are idempotent (`-C` before `-A`); watchdog ticks no
  longer pile duplicate OUTPUT rules.
- `lockin doctor` warns when user rules.yaml has multiple rules but no
  `default:` (does not fail solely for that).
- Status with missing hosts during a live block points to the watchdog, not
  `lockin cleanup`.

## 2026.8.1 — 2026-08-24

- Hostname expansion: common subdomains (`m`, `old`, …) and aliases
  (`youtu.be`, `fb.com`, `old.reddit.com`). No glob matching.
- Stack rules: `--rule social,news` or repeated `-r`.
- Optional `--rule`; `default: social` in packaged rules.yaml.
- `lockin status --json` for status bars.
- Desktop notification when a block ends (expiry, soft stop, unlock --now).

## 2026.8.0 — 2026-08-24

Breaking: whitelist invert never worked. Every rule is a blocklist.
The `whitelists:` YAML key is still loaded as a blocklist alias.
Default `coding` / `email` rules are gone. Path and glob patterns in
the default file are gone.

- One `end_session` teardown for stop, unlock --now, cleanup, uninstall, and expiry.
- `lockin cleanup` strips leftovers even when `state.json` is missing.
- Failed `start` rolls back hosts/nft/policies/watchdog.
- `unlock` queues an earlier end after a cooldown; it no longer lengthens the block.
- `--until` accepts `9:30pm` as well as `17:00`.
- Watchdog runs the same `hosts` / `nat` / `policies` modules (package copied to `/usr/local/lib/lockin/pkg`).
- Removed unused `scheduler.py` and hidden `reset` command.
- `lockin doctor` treats a live session as healthy and exits non-zero on failure.

## 1.0.0 — 2026-05-24

Initial release.
