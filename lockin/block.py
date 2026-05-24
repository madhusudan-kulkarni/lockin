"""Core orchestration: start/stop/status of blocking sessions.

lockin v2 uses /etc/hosts for domain blocking (replaces mitmproxy).
No proxy, no certs, no MITM. System-level blocking that catches all
applications, not just browsers.
"""

import contextlib
import datetime
import json
import re
from pathlib import Path

import yaml

from lockin import browser, nat, policies
from lockin.hosts import (
    add_entries,
    get_entries,
    lock_hosts,
    remove_entries,
)
from lockin.watchdog_install import install as _install_watchdog
from lockin.watchdog_install import remove as _remove_watchdog

STATE_DIR = Path.home() / ".config" / "lockin"
STATE_FILE = STATE_DIR / "state.json"
DEFAULT_RULES_PATH = Path(__file__).parent / "data" / "rules.yaml"
USER_RULES_PATH = STATE_DIR / "rules.yaml"


def parse_duration(duration_str: str) -> int:
    """Parse a human duration string into total minutes.

    Examples: "30m" → 30, "2h" → 120, "1h30m" → 90.
    """
    pattern = r"^(?:(\d+)h)?(?:(\d+)m)?$"
    match = re.match(pattern, duration_str)
    if not match or (not match.group(1) and not match.group(2)):
        raise ValueError(
            f"Invalid duration: '{duration_str}'. "
            "Use format like '30m', '2h', or '1h30m'."
        )
    hours = int(match.group(1) or 0)
    minutes = int(match.group(2) or 0)
    total = hours * 60 + minutes
    if total <= 0:
        raise ValueError(f"Duration must be positive: '{duration_str}'.")
    return total


def load_rules(path: Path) -> dict:
    """Load rules from a YAML file."""
    with open(path) as f:
        data = yaml.safe_load(f)
    if data is None:
        return {"whitelists": {}, "blacklists": {}}
    return data


def get_rules_path() -> Path:
    """Get the rules file path, preferring user config over default."""
    if USER_RULES_PATH.exists():
        return USER_RULES_PATH
    if DEFAULT_RULES_PATH.exists():
        return DEFAULT_RULES_PATH
    raise FileNotFoundError("No rules file found.")


