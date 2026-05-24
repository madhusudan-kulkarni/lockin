"""Manage /etc/hosts entries for blocking domains.

Uses marker lines to delimit lockin's entries, making cleanup safe
and predictable. Always adds IPv4 (127.0.0.2) and IPv6 (::1) entries.
"""

import contextlib
import os
import re
import subprocess
from pathlib import Path

HOSTS_PATH = Path("/etc/hosts")
MARKER_START = "# === lockin start ==="
MARKER_END = "# === lockin end ==="


def _resolve_path() -> Path:
    """Resolve the real hosts file path (follows symlinks)."""
    return HOSTS_PATH.resolve()


def _read_hosts() -> list[str]:
    """Read /etc/hosts lines. Returns empty list if file missing."""
    path = _resolve_path()
    if not path.exists():
        return []
    return path.read_text().splitlines()


def _write_hosts(lines: list[str]) -> None:
    """Write lines to /etc/hosts.

    If running as root (e.g., via systemd timer), writes directly.
    Otherwise uses sudo tee (needs TTY for password).
    """
    content = "\n".join(lines) + "\n"
    path = _resolve_path()
    if os.geteuid() == 0:
        path.write_text(content)
    else:
        subprocess.run(
            ["sudo", "tee", str(path)],
            input=content,
            capture_output=True,
            text=True,
            check=True,
        )


def _flush_dns_cache() -> None:
    """Flush systemd-resolved cache (best-effort)."""
    with contextlib.suppress(FileNotFoundError, subprocess.TimeoutExpired):
        subprocess.run(
            ["resolvectl", "flush-caches"],
            capture_output=True,
            timeout=5,
        )


def _build_ipv4_entry(domain: str) -> str:
    """Build 127.0.0.2 entry with domain and www subdomain."""
    return f"127.0.0.2 {domain} www.{domain}"


def _build_ipv6_entry(domain: str) -> str:
    """Build ::1 entry with domain and www subdomain."""
    return f"::1 {domain} www.{domain}"


def _strip_lockin_block(lines: list[str]) -> list[str]:
    """Remove all lines between (inclusive) lockin markers."""
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
    return result


def add_entries(domains: list[str]) -> None:
    """Add lockin hosts entries for the given domains.

    Appends between MARKER_START and MARKER_END markers. Removes any
    existing lockin block first (idempotent). Includes the Firefox
    DoH canary domain automatically.
    """
    all_domains = list(domains)
    lines = _read_hosts()
    lines = _strip_lockin_block(lines)

    # Build new block
    block = [MARKER_START]
    for domain in sorted(set(all_domains)):
        block.append(_build_ipv4_entry(domain))
        block.append(_build_ipv6_entry(domain))
    block.append(MARKER_END)

    # Ensure exactly one blank line before marker if file is non-empty
    if lines and lines[-1] != "":
        lines.append("")

    lines.extend(block)
    _write_hosts(lines)
    _flush_dns_cache()


def remove_entries() -> None:
    """Remove all lockin hosts entries between markers."""
    _unlock_hosts()
    lines = _read_hosts()
    lines = _strip_lockin_block(lines)
    _write_hosts(lines)
    _flush_dns_cache()


def _unlock_hosts() -> None:
    """Remove immutable flag from /etc/hosts (best-effort)."""
    with contextlib.suppress(Exception):
        cmd = ["chattr", "-i", str(_resolve_path())]
        if os.geteuid() != 0:
            cmd = ["sudo"] + cmd
        subprocess.run(cmd, capture_output=True, timeout=5)


def _lock_hosts() -> None:
    """Set immutable flag on /etc/hosts."""
    cmd = ["chattr", "+i", str(_resolve_path())]
    if os.geteuid() != 0:
        cmd = ["sudo"] + cmd
    subprocess.run(cmd, capture_output=True, check=True, timeout=5)


def lock_hosts() -> None:
    """Make /etc/hosts immutable (high-friction mode)."""
    _lock_hosts()


def unlock_hosts() -> None:
    """Remove immutable flag from /etc/hosts."""
    _unlock_hosts()


def get_entries() -> list[str]:
    """Get list of domains currently in the lockin hosts block.

    Excludes the canary domain from results (it's an implementation detail).
    """
    lines = _read_hosts()
    pattern = re.compile(
        r"^(?:127\.0\.0\.2|::1)\s+(\S+)"
    )
    domains: set[str] = set()
    in_block = False
    for line in lines:
        if MARKER_START in line:
            in_block = True
            continue
        if MARKER_END in line:
            break
        if in_block:
            match = pattern.match(line)
            if match:
                domains.add(match.group(1))
    domains.discard("use-application-dns.net")
    return sorted(domains)
