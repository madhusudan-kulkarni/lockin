"""Watchdog systemd unit installation and removal.

Installs / removes the lockin-watchdog systemd timer that runs
the self-contained watchdog.py script as root.
"""

import contextlib
import os
import subprocess
import textwrap
from pathlib import Path

STATE_FILE = Path.home() / ".config" / "lockin" / "state.json"


def install() -> None:
    """Install systemd watchdog timer.  Copies watchdog.py to
    /usr/local/lib so it can run without accessing the user's
    home directory."""
    watchdog_src = str(Path(__file__).parent / "watchdog.py")
    watchdog_dst = "/usr/local/lib/lockin/watchdog.py"

    user = os.environ.get("USER", "root")
    display = os.environ.get("DISPLAY", "")
    wayland = os.environ.get("WAYLAND_DISPLAY", "")
    xauth = os.environ.get("XAUTHORITY", "")
    xdg_runtime = os.environ.get("XDG_RUNTIME_DIR", "")
    dbus = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")

    env_lines = [f"Environment=WATCHDOG_USER={user}"]
    home_dir = os.path.expanduser(f"~{user}") if user != "root" else "/root"
    env_lines.append(f"Environment=HOME={home_dir}")
    if display:
        env_lines.append(f"Environment=DISPLAY={display}")
    if wayland:
        env_lines.append(f"Environment=WAYLAND_DISPLAY={wayland}")
    if xauth:
        env_lines.append(f"Environment=XAUTHORITY={xauth}")
    if xdg_runtime:
        env_lines.append(f"Environment=XDG_RUNTIME_DIR={xdg_runtime}")
    if dbus:
        env_lines.append(f"Environment=DBUS_SESSION_BUS_ADDRESS={dbus}")

    env_block = "\n    ".join(env_lines)
    service = textwrap.dedent(f"""\
    [Unit]
    Description=lockin watchdog — re-apply blocking rules

    [Service]
    Type=oneshot
    Environment=LOCKIN_STATE={STATE_FILE}
    Environment=LOCKIN_DEBUG=1
    {env_block}
    ExecStart=/usr/bin/python3 {watchdog_dst}
    """)

    timer = textwrap.dedent("""\
    [Unit]
    Description=lockin watchdog timer

    [Timer]
    OnBootSec=1min
    OnUnitActiveSec=1min

    [Install]
    WantedBy=timers.target
    """)

    # Stage 1: stop any old instances (best-effort)
    with contextlib.suppress(Exception):
        subprocess.run(
            ["sudo", "systemctl", "stop", "lockin-watchdog.timer"],
            capture_output=True, timeout=10,
        )
        subprocess.run(
            ["sudo", "systemctl", "stop", "lockin-watchdog.service"],
            capture_output=True, timeout=10,
        )
        subprocess.run(
            ["sudo", "rm", "-f",
             "/etc/systemd/system/lockin-watchdog.service",
             "/etc/systemd/system/lockin-watchdog.timer"],
            capture_output=True, timeout=10,
        )
        subprocess.run(
            ["sudo", "pkill", "-f", "lockin/watchdog.py"],
            capture_output=True, timeout=10,
        )

    # Stage 2: install files — each step must succeed
    subprocess.run(
        ["sudo", "mkdir", "-p", "/usr/local/lib/lockin"],
        capture_output=True, timeout=10, check=True,
    )
    subprocess.run(
        ["sudo", "cp", watchdog_src, watchdog_dst],
        capture_output=True, timeout=10, check=True,
    )
    subprocess.run(
        ["sudo", "tee", "/etc/systemd/system/lockin-watchdog.service"],
        input=service, capture_output=True, text=True,
        timeout=10, check=True,
    )
    subprocess.run(
        ["sudo", "tee", "/etc/systemd/system/lockin-watchdog.timer"],
        input=timer, capture_output=True, text=True,
        timeout=10, check=True,
    )
    subprocess.run(
        ["sudo", "systemctl", "daemon-reload"],
        capture_output=True, timeout=10, check=True,
    )
    subprocess.run(
        ["sudo", "systemctl", "enable", "--now", "lockin-watchdog.timer"],
        capture_output=True, timeout=10, check=True,
    )


def remove() -> None:
    """Remove systemd watchdog timer and all associated files."""
    # Best-effort: units may already be gone
    with contextlib.suppress(Exception):
        subprocess.run(
            [
                "sudo", "systemctl", "disable", "--now",
                "lockin-watchdog.timer",
            ],
            capture_output=True, timeout=10,
        )
        subprocess.run(
            ["sudo", "rm", "-f",
             "/etc/systemd/system/lockin-watchdog.service",
             "/etc/systemd/system/lockin-watchdog.timer"],
            capture_output=True, timeout=10,
        )
        subprocess.run(
            ["sudo", "rm", "-rf", "/usr/local/lib/lockin"],
            capture_output=True, timeout=10,
        )
    subprocess.run(
        ["sudo", "systemctl", "daemon-reload"],
        capture_output=True, timeout=10, check=True,
    )
