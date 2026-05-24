# AGENTS.md — lockin

> For AI coding agents working on this project.

## Setup

```bash
uv sync --extra dev
uv run lockin --help
```

## Rules

1. **TDD always.** Write the test first, watch it fail, then implement.
2. **Conventional commits:** `feat(scope):`, `fix(scope):`, `test(scope):`, `refactor(scope):`, `chore:`.
3. **Don't break the host.** Never run `nft delete table` or `sudo tee /etc/hosts` without explicit approval.
4. **Verify before claiming done.** Run `uv run ruff check . && uv run pytest` after every task.
5. **Clear uv cache before local install.** Run `uv cache clean` before `uv tool install --force`. The cache can hold a stale build.

## Commands

```bash
uv run ruff check .          # lint
uv run ruff check --fix .    # auto-fix
uv run pytest                # all tests
uv run pytest -v -k "name"   # specific test
uv run lockin --help         # CLI help
./scripts/dev-install        # clean old install + reinstall from local source
./scripts/test-watchdog      # full e2e test: install → block → wait → verify restart
```

## Architecture

lockin uses `/etc/hosts` + nftables for system-level domain blocking. No proxy, no certs, no browser extensions.

| Module | Responsibility |
|--------|---------------|
| `lockin/cli.py` | Click commands, arg parsing, output formatting |
| `lockin/block.py` | Orchestration: start/stop/status via /etc/hosts + nftables |
| `lockin/browser.py` | Browser detection and graceful kill (no relaunch) |
| `lockin/hosts.py` | /etc/hosts manager — adds/removes blocked domain entries |
| `lockin/nat.py` | nftables/iptables QUIC sinkhole (UDP 443 drop) |
| `lockin/policies.py` | Browser policy deployment (Firefox + Chromium DoH disable) |
| `lockin/scheduler.py` | systemd/at/cron/thread unblock scheduling |
| `lockin/watchdog.py` | Self-contained expiry watchdog — runs as root via systemd |

### Browser handling

Browsers are **killed only, never relaunched** (relaunch from a root systemd context
is unreliable on Wayland).  `lockin start` kills browsers so they pick up DoH-disabled
policies on next launch.  The watchdog kills browsers at expiry so stale DNS / policy
caches are cleared.  Users reopen browsers manually.

### State file

`~/.config/lockin/state.json` tracks the active block:

```json
{
  "rule_name": "social",
  "block_type": "blacklist",
  "domains": ["twitter.com", "..."],
  "start": "2026-05-24T21:00:00",
  "end": "2026-05-24T22:00:00",
  "hardcore": true,
  "browsers": ["firefox", "chrome"]
}
```

The `browsers` field records what was killed at block start so the watchdog can
report it in `/tmp/lockin-watchdog-result`.

## Dependencies

- `click` — CLI framework
- `pyyaml` — rules file parsing
- `ruff`, `pytest` — dev only
