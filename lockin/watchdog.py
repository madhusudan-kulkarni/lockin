#!/usr/bin/env python3
"""lockin watchdog — self-contained, no lockin imports needed.

Runs as root via systemd. Reads state.json directly, manages
/etc/hosts, nftables, browser policies, and browser kill.
"""

import contextlib
import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

_state_env = os.environ.get("LOCKIN_STATE", "")
if not _state_env:
    sys.exit("LOCKIN_STATE environment variable not set")
STATE_PATH = Path(_state_env)
RESULT_FILE = Path("/tmp/lockin-watchdog-result")
HOSTS_FILE = Path("/etc/hosts").resolve()
MARKER_START = "# === lockin start ==="
MARKER_END = "# === lockin end ==="

BROWSERS = [
    "firefox", "firefox-bin",
    "google-chrome", "google-chrome-stable", "chrome",
    "chromium", "chromium-browser", "brave", "brave-browser",
    "microsoft-edge", "microsoft-edge-stable",
]

def _log(msg: str) -> None:
    """Log a debug message (stderr) and append to result file."""
    timestamp = datetime.now().isoformat()
    line = f"[{timestamp}] {msg}"
    if os.environ.get("LOCKIN_DEBUG") == "1":
        print(line, file=sys.stderr)
    with contextlib.suppress(Exception), open(RESULT_FILE, "a") as f:
        f.write(line + "\n")


def _warn(msg: str) -> None:
    """Log a warning that always appears in stderr and result file."""
    timestamp = datetime.now().isoformat()
    line = f"[{timestamp}] lockin-watchdog: {msg}"
    print(line, file=sys.stderr)
    with contextlib.suppress(Exception), open(RESULT_FILE, "a") as f:
        f.write(line + "\n")


def main() -> None:
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
    """Full cleanup: hosts, nftables, policies, browser kill.

    Only proceeds if the state file still matches the block we
    were asked to clean up.  If a new block was started in the
    meantime the stale cleanup must not delete its state.
    """
    if not _state_still_matches(state):
        _log("cleanup: state changed — another block started, aborting")
        return
    _log("cleanup: starting")
    _unlock_hosts()
    _remove_hosts_entries()
    _remove_nftables()
    _clear_policies()
    _remove_watchdog_units()
    if _state_still_matches(state):
        STATE_PATH.unlink(missing_ok=True)
    _log("cleanup: killing browsers")
    _kill_browsers(state)
    _log("cleanup: done")


def _reapply(state: dict) -> None:
    """Re-apply blocking if tampered with.

    Skips if the state file was replaced by a new block while we
    were running (e.g. a stale timer fire from a previous block).
    """
    if not _state_still_matches(state):
        _log("reapply: state changed — another block started, aborting")
        return
    _log(
        f"reapply: domains={len(state.get('domains', []))}, "
        f"hardcore={state.get('hardcore', True)}"
    )
    domains = state.get("domains", [])
    hardcore = state.get("hardcore", True)

    current = _get_hosts_entries()
    if set(current) != set(domains):
        _add_hosts_entries(domains)

    _setup_nftables()
    _apply_policies()

    if hardcore:
        with contextlib.suppress(Exception):
            subprocess.run(
                ["chattr", "+i", str(HOSTS_FILE)],
                capture_output=True, timeout=5,
            )


