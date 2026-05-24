"""Scheduling: systemd timer, at, cron, and thread-based unblock scheduling."""

import datetime
import os
import shutil
import subprocess
import threading


def schedule(when: datetime.datetime, reset_command: str) -> tuple[str, str]:
    """Schedule a reset at the given time.

    Returns (method, job_id) where method is one of:
    "systemd", "at", "cron", "thread".
    """
    if _systemd_available():
        return ("systemd", _schedule_systemd(when, reset_command))
    if _at_available():
        return ("at", _schedule_at(when, reset_command))
    if _cron_available():
        return ("cron", _schedule_cron(when, reset_command))
    return ("thread", _schedule_thread(when, reset_command))


def cancel(method: str, job_id: str) -> None:
    """Cancel a scheduled job."""
    if method == "systemd":
        cmd = ["systemctl", "stop", f"{job_id}.timer"]
        if os.geteuid() != 0:
            cmd = ["sudo"] + cmd
        subprocess.run(cmd, capture_output=True)
    elif method == "at":
        subprocess.run(
            ["atrm", job_id],
            capture_output=True,
        )
    elif method == "cron":
        try:
            result = subprocess.run(
                ["crontab", "-l"],
                capture_output=True, text=True,
            )
            lines = result.stdout.splitlines()
            filtered = [
                line for line in lines
                if "lockin" not in line
            ]
            if filtered != lines:
                subprocess.run(
                    ["crontab", "-"],
                    input="\n".join(filtered) + "\n",
                    capture_output=True, text=True,
                )
        except subprocess.CalledProcessError:
            pass
    # "thread" — noop


def _systemd_available() -> bool:
    return (
        shutil.which("systemctl") is not None
        and os.path.exists("/run/systemd/system")
    )


def _at_available() -> bool:
    return shutil.which("at") is not None


def _cron_available() -> bool:
    return shutil.which("crontab") is not None


def _schedule_systemd(when: datetime.datetime, reset_command: str) -> str:
    """Schedule via systemd-run transient timer. Returns unit name."""
    unit_name = "lockin-reset"
    calendar = when.strftime("%Y-%m-%d %H:%M:%S")
    subprocess.run(
        [
            "sudo", "systemd-run",
            "--on-calendar", calendar,
            "--unit", unit_name,
            "--description", "lockin block reset timer",
            "--", "bash", "-c", reset_command,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return unit_name


def _schedule_at(when: datetime.datetime, reset_command: str) -> str:
    """Schedule via at command. Returns job ID string."""
    time_str = when.strftime("%H:%M %Y-%m-%d")
    result = subprocess.run(
        ["at", time_str],
        input=reset_command,
        capture_output=True,
        text=True,
        check=True,
    )
    # at outputs "job N at ..." to stderr
    output = result.stderr.strip() or result.stdout.strip()
    parts = output.split()
    if len(parts) >= 2 and parts[0] == "job":
        return parts[1]
    return output


def _schedule_cron(when: datetime.datetime, reset_command: str) -> str:
    """Schedule via crontab. Returns cron entry identifier."""
    cron_line = (
        f"{when.minute} {when.hour} {when.day} {when.month} * "
        f"{reset_command}  # lockin-reset"
    )
    try:
        existing = subprocess.run(
            ["crontab", "-l"],
            capture_output=True, text=True,
        )
        content = existing.stdout
    except subprocess.CalledProcessError:
        content = ""

    lines = content.splitlines()
    lines = [
        line for line in lines
        if "lockin-reset" not in line
    ]
    lines.append(cron_line)

    subprocess.run(
        ["crontab", "-"],
        input="\n".join(lines) + "\n",
        capture_output=True,
        text=True,
        check=True,
    )
    return "cron-entry"


def _schedule_thread(when: datetime.datetime, reset_command: str) -> str:
    """Schedule via threading.Timer. Returns thread identifier."""
    delay = (when - datetime.datetime.now()).total_seconds()
    if delay < 0:
        delay = 0
    timer = threading.Timer(
        delay,
        lambda: subprocess.run(
            reset_command, shell=True,
            capture_output=True,
        ),
    )
    timer.daemon = True
    timer.start()
    return "thread"
