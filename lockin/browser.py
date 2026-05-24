"""Browser management — graceful kill to apply policy changes.

When browser policies are deployed, browsers must be closed so they
pick up the new config on next launch.  Sends SIGTERM, waits for
graceful shutdown, then SIGKILL for any remaining processes.
"""

import contextlib
import os
import signal
import subprocess
import time

BROWSERS = [
    "firefox", "firefox-bin",
    "google-chrome", "google-chrome-stable", "chrome",
    "chromium", "chromium-browser",
    "brave", "brave-browser",
    "microsoft-edge", "microsoft-edge-stable",
]

GRACE_SECONDS = 5
KILL_TIMEOUT = 8


def _get_pids() -> list[int]:
    """Get PIDs of all running browser processes."""
    pids: list[int] = []
    for name in BROWSERS:
        try:
            result = subprocess.run(
                ["pgrep", "-x", name],
                capture_output=True, text=True, timeout=5,
            )
            for line in result.stdout.strip().splitlines():
                if line.strip():
                    pids.append(int(line.strip()))
        except (subprocess.TimeoutExpired, ValueError):
            pass
    return list(set(pids))


def kill() -> list[str]:
    """Kill all running browsers and return their names.

    Sends SIGTERM, waits up to KILL_TIMEOUT seconds, then SIGKILL
    for remaining processes.  Returns the list of browser binary
    names that were killed so the caller can notify the user.
    """
    pids = _get_pids()
    if not pids:
        return []

    running = _get_running_names()

    for pid in pids:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(pid, signal.SIGTERM)

    for _ in range(KILL_TIMEOUT):
        time.sleep(1)
        still_running = [pid for pid in pids if _pid_alive(pid)]
        if not still_running:
            break

    for pid in pids:
        if _pid_alive(pid):
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(pid, signal.SIGKILL)

    return running


def _get_running_names() -> list[str]:
    """Get names of browser binaries currently running."""
    running: list[str] = []
    for name in BROWSERS:
        try:
            result = subprocess.run(
                ["pgrep", "-x", name],
                capture_output=True, text=True, timeout=5,
            )
            if result.stdout.strip():
                running.append(name)
        except subprocess.TimeoutExpired:
            pass
    return running


def _pid_alive(pid: int) -> bool:
    """Check if a process is still running."""
    try:
        os.kill(pid, 0)
        return True
    except (ProcessLookupError, PermissionError):
        return False