def _state_still_matches(state: dict) -> bool:
    """Return True if the on-disk state still belongs to the same block."""
    if not STATE_PATH.exists():
        return False
    try:
        current = json.loads(STATE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return False
    return current.get("start") == state.get("start")


# ——— hosts management ———

def _add_hosts_entries(domains: list[str]) -> None:
    lines = HOSTS_FILE.read_text().splitlines() if HOSTS_FILE.exists() else []
    lines = _strip_markers(lines)
    block = [MARKER_START]
    for d in sorted(set(domains)):
        block.append(f"127.0.0.2 {d} www.{d}")
        block.append(f"::1 {d} www.{d}")
    block.append(MARKER_END)
    if lines and lines[-1] != "":
        lines.append("")
    lines.extend(block)
    HOSTS_FILE.write_text("\n".join(lines) + "\n")
    with contextlib.suppress(Exception):
        subprocess.run(["resolvectl", "flush-caches"], capture_output=True, timeout=5)


def _get_hosts_entries() -> list[str]:
    if not HOSTS_FILE.exists():
        return []
    domains = set()
    in_block = False
    for line in HOSTS_FILE.read_text().splitlines():
        if MARKER_START in line:
            in_block = True
            continue
        if MARKER_END in line:
            break
        if in_block:
            parts = line.split()
            if parts and (parts[0] in ("127.0.0.2", "::1")):
                domains.add(parts[1])
    return sorted(domains)


def _remove_hosts_entries() -> None:
    lines = HOSTS_FILE.read_text().splitlines() if HOSTS_FILE.exists() else []
    HOSTS_FILE.write_text("\n".join(_strip_markers(lines)) + "\n")
    with contextlib.suppress(Exception):
        subprocess.run(["resolvectl", "flush-caches"], capture_output=True, timeout=5)


def _strip_markers(lines: list[str]) -> list[str]:
    result = []
    in_block = False
    for line in lines:
        if MARKER_START in line:
            in_block = True
            continue
        if MARKER_END in line:
            in_block = False
            continue
        if not in_block:
            result.append(line)
    while result and result[-1] == "":
        result.pop()
    return result


def _unlock_hosts() -> None:
    with contextlib.suppress(Exception):
        subprocess.run(
            ["chattr", "-i", str(HOSTS_FILE)],
            capture_output=True, timeout=5,
        )


# ——— nftables ———

def _setup_nftables() -> None:
    with contextlib.suppress(Exception):
        subprocess.run(["nft", "add", "table", "inet", "lockin"], capture_output=True)
        subprocess.run([
            "nft", "add", "chain", "inet", "lockin", "output",
            "{", "type", "filter", "hook", "output", "priority", "mangle", ";", "}",
        ], capture_output=True)
        subprocess.run([
            "nft", "flush", "chain", "inet", "lockin", "output",
        ], capture_output=True)
        subprocess.run([
            "nft", "add", "rule", "inet", "lockin", "output",
            "udp", "dport", "443", "reject",
        ], capture_output=True)


def _remove_nftables() -> None:
    with contextlib.suppress(Exception):
        subprocess.run(
            ["nft", "delete", "table", "inet", "lockin"], capture_output=True
        )


# ——— browser policies ———

POLICY_DIRS = [
    Path("/etc/firefox/policies"),
    Path("/etc/opt/chrome/policies/managed"),
    Path("/etc/chromium/policies/managed"),
    Path("/etc/opt/brave/policies/managed"),
    Path("/etc/opt/edge/policies/managed"),
]


def _apply_policies() -> None:
    for d in POLICY_DIRS:
        d.mkdir(parents=True, exist_ok=True)
    # Firefox: merge with existing policies.json
    _apply_firefox_policy()
    # Chromium: write standalone file
    payload = '{"DnsOverHttpsMode":"off"}\n'
    for d in POLICY_DIRS[1:]:
        (d / "lockin-doh.json").write_text(payload)


def _apply_firefox_policy() -> None:
    fp = POLICY_DIRS[0] / "policies.json"
    backup = _firefox_policy_backup_path()
    if fp.exists() and not backup.exists():
        backup.write_text(fp.read_text())
    elif not fp.exists() and not backup.exists():
        backup.write_text("")

    data = {}
    if fp.exists():
        with contextlib.suppress(Exception):
            data = json.loads(fp.read_text())
    policies = data.get("policies", {})
    if not isinstance(policies, dict):
        policies = {}
    policies["DNSOverHTTPS"] = {"Enabled": False, "Locked": True}
    policies["LockinManaged"] = True
    data["policies"] = policies
    fp.write_text(json.dumps(data, indent=2) + "\n")


def _clear_policies() -> None:
    _clear_firefox_policy()
    for d in POLICY_DIRS[1:]:
        with contextlib.suppress(Exception):
            (d / "lockin-doh.json").unlink()


def _clear_firefox_policy() -> None:
    fp = POLICY_DIRS[0] / "policies.json"
    backup = _firefox_policy_backup_path()
    if backup.exists():
        original = backup.read_text()
        if original:
            fp.write_text(original)
        else:
            fp.unlink(missing_ok=True)
        backup.unlink(missing_ok=True)
        return

    if not fp.exists():
        return

    try:
        data = json.loads(fp.read_text())
    except (json.JSONDecodeError, OSError) as e:
        _warn(f"failed to read Firefox policies for cleanup: {e}")
        return

    policies = data.get("policies", {})
    if isinstance(policies, dict):
        policies.pop("LockinManaged", None)
        policies.pop("DNSOverHTTPS", None)
        if policies:
            data["policies"] = policies
        else:
            data.pop("policies", None)

    if data:
        fp.write_text(json.dumps(data, indent=2) + "\n")
    else:
        fp.unlink(missing_ok=True)


def _firefox_policy_backup_path() -> Path:
    return POLICY_DIRS[0] / "policies.json.lockin-backup"


# ——— watchdog units ———

def _remove_watchdog_units() -> None:
    with contextlib.suppress(Exception):
        subprocess.run(
            ["systemctl", "disable", "--now", "lockin-watchdog.timer"],
            capture_output=True,
        )
        for f in [
            "/etc/systemd/system/lockin-watchdog.service",
            "/etc/systemd/system/lockin-watchdog.timer",
        ]:
            Path(f).unlink(missing_ok=True)
        subprocess.run(
            ["systemctl", "daemon-reload"], capture_output=True
        )


# ——— browser kill ———

def _kill_browsers(state: dict | None = None) -> None:
    """Kill all running browsers so stale DNS / policy caches are cleared.

    Reads ``browsers`` from *state* (saved by ``lockin start``) to
    report which browsers were killed.  Falls back to detecting
    currently-running browsers if state lacks the key.
    """
    pids = _get_browser_pids()
    _log(f"kill: found pids={pids}")

    saved = None
    if state:
        saved = state.get("browsers")
    if saved and isinstance(saved, list):
        browsers_killed = [b for b in saved if isinstance(b, str)]
    elif pids:
        browsers_killed = _get_running_names()
    else:
        browsers_killed = []

    for pid in pids:
        with contextlib.suppress(Exception):
            os.kill(pid, signal.SIGTERM)
    if pids:
        time.sleep(3)
    for pid in pids:
        if _pid_alive(pid):
            with contextlib.suppress(Exception):
                os.kill(pid, signal.SIGKILL)
    if pids:
        time.sleep(2)

    _log(f"kill: browsers killed: {browsers_killed}")
    if browsers_killed:
        with contextlib.suppress(Exception), open(RESULT_FILE, "a") as f:
            f.write(
                f"[{datetime.now().isoformat()}] browsers were running: "
                + ", ".join(browsers_killed)
                + "\n  They have been closed.  Reopen them manually.\n"
            )


def _get_browser_pids() -> list[int]:
    pids = []
    for name in BROWSERS:
        try:
            r = subprocess.run(
                ["pgrep", "-x", name],
                capture_output=True, text=True, timeout=5,
            )
            for line in r.stdout.strip().splitlines():
                if line.strip():
                    pids.append(int(line.strip()))
        except Exception:
            pass
    return list(set(pids))


def _get_running_names() -> list[str]:
    return [n for n in BROWSERS if _get_browser_pids_for(n)]


def _get_browser_pids_for(name: str) -> list[int]:
    try:
        r = subprocess.run(
            ["pgrep", "-x", name],
            capture_output=True, text=True, timeout=5,
        )
        return [
            int(ln) for ln in r.stdout.strip().splitlines() if ln.strip()
        ]
    except Exception:
        return []


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False


if __name__ == "__main__":
    main()
