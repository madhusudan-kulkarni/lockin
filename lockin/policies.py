"""Browser policy deployment — disables DNS-over-HTTPS in all browsers.

Writes managed policy JSON files that disable DoH in Firefox, Chrome,
Chromium, Brave, and Edge. Policies are applied on lockin start and
removed on lockin stop. Requires root (installed via sudo).

Based on piko's piko-browser-guard approach.
"""

import contextlib
import json
import os
import subprocess
from pathlib import Path

# Firefox policy (enterprise policies.json)
FIREFOX_POLICY_DIR = Path("/etc/firefox/policies")
FIREFOX_POLICY_FILE = FIREFOX_POLICY_DIR / "policies.json"

# Chromium-based browser policy directories
CHROMIUM_POLICIES = [
    Path("/etc/opt/chrome/policies/managed"),
    Path("/etc/chromium/policies/managed"),
    Path("/etc/opt/brave/policies/managed"),
    Path("/etc/opt/edge/policies/managed"),
]
POLICY_FILENAME = "lockin-doh.json"


def _sudo_write(path: Path, content: str) -> None:
    """Write a file as root (direct) or via sudo tee."""
    if os.geteuid() == 0:
        path.write_text(content)
        return
    subprocess.run(
        ["sudo", "tee", str(path)],
        input=content,
        capture_output=True,
        text=True,
        check=True,
        timeout=10,
    )


def _sudo_remove(path: Path) -> None:
    """Remove a file as root or via sudo rm."""
    if os.geteuid() == 0:
        path.unlink(missing_ok=True)
        return
    with contextlib.suppress(Exception):
        subprocess.run(
            ["sudo", "rm", "-f", str(path)],
            capture_output=True,
            timeout=10,
        )


def _sudo_mkdir(path: Path) -> None:
    """Create directory as root or via sudo mkdir -p."""
    if os.geteuid() == 0:
        path.mkdir(parents=True, exist_ok=True)
        return
    with contextlib.suppress(Exception):
        subprocess.run(
            ["sudo", "mkdir", "-p", str(path)],
            capture_output=True,
            timeout=10,
        )


def apply() -> None:
    """Apply browser policies to disable DoH in all supported browsers."""
    _apply_firefox()
    _apply_chromium()


def clear() -> None:
    """Remove all browser policies deployed by lockin."""
    _clear_firefox()
    _clear_chromium()


def _apply_firefox() -> None:
    """Write Firefox policies.json to disable DoH."""
    _sudo_mkdir(FIREFOX_POLICY_DIR)
    backup = _firefox_policy_backup_path()
    if FIREFOX_POLICY_FILE.exists() and not backup.exists():
        _sudo_write(backup, FIREFOX_POLICY_FILE.read_text())
    elif not FIREFOX_POLICY_FILE.exists() and not backup.exists():
        _sudo_write(backup, "")

    data = {}
    if FIREFOX_POLICY_FILE.exists():
        try:
            data = json.loads(FIREFOX_POLICY_FILE.read_text())
        except (json.JSONDecodeError, PermissionError):
            data = {}

    policies = data.get("policies", {})
    if not isinstance(policies, dict):
        policies = {}

    policies["DNSOverHTTPS"] = {"Enabled": False, "Locked": True}
    policies["LockinManaged"] = True
    data["policies"] = policies

    _sudo_write(FIREFOX_POLICY_FILE, json.dumps(data, indent=2) + "\n")


def _clear_firefox() -> None:
    """Remove lockin's entries from Firefox policies.json."""
    backup = _firefox_policy_backup_path()
    if backup.exists():
        original = backup.read_text()
        if original:
            _sudo_write(FIREFOX_POLICY_FILE, original)
        else:
            _sudo_remove(FIREFOX_POLICY_FILE)
        _sudo_remove(backup)
        return

    if not FIREFOX_POLICY_FILE.exists():
        return

    try:
        data = json.loads(FIREFOX_POLICY_FILE.read_text())
    except (json.JSONDecodeError, PermissionError):
        return

    policies = data.get("policies", {})
    if isinstance(policies, dict):
        policies.pop("LockinManaged", None)
        policies.pop("DNSOverHTTPS", None)
        if not policies:
            data.pop("policies", None)
        else:
            data["policies"] = policies

    if not data:
        _sudo_remove(FIREFOX_POLICY_FILE)
    else:
        _sudo_write(FIREFOX_POLICY_FILE, json.dumps(data, indent=2) + "\n")


def _firefox_policy_backup_path() -> Path:
    return FIREFOX_POLICY_FILE.with_name("policies.json.lockin-backup")


def _apply_chromium() -> None:
    """Write Chrome/Chromium/Brave/Edge managed policy to disable DoH."""
    payload = {"DnsOverHttpsMode": "off", "LockinManaged": True}
    content = json.dumps(payload, indent=2) + "\n"

    for policy_dir in CHROMIUM_POLICIES:
        _sudo_mkdir(policy_dir)
        _sudo_write(policy_dir / POLICY_FILENAME, content)


def _clear_chromium() -> None:
    """Remove lockin's Chrome/Chromium policies."""
    for policy_dir in CHROMIUM_POLICIES:
        _sudo_remove(policy_dir / POLICY_FILENAME)


def browser_policy_active() -> bool:
    """Check if browser policies are currently deployed."""
    if FIREFOX_POLICY_FILE.exists():
        try:
            data = json.loads(FIREFOX_POLICY_FILE.read_text())
            policies = data.get("policies", {})
            if isinstance(policies, dict) and policies.get("LockinManaged"):
                return True
        except Exception:
            pass

    for policy_dir in CHROMIUM_POLICIES:
        if (policy_dir / POLICY_FILENAME).exists():
            return True

    return False
