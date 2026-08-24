"""Best-effort desktop notification when a block ends."""

import contextlib
import os
import subprocess

TITLE = "lockin"
BODY = "Block ended. Reopen your browsers."


def notify_block_ended() -> None:
    """Show a notification as the session user. Never raises."""
    with contextlib.suppress(Exception):
        _notify()


def _notify() -> None:
    user = (
        os.environ.get("WATCHDOG_USER")
        or os.environ.get("SUDO_USER")
        or os.environ.get("USER")
        or ""
    )
    xdg = os.environ.get("XDG_RUNTIME_DIR", "")
    dbus = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
    if not dbus and xdg:
        dbus = f"unix:path={xdg}/bus"

    if os.geteuid() == 0 and user and user != "root":
        cmd = ["sudo", "-u", user, "env"]
        if xdg:
            cmd.append(f"XDG_RUNTIME_DIR={xdg}")
        if dbus:
            cmd.append(f"DBUS_SESSION_BUS_ADDRESS={dbus}")
        cmd.extend(["notify-send", TITLE, BODY])
        subprocess.run(cmd, capture_output=True, timeout=5)
        return

    env = os.environ.copy()
    if xdg:
        env["XDG_RUNTIME_DIR"] = xdg
    if dbus:
        env["DBUS_SESSION_BUS_ADDRESS"] = dbus
    subprocess.run(
        ["notify-send", TITLE, BODY],
        env=env,
        capture_output=True,
        timeout=5,
    )
