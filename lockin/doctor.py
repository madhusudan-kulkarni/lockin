"""Diagnostic checks for lockin installation health."""

import json
import os
import shutil
import subprocess
from pathlib import Path

import yaml


def run_checks() -> list[tuple[str, bool, str]]:
    """Run all diagnostic checks. Returns [(name, ok, detail), ...]."""
    results: list[tuple[str, bool, str]] = []

    # 1. Firewall backend
    backend = shutil.which("nft") or shutil.which("iptables")
    results.append((
        "firewall",
        backend is not None,
        "nftables detected" if shutil.which("nft")
        else "iptables detected" if shutil.which("iptables")
        else "No firewall backend found. Install nftables or iptables.",
    ))

    # 2. /etc/hosts writability
    hosts = Path("/etc/hosts")
    if hosts.exists():
        writable = os.access(hosts, os.W_OK)
        results.append((
            "hosts writable",
            True,  # sudo is expected and handled
            "/etc/hosts writable" if writable else
            "/etc/hosts requires sudo (expected — lockin uses sudo tee)",
        ))
    else:
        results.append((
            "hosts file",
            False,
            "/etc/hosts not found",
        ))

    # 3. Rules file
    rules_path = None
    user_rules = Path.home() / ".config" / "lockin" / "rules.yaml"
    default_rules = Path(__file__).parent / "data" / "rules.yaml"
    if user_rules.exists():
        rules_path = user_rules
    elif default_rules.exists():
        rules_path = default_rules

    if rules_path:
        try:
            with open(rules_path) as f:
                data = yaml.safe_load(f)
            whitelist_count = len(data.get("whitelists", {}))
            blacklist_count = len(data.get("blacklists", {}))
            total = whitelist_count + blacklist_count
            results.append((
                "rules",
                total > 0,
                f"{total} rules ({whitelist_count} whitelist, "
                f"{blacklist_count} blacklist) in {rules_path}",
            ))
        except Exception as e:
            results.append((
                "rules",
                False,
                f"Failed to parse {rules_path}: {e}",
            ))
    else:
        results.append((
            "rules",
            False,
            "No rules file found",
        ))

    # 4. State file (stale check)
    state_path = Path.home() / ".config" / "lockin" / "state.json"
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
            end = state.get("end", "")
            results.append((
                "state",
                False,
                f"Stale state file present (ended {end}). "
                "Run 'lockin cleanup' to remove.",
            ))
        except Exception:
            results.append((
                "state",
                False,
                "Corrupt state file. Run 'lockin cleanup'.",
            ))
    else:
        results.append((
            "state",
            True,
            "No stale state",
        ))

    # 5. Hosts entries check
    hosts_block = False
    if hosts.exists():
        content = hosts.read_text()
        hosts_block = "# === lockin start ===" in content
    results.append((
        "hosts entries",
        not hosts_block,
        "No lockin entries" if not hosts_block
        else "Stale lockin entries in /etc/hosts. Run 'lockin cleanup'.",
    ))

    # 6. DoH canary domain
    canary_blocked = False
    if hosts.exists():
        canary_blocked = "use-application-dns.net" in hosts.read_text()
    results.append((
        "firefox DoH",
        True,
        "Canary domain in /etc/hosts" if canary_blocked
        else "Canary domain not in /etc/hosts (added during active block)",
    ))

    # 7. Scheduler availability
    has_systemd = (
        shutil.which("systemctl") is not None
        and Path("/run/systemd/system").exists()
    )
    has_at = shutil.which("at") is not None
    has_cron = shutil.which("crontab") is not None

    if has_systemd:
        sched_detail = "systemd (optimal)"
    elif has_at:
        sched_detail = "at (fallback)"
    elif has_cron:
        sched_detail = "cron (fallback)"
    else:
        sched_detail = "in-process timer (last resort)"

    results.append((
        "scheduler",
        has_systemd,
        sched_detail,
    ))

    # 8. nftables lockin table
    try:
        result = subprocess.run(
            ["sudo", "nft", "list", "table", "inet", "lockin"],
            capture_output=True, text=True, timeout=5,
        )
        has_table = result.returncode == 0
    except Exception:
        has_table = False

    results.append((
        "nftables",
        not has_table,
        "Table present (should not exist without active block)"
        if has_table else "No stale lockin table",
    ))

    return results


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
