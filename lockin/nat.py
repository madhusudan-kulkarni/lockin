"""NAT management: nftables QUIC sinkhole with iptables fallback.

Rejects QUIC (UDP 443) via nftables when available, or iptables otherwise.
Domain blocking is handled by /etc/hosts, not here.
"""

import contextlib
import os
import shutil
import subprocess

TABLE_NAME = "lockin"
CHAIN_NAME = "output"


def backend() -> str:
    """Detect available firewall backend."""
    if shutil.which("nft"):
        return "nftables"
    if shutil.which("iptables"):
        return "iptables"
    raise RuntimeError(
        "No firewall backend found. Install nftables or iptables."
    )


def _sudo(cmd: list[str], *, check: bool = True) -> None:
    """Run a command as root. Skips sudo if already root."""
    if os.geteuid() == 0:
        subprocess.run(cmd, check=check, capture_output=True, text=True)
    else:
        subprocess.run(
            ["sudo"] + cmd, check=check, capture_output=True, text=True
        )


def setup() -> None:
    """Drop UDP 443 to block QUIC/HTTP3."""
    if backend() == "nftables":
        for cmd in _nft_setup_commands():
            _sudo(cmd)
    else:
        _iptables_setup()


def reset() -> None:
    """Remove all lockin firewall rules."""
    if backend() == "nftables":
        for cmd in _nft_reset_commands():
            with contextlib.suppress(subprocess.CalledProcessError):
                _sudo(cmd)
    else:
        for cmd in _iptables_reset_commands():
            with contextlib.suppress(subprocess.CalledProcessError):
                _sudo(cmd)


def probe() -> str:
    """Return 'active', 'inactive', or 'unknown' without assuming sudo."""
    try:
        kind = backend()
    except RuntimeError:
        return "inactive"
    if kind != "nftables":
        return "unknown"
    try:
        result = subprocess.run(
            ["nft", "list", "table", "inet", TABLE_NAME],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    if result.returncode == 0:
        return "active"
    err = (result.stderr or "").lower()
    if "permission" in err or "not permitted" in err or "operation" in err:
        return "unknown"
    return "inactive"


def _nft_setup_commands() -> list[list[str]]:
    """Generate nftables commands for QUIC drop."""
    return [
        ["nft", "add", "table", "inet", TABLE_NAME],
        [
            "nft", "add", "chain", "inet", TABLE_NAME, CHAIN_NAME,
            "{",
            "type", "filter", "hook", "output", "priority", "mangle", ";",
            "}",
        ],
        ["nft", "flush", "chain", "inet", TABLE_NAME, CHAIN_NAME],
        [
            "nft", "add", "rule", "inet", TABLE_NAME, CHAIN_NAME,
            "udp", "dport", "443", "reject",
        ],
    ]


def _nft_reset_commands() -> list[list[str]]:
    """Generate nftables commands for reset."""
    return [
        ["nft", "delete", "table", "inet", TABLE_NAME],
    ]


def _iptables_setup() -> None:
    """Add QUIC reject rules idempotently (check before append)."""
    for table in ("iptables", "ip6tables"):
        rule = ["-p", "udp", "--dport", "443", "-j", "REJECT"]
        check = [table, "-C", "OUTPUT", *rule]
        append = [table, "-A", "OUTPUT", *rule]
        try:
            _sudo(check)
        except subprocess.CalledProcessError:
            _sudo(append)


def _iptables_reset_commands() -> list[list[str]]:
    """Generate iptables commands for reset."""
    return [
        ["iptables", "-D", "OUTPUT", "-p", "udp", "--dport", "443", "-j", "REJECT"],
        ["ip6tables", "-D", "OUTPUT", "-p", "udp", "--dport", "443", "-j", "REJECT"],
    ]