def ensure_user_rules() -> Path:
    """Copy default rules to user config if not present."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not USER_RULES_PATH.exists() and DEFAULT_RULES_PATH.exists():
        USER_RULES_PATH.write_text(DEFAULT_RULES_PATH.read_text())
    return get_rules_path()


def find_rule(rule_name: str, rules: dict) -> tuple[str, str, list[str]]:
    """Find a rule by name. Returns (name, block_type, addresses).

    Raises ValueError if rule not found.
    """
    for section, block_type in [
        ("whitelists", "whitelist"),
        ("blacklists", "blacklist"),
    ]:
        section_rules = rules.get(section, {})
        if rule_name in section_rules:
            return rule_name, block_type, section_rules[rule_name]
    available = []
    for section in ("whitelists", "blacklists"):
        available.extend(rules.get(section, {}).keys())
    raise ValueError(
        f"Rule '{rule_name}' not found. "
        f"Available: {', '.join(sorted(available)) or 'none'}"
    )


def list_rules(rules_path: Path) -> list[tuple[str, str, int]]:
    """Return all rules as (name, block_type, address_count) tuples."""
    rules = load_rules(rules_path)
    result = []
    for section, block_type in [
        ("whitelists", "whitelist"),
        ("blacklists", "blacklist"),
    ]:
        for name, addresses in rules.get(section, {}).items():
            result.append((name, block_type, len(addresses)))
    return sorted(result)


def get_state(path: Path | None = None) -> dict | None:
    """Read the current block state, or None if no block is active."""
    if path is None:
        path = STATE_FILE
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def save_state(state: dict, path: Path | None = None) -> None:
    """Write block state to disk."""
    if path is None:
        path = STATE_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(state, f, indent=2)


def clear_state(path: Path | None = None) -> None:
    """Remove the state file."""
    if path is None:
        path = STATE_FILE
    path.unlink(missing_ok=True)


def is_block_active(state: dict | None) -> bool:
    """Check if a saved block is still in effect."""
    if state is None:
        return False
    end = datetime.datetime.fromisoformat(state["end"])
    return datetime.datetime.now() < end


def start_block(
    rule_name: str,
    duration_minutes: int | None = None,
    until_time: str | None = None,
    hardcore: bool = True,
) -> dict:
    """Start a new block. Returns the state dict.

    If hardcore=True, /etc/hosts is made immutable and stop is disabled.
    """
    # Check for existing block
    existing = get_state()
    if is_block_active(existing):
        assert existing is not None
        end = datetime.datetime.fromisoformat(existing["end"])
        raise RuntimeError(
            f"Block '{existing['rule_name']}' already active "
            f"until {end.strftime('%H:%M')}."
        )

    # Clean up stale state from a crash
    if existing:
        _cleanup_stale(existing)

    # Compute block time
    now = datetime.datetime.now().replace(second=0, microsecond=0)
    if until_time:
        end = datetime.datetime.strptime(until_time, "%H:%M").replace(
            year=now.year, month=now.month, day=now.day
        )
        if end <= now:
            end += datetime.timedelta(days=1)
    else:
        assert duration_minutes is not None
        end = now + datetime.timedelta(minutes=duration_minutes)

    # Load and find rule
    rules_path = get_rules_path()
    rules = load_rules(rules_path)
    name, block_type, addresses = find_rule(rule_name, rules)

    # 1. Write /etc/hosts entries (blocks at DNS level, all apps)
    add_entries(addresses)

    # 2. Drop QUIC/UDP 443 (prevents HTTP3 bypass)
    nat.setup()

    # 3. Deploy browser policies (disable DoH in all browsers)
    with contextlib.suppress(Exception):
        policies.apply()

    # 4. Kill browsers so they pick up new DoH-disabled policies on next launch
    killed: list[str] = []
    with contextlib.suppress(Exception):
        killed = browser.kill()

    # 5. Save state
    state = {
        "rule_name": name,
        "block_type": block_type,
        "domains": addresses,
        "start": now.isoformat(),
        "end": end.isoformat(),
        "hardcore": hardcore,
        "browsers": killed,
    }
    save_state(state)

    # 5. Lock hosts file (high-friction mode)
    if hardcore:
        lock_hosts()

    # 6. Install watchdog systemd timer
    _install_watchdog()

    return state


def stop_block() -> dict | None:
    """Stop the active block. Returns the cleared state or None.

    In hardcore mode, this is blocked — use lockin unlock instead.
    """
    state = get_state()
    if state is None:
        return None

    if state.get("hardcore"):
        raise RuntimeError(
            "Hardcore mode is active. Use 'lockin unlock' to end the session."
        )

    _cleanup_stale(state)
    clear_state()
    _remove_watchdog()
    return state


def extend_block(minutes: int) -> dict:
    """Extend the current block by N minutes.

    Raises RuntimeError if no active block.
    """
    state = get_state()
    if state is None or not is_block_active(state):
        raise RuntimeError("No active block to extend.")

    assert state is not None
    end = datetime.datetime.fromisoformat(state["end"])
    new_end = end + datetime.timedelta(minutes=minutes)
    state["end"] = new_end.isoformat()
    save_state(state)
    return state


def _cleanup_stale(state: dict) -> None:
    """Clean up all resources from a block — each step independent."""
    with contextlib.suppress(Exception):
        remove_entries()  # calls _unlock_hosts() internally
    with contextlib.suppress(Exception):
        nat.reset()
    with contextlib.suppress(Exception):
        policies.clear()


def get_status() -> str:
    """Get a human-readable status of the current block (read-only)."""
    state = get_state()
    if state is None or not is_block_active(state):
        return "No active block."

    end = datetime.datetime.fromisoformat(state["end"])
    remaining = end - datetime.datetime.now()
    if remaining.total_seconds() < 0:
        remaining = datetime.timedelta(0)

    hours, remainder = divmod(int(remaining.total_seconds()), 3600)
    minutes = remainder // 60
    time_str = f"{hours}h {minutes}m" if hours else f"{minutes}m"

    # Verify /etc/hosts entries and nftables
    hosts_entries = get_entries()
    hosts_status = (
        "active" if hosts_entries else "MISSING"
    )
    nat_status = "active"  # We can't easily check nftables without sudo

    lines = [
        f"Rule:      {state['rule_name']} ({state['block_type']})",
        f"Remaining: {time_str}",
        f"Ends at:   {end.strftime('%H:%M:%S')}",
        f"Hosts:     {hosts_status} ({len(hosts_entries)} domains)",
        f"Firewall:  {nat_status} (QUIC blocked)",
    ]
    if hosts_status == "MISSING":
        lines.append("")
        lines.append(
            "Hosts entries are missing. Run 'lockin stop' to clean up."
        )
    return "\n".join(lines)
