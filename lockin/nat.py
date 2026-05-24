"""NAT management: nftables QUIC sinkhole.

Drops UDP port 443 to force browsers to fall back from QUIC/HTTP3
to TCP/HTTPS. Does NOT redirect any TCP traffic — lockin v2 blocks
via /etc/hosts and browser extension instead of proxy MITM.
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
        for cmd in _iptables_setup_commands():
            _sudo(cmd)


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


def _iptables_setup_commands() -> list[list[str]]:
    """Generate iptables commands for QUIC drop."""
    return [
        ["iptables", "-A", "OUTPUT", "-p", "udp", "--dport", "443", "-j", "REJECT"],
        ["ip6tables", "-A", "OUTPUT", "-p", "udp", "--dport", "443", "-j", "REJECT"],
    ]


def _iptables_reset_commands() -> list[list[str]]:
    """Generate iptables commands for reset."""
    return [
        ["iptables", "-D", "OUTPUT", "-p", "udp", "--dport", "443", "-j", "REJECT"],
        ["ip6tables", "-D", "OUTPUT", "-p", "udp", "--dport", "443", "-j", "REJECT"],
    ]
