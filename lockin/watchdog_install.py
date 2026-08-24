"""Watchdog systemd unit installation and removal.

Copies the lockin package to /usr/local/lib/lockin/pkg so the timer
runs the same hosts/nat/policies code as the CLI.
"""

import contextlib
import os
import subprocess
import textwrap
from pathlib import Path

STATE_FILE = Path.home() / ".config" / "lockin" / "state.json"
PKG_ROOT = "/usr/local/lib/lockin/pkg"


def _root(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    if os.geteuid() != 0:
        cmd = ["sudo", *cmd]
    return subprocess.run(cmd, **kwargs)


def install() -> None:
    """Install systemd watchdog timer and copy the lockin package."""
    pkg_src = str(Path(__file__).resolve().parent)

    user = os.environ.get("USER", "root")
    home_dir = os.path.expanduser(f"~{user}") if user != "root" else "/root"
    xdg = os.environ.get("XDG_RUNTIME_DIR", "")
    dbus = os.environ.get("DBUS_SESSION_BUS_ADDRESS", "")
    if not dbus and xdg:
        dbus = f"unix:path={xdg}/bus"

    env_lines = [
        f"Environment=LOCKIN_STATE={STATE_FILE}",
        "Environment=LOCKIN_DEBUG=1",
        f"Environment=HOME={home_dir}",
        f"Environment=PYTHONPATH={PKG_ROOT}",
        f"Environment=WATCHDOG_USER={user}",
    ]
    if xdg:
        env_lines.append(f"Environment=XDG_RUNTIME_DIR={xdg}")
    if dbus:
        env_lines.append(f"Environment=DBUS_SESSION_BUS_ADDRESS={dbus}")
    env_block = "\n    ".join(env_lines)

    service = textwrap.dedent(f"""\
    [Unit]
    Description=lockin watchdog — re-apply blocking rules

    [Service]
    Type=oneshot
    {env_block}
    ExecStart=/usr/bin/python3 -m lockin.watchdog
    """)

    timer = textwrap.dedent("""\
    [Unit]
    Description=lockin watchdog timer

    [Timer]
    OnBootSec=1min
    OnActiveSec=1min
    OnUnitActiveSec=1min

    [Install]
    WantedBy=timers.target
    """)

    with contextlib.suppress(Exception):
        _root(
            ["systemctl", "stop", "lockin-watchdog.timer"],
            capture_output=True, timeout=10,
        )
        _root(
            ["systemctl", "stop", "lockin-watchdog.service"],
            capture_output=True, timeout=10,
        )
        _root(
            ["rm", "-f",
             "/etc/systemd/system/lockin-watchdog.service",
             "/etc/systemd/system/lockin-watchdog.timer"],
            capture_output=True, timeout=10,
        )

    _root(
        ["rm", "-rf", PKG_ROOT],
        capture_output=True, timeout=10, check=True,
    )
    _root(
        ["mkdir", "-p", PKG_ROOT],
        capture_output=True, timeout=10, check=True,
    )
    _root(
        ["cp", "-a", pkg_src, f"{PKG_ROOT}/lockin"],
        capture_output=True, timeout=10, check=True,
    )
    _root(
        ["tee", "/etc/systemd/system/lockin-watchdog.service"],
        input=service, capture_output=True, text=True,
        timeout=10, check=True,
    )
    _root(
        ["tee", "/etc/systemd/system/lockin-watchdog.timer"],
        input=timer, capture_output=True, text=True,
        timeout=10, check=True,
    )
    _root(
        ["systemctl", "daemon-reload"],
        capture_output=True, timeout=10, check=True,
    )
    _root(
        ["systemctl", "enable", "--now", "lockin-watchdog.timer"],
        capture_output=True, timeout=10, check=True,
    )


def remove() -> None:
    """Remove systemd watchdog timer and copied package files."""
    with contextlib.suppress(Exception):
        _root(
            ["systemctl", "disable", "--now", "lockin-watchdog.timer"],
            capture_output=True, timeout=10,
        )
        _root(
            ["rm", "-f",
             "/etc/systemd/system/lockin-watchdog.service",
             "/etc/systemd/system/lockin-watchdog.timer"],
            capture_output=True, timeout=10,
        )
        _root(
            ["rm", "-rf", "/usr/local/lib/lockin"],
            capture_output=True, timeout=10,
        )
    _root(
        ["systemctl", "daemon-reload"],
        capture_output=True, timeout=10, check=True,
    )
