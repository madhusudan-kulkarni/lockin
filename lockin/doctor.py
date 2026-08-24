"""Diagnostic checks for lockin installation health."""

import json
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import yaml

from lockin.hosts import MARKER_START


def _user_home() -> Path:
    return Path.home()


def _hosts_path() -> Path:
    return Path("/etc/hosts")


def _systemd_run_path() -> Path:
    return Path("/run/systemd/system")


def run_checks() -> list[tuple[str, bool, str]]:
    """Run all diagnostic checks. Returns [(name, ok, detail), ...]."""
    results: list[tuple[str, bool, str]] = []

    has_nft = shutil.which("nft") is not None
    has_iptables = shutil.which("iptables") is not None
    results.append((
        "firewall",
        has_nft or has_iptables,
        "nftables detected" if has_nft
        else "iptables detected" if has_iptables
        else "No firewall backend found. Install nftables or iptables.",
    ))

    hosts = _hosts_path()
    results.append((
        "hosts file",
        hosts.exists(),
        "/etc/hosts found" if hosts.exists() else "/etc/hosts not found",
    ))

    user_rules = _user_home() / ".config" / "lockin" / "rules.yaml"
    default_rules = Path(__file__).parent / "data" / "rules.yaml"
    rules_path = user_rules if user_rules.exists() else (
        default_rules if default_rules.exists() else None
    )
    if rules_path:
        try:
            with open(rules_path) as f:
                data = yaml.safe_load(f) or {}
            blacklist_count = len(data.get("blacklists") or {})
            legacy_count = len(data.get("whitelists") or {})
            total = blacklist_count + legacy_count
            extra = (
                f", {legacy_count} legacy whitelist key"
                if legacy_count else ""
            )
            results.append((
                "rules",
                total > 0,
                f"{total} blocklist(s){extra} in {rules_path}",
            ))
        except Exception as e:
            results.append((
                "rules",
                False,
                f"Failed to parse {rules_path}: {e}",
            ))
    else:
        results.append(("rules", False, "No rules file found"))

    if user_rules.exists():
        try:
            with open(user_rules) as f:
                user_data = yaml.safe_load(f) or {}
            names = set((user_data.get("blacklists") or {}).keys())
            names.update((user_data.get("whitelists") or {}).keys())
            default = user_data.get("default")
            if len(names) > 1 and not (
                isinstance(default, str) and default.strip()
            ):
                results.append((
                    "default rule",
                    True,
                    "No default key in rules.yaml. "
                    "Add `default: social` or pass --rule each time.",
                ))
        except Exception:
            pass

    has_systemd = (
        shutil.which("systemctl") is not None
        and _systemd_run_path().exists()
    )
    results.append((
        "systemd",
        has_systemd,
        "systemd available" if has_systemd
        else "systemd not found (lockin requires systemd)",
    ))

    state_path = _user_home() / ".config" / "lockin" / "state.json"
    state = None
    live = False
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
            end = datetime.fromisoformat(state.get("end", ""))
            live = datetime.now() < end
        except Exception:
            results.append((
                "session",
                False,
                "Corrupt state file. Run 'lockin cleanup'.",
            ))
            return results

    hosts_block = False
    if hosts.exists():
        hosts_block = MARKER_START in hosts.read_text()

    nft_table = _nft_table_present()
    timer_active = _timer_active() if has_systemd else False

    leftovers = hosts_block or nft_table is True or timer_active

    if live and state is not None:
        until = state.get("end", "")
        results.append((
            "session",
            True,
            f"block live until {until}",
        ))
        results.append((
            "hosts entries",
            hosts_block,
            "lockin markers present" if hosts_block
            else "Hosts markers missing during live block. "
            "The watchdog should restore them.",
        ))
        if nft_table is True:
            nft_ok, nft_detail = True, "lockin nft table present"
        elif nft_table is False:
            nft_ok, nft_detail = True, (
                "no nft table (iptables backend or not yet applied)"
            )
        else:
            nft_ok, nft_detail = True, "nft status unknown (needs sudo)"
        results.append(("nftables", nft_ok, nft_detail))
        results.append((
            "watchdog",
            timer_active if has_systemd else True,
            "timer active" if timer_active
            else "timer not active" if has_systemd
            else "skipped (no systemd)",
        ))
    elif leftovers or state is not None:
        results.append((
            "session",
            False,
            "Leftover lockin state. Run 'lockin cleanup'.",
        ))
        results.append((
            "hosts entries",
            not hosts_block,
            "No lockin entries" if not hosts_block
            else "Stale lockin entries in /etc/hosts. Run 'lockin cleanup'.",
        ))
        if nft_table is True:
            results.append((
                "nftables",
                False,
                "Stale lockin nft table. Run 'lockin cleanup'.",
            ))
        elif nft_table is False:
            results.append(("nftables", True, "No stale lockin table"))
        else:
            results.append(("nftables", True, "nft status unknown (needs sudo)"))
        if timer_active:
            results.append((
                "watchdog",
                False,
                "Watchdog timer still enabled. Run 'lockin cleanup'.",
            ))
        else:
            results.append(("watchdog", True, "No leftover timer"))
    else:
        results.append(("session", True, "No active block, no leftovers"))
        results.append(("hosts entries", True, "No lockin entries"))
        results.append(("nftables", True, "No stale lockin table"))
        results.append(("watchdog", True, "No leftover timer"))

    return results


def _nft_table_present() -> bool | None:
    try:
        result = subprocess.run(
            ["nft", "list", "table", "inet", "lockin"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return None
    if result.returncode == 0:
        return True
    err = (result.stderr or "").lower()
    if "permission" in err or "not permitted" in err:
        return None
    return False


def _timer_active() -> bool:
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "lockin-watchdog.timer"],
            capture_output=True, text=True, timeout=5,
        )
        return result.stdout.strip() == "active"
    except Exception:
        return False


def format_results(results: list[tuple[str, bool, str]]) -> str:
    """Format check results for display."""
    lines = ["lockin doctor — diagnostic report", "=" * 50, ""]
    all_ok = True
    for name, ok, detail in results:
        icon = "✓" if ok else "✗"
        lines.append(f"  {icon} {name:<18} {detail}")
        if not ok:
            all_ok = False
    lines.append("")
    if all_ok:
        lines.append("All checks passed. lockin is ready.")
    else:
        lines.append("Some checks failed. See above for details.")
    return "\n".join(lines)
