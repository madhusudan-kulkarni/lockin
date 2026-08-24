#!/usr/bin/env python3
"""lockin watchdog — systemd tick using the same hosts/nat/policies modules.

Copied under /usr/local/lib/lockin/pkg so root Python can import lockin
without the user's uv environment. Stdlib + lockin package only (no PyYAML).
"""

import contextlib
import json
import os
import sys
from datetime import datetime
from pathlib import Path

_state_env = os.environ.get("LOCKIN_STATE", "")
STATE_PATH = Path(_state_env) if _state_env else None
RESULT_FILE = Path("/tmp/lockin-watchdog-result")


def _log(msg: str) -> None:
    timestamp = datetime.now().isoformat()
    line = f"[{timestamp}] {msg}"
    if os.environ.get("LOCKIN_DEBUG") == "1":
        print(line, file=sys.stderr)
    with contextlib.suppress(Exception), open(RESULT_FILE, "a") as f:
        f.write(line + "\n")


def _warn(msg: str) -> None:
    timestamp = datetime.now().isoformat()
    line = f"[{timestamp}] lockin-watchdog: {msg}"
    print(line, file=sys.stderr)
    with contextlib.suppress(Exception), open(RESULT_FILE, "a") as f:
        f.write(line + "\n")


def _state_still_matches(state: dict) -> bool:
    if STATE_PATH is None or not STATE_PATH.exists():
        return False
    try:
        current = json.loads(STATE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    return current.get("start") == state.get("start")


def main() -> None:
    if not _state_env:
        sys.exit("LOCKIN_STATE environment variable not set")
    assert STATE_PATH is not None
    if not STATE_PATH.exists():
        _log("main: state file not found, exiting")
        return
    try:
        state = json.loads(STATE_PATH.read_text())
    except (json.JSONDecodeError, OSError) as e:
        _warn(f"failed to read state: {e}")
        return

    end_str = state.get("end", "")
    if not end_str:
        _log("main: no end time in state, exiting")
        return

    end = datetime.fromisoformat(end_str)
    _log(f"main: state end={end}, expired={datetime.now() >= end}")

    if datetime.now() >= end:
        _cleanup(state)
    else:
        _reapply(state)


def _cleanup(state: dict) -> None:
    from lockin import browser, nat, policies
    from lockin.hosts import remove_entries
    from lockin.watchdog_install import remove as remove_watchdog

    if not _state_still_matches(state):
        _log("cleanup: state changed — another block started, aborting")
        return
    _log("cleanup: starting")
    with contextlib.suppress(Exception):
        remove_entries()
    with contextlib.suppress(Exception):
        nat.reset()
    with contextlib.suppress(Exception):
        policies.clear()
    with contextlib.suppress(Exception):
        remove_watchdog()
    if _state_still_matches(state) and STATE_PATH is not None:
        STATE_PATH.unlink(missing_ok=True)
    _log("cleanup: killing browsers")
    with contextlib.suppress(Exception):
        browser.kill()
    with contextlib.suppress(Exception):
        from lockin.notify import notify_block_ended
        notify_block_ended()
    _log("cleanup: done")


def _reapply(state: dict) -> None:
    from lockin import nat, policies
    from lockin.hosts import add_entries, get_entries, lock_hosts

    if not _state_still_matches(state):
        _log("reapply: state changed — another block started, aborting")
        return
    domains = state.get("domains", [])
    hardcore = state.get("hardcore", True)
    _log(f"reapply: domains={len(domains)}, hardcore={hardcore}")

    with contextlib.suppress(Exception):
        current = get_entries()
        if set(current) != set(domains):
            add_entries(domains)
    with contextlib.suppress(Exception):
        nat.setup()
    with contextlib.suppress(Exception):
        policies.apply()
    if hardcore:
        with contextlib.suppress(Exception):
            lock_hosts()


if __name__ == "__main__":
    main()
