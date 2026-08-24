"""Core orchestration: start/stop/status of blocking sessions.

lockin uses /etc/hosts for domain blocking. No proxy, no certs, no MITM.
System-level blocking that catches all applications, not just browsers.
"""

import contextlib
import datetime
import json
import os
import re
from pathlib import Path

import yaml

from lockin import browser, nat, policies
from lockin.expand import expand
from lockin.hosts import (
    add_entries,
    get_entries,
    lock_hosts,
    remove_entries,
)
from lockin.notify import notify_block_ended
from lockin.watchdog_install import install as _install_watchdog
from lockin.watchdog_install import remove as _remove_watchdog

STATE_DIR = Path.home() / ".config" / "lockin"
STATE_FILE = STATE_DIR / "state.json"
DEFAULT_RULES_PATH = Path(__file__).parent / "data" / "rules.yaml"
USER_RULES_PATH = STATE_DIR / "rules.yaml"

EXIT_ERROR = 1
EXIT_ALREADY_ACTIVE = 2
EXIT_NO_BLOCK = 3
EXIT_RULE_NOT_FOUND = 4


def _state_path(path: Path | None = None) -> Path:
    if path is not None:
        return path
    env = os.environ.get("LOCKIN_STATE")
    if env:
        return Path(env)
    return STATE_FILE


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


def parse_until(
    until_time: str, now: datetime.datetime | None = None
) -> datetime.datetime:
    """Parse an end clock time. Accepts 17:00 and 9:30pm / 9:30 PM."""
    if now is None:
        now = datetime.datetime.now()
    now = now.replace(second=0, microsecond=0)
    raw = until_time.strip()
    compact = raw.lower().replace(" ", "")
    parsed: datetime.datetime | None = None
    if compact.endswith(("am", "pm")):
        for fmt in ("%I:%M%p", "%I%p"):
            try:
                parsed = datetime.datetime.strptime(compact, fmt)
                break
            except ValueError:
                continue
    else:
        try:
            parsed = datetime.datetime.strptime(raw, "%H:%M")
        except ValueError:
            parsed = None
    if parsed is None:
        raise ValueError(
            f"Invalid time: '{until_time}'. Use 17:00 or 9:30pm."
        )
    end = now.replace(hour=parsed.hour, minute=parsed.minute)
    if end <= now:
        end += datetime.timedelta(days=1)
    return end


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


def available_rule_names(rules: dict) -> list[str]:
    names = list((rules.get("blacklists") or {}).keys())
    for name in (rules.get("whitelists") or {}):
        if name not in names:
            names.append(name)
    return names


def parse_rule_names(raw: str | list[str] | tuple[str, ...] | None) -> list[str]:
    """Split comma/space separated and repeated CLI values into rule names."""
    if raw is None:
        return []
    parts = [raw] if isinstance(raw, str) else list(raw)
    names: list[str] = []
    for part in parts:
        for token in part.replace(",", " ").split():
            if token and token not in names:
                names.append(token)
    return names


def resolve_rules(
    names: list[str] | None, rules: dict
) -> tuple[str, list[str]]:
    """Resolve one or more rule names to a joined name and union of addresses.

    Empty names: YAML ``default``, else the only blacklist, else ValueError.
    """
    if not names:
        default = rules.get("default")
        if isinstance(default, str) and default.strip():
            names = [default.strip()]
        else:
            available = available_rule_names(rules)
            if len(available) == 1:
                names = available
            else:
                listed = ", ".join(sorted(available)) or "none"
                raise ValueError(
                    f"Must specify --rule. Available: {listed}"
                )
    addresses: list[str] = []
    resolved: list[str] = []
    for name in names:
        found, _, addrs = find_rule(name, rules)
        if found not in resolved:
            resolved.append(found)
            addresses.extend(addrs)
    joined = ",".join(sorted(resolved))
    return joined, addresses


def find_rule(rule_name: str, rules: dict) -> tuple[str, str, list[str]]:
    """Find a rule by name. Returns (name, 'blacklist', addresses).

    ``blacklists`` is the real key. ``whitelists`` is a legacy alias and
    is also treated as a blocklist (no invert).
    """
    blacklists = rules.get("blacklists") or {}
    if rule_name in blacklists:
        return rule_name, "blacklist", blacklists[rule_name]
    legacy = rules.get("whitelists") or {}
    if rule_name in legacy:
        return rule_name, "blacklist", legacy[rule_name]
    available = list(blacklists.keys()) + list(legacy.keys())
    raise ValueError(
        f"Rule '{rule_name}' not found. "
        f"Available: {', '.join(sorted(available)) or 'none'}"
    )


def list_rules(rules_path: Path) -> list[tuple[str, str, int]]:
    """Return all rules as (name, display_type, address_count) tuples."""
    rules = load_rules(rules_path)
    result = []
    for name, addresses in (rules.get("blacklists") or {}).items():
        result.append((name, "blocklist", len(addresses)))
    for name, addresses in (rules.get("whitelists") or {}).items():
        if name in (rules.get("blacklists") or {}):
            continue
        result.append((name, "blocklist", len(addresses)))
    return sorted(result)


def get_state(path: Path | None = None) -> dict | None:
    """Read the current block state, or None if no block is active."""
    path = _state_path(path)
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def save_state(state: dict, path: Path | None = None) -> None:
    """Write block state to disk."""
    path = _state_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(state, f, indent=2)


def clear_state(path: Path | None = None) -> None:
    """Remove the state file."""
    path = _state_path(path)
    path.unlink(missing_ok=True)


def is_block_active(state: dict | None) -> bool:
    """Check if a saved block is still in effect."""
    if state is None:
        return False
    end = datetime.datetime.fromisoformat(state["end"])
    return datetime.datetime.now() < end


def end_session(*, force: bool = False) -> dict | None:
    """Tear down hosts, firewall, policies, state, and the watchdog.

    If there is no state file and ``force`` is false, return None.
    If ``force`` is true, still strip leftovers.
    """
    state = get_state()
    if state is None and not force:
        return None
    with contextlib.suppress(Exception):
        remove_entries()
    with contextlib.suppress(Exception):
        nat.reset()
    with contextlib.suppress(Exception):
        policies.clear()
    clear_state()
    with contextlib.suppress(Exception):
        _remove_watchdog()
    return state


def start_block(
    rule_name: str | list[str] | tuple[str, ...] | None = None,
    duration_minutes: int | None = None,
    until_time: str | None = None,
    hardcore: bool = True,
) -> dict:
    """Start a new block. Returns the state dict.

    If hardcore=True, /etc/hosts is made immutable and stop is disabled.
    """
    existing = get_state()
    if is_block_active(existing):
        assert existing is not None
        end = datetime.datetime.fromisoformat(existing["end"])
        raise RuntimeError(
            f"Block '{existing['rule_name']}' already active "
            f"until {end.strftime('%H:%M')}."
        )

    if existing:
        end_session(force=True)

    now = datetime.datetime.now().replace(second=0, microsecond=0)
    if until_time:
        end = parse_until(until_time, now)
    else:
        assert duration_minutes is not None
        end = now + datetime.timedelta(minutes=duration_minutes)

    ensure_user_rules()
    rules_path = get_rules_path()
    rules = load_rules(rules_path)
    names = parse_rule_names(rule_name)
    name, addresses = resolve_rules(names, rules)
    addresses = expand(addresses)

    nat.backend()

    killed: list[str] = []
    try:
        add_entries(addresses)
        nat.setup()
        with contextlib.suppress(Exception):
            policies.apply()
        with contextlib.suppress(Exception):
            killed = browser.kill()
        state = {
            "rule_name": name,
            "block_type": "blacklist",
            "domains": addresses,
            "start": now.isoformat(),
            "end": end.isoformat(),
            "hardcore": hardcore,
            "browsers": killed,
        }
        save_state(state)
        if hardcore:
            lock_hosts()
        _install_watchdog()
    except Exception:
        end_session(force=True)
        raise

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

    end_session()
    notify_block_ended()
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


def request_unlock(minutes: int = 30) -> tuple[dict, bool]:
    """Queue an early unlock after a cooldown.

    Returns (state, shortened). If shortened is False, the current end is
    already sooner than now + minutes and state is unchanged.
    """
    state = get_state()
    if state is None or not is_block_active(state):
        raise RuntimeError("No active block.")
    if state.get("unlock_requested"):
        raise RuntimeError(
            "Unlock already requested. Use 'lockin unlock --now' for emergency."
        )
    now = datetime.datetime.now()
    current_end = datetime.datetime.fromisoformat(state["end"])
    new_end = now + datetime.timedelta(minutes=minutes)
    if new_end >= current_end:
        return state, False
    state["end"] = new_end.isoformat()
    state["unlock_requested"] = True
    save_state(state)
    return state, True


def get_status_data() -> dict:
    """Machine-readable status for CLI --json and status bars."""
    state = get_state()
    if state is None or not is_block_active(state):
        return {"active": False}
    end = datetime.datetime.fromisoformat(state["end"])
    remaining = end - datetime.datetime.now()
    remaining_seconds = max(0, int(remaining.total_seconds()))
    hosts_entries = get_entries()
    return {
        "active": True,
        "rule_name": state["rule_name"],
        "block_type": state.get("block_type", "blacklist"),
        "end": state["end"],
        "remaining_seconds": remaining_seconds,
        "hosts": "active" if hosts_entries else "missing",
        "hosts_count": len(hosts_entries),
        "firewall": nat.probe(),
    }


def get_status() -> str:
    """Get a human-readable status of the current block (read-only)."""
    data = get_status_data()
    if not data.get("active"):
        return "No active block."

    remaining_seconds = int(data["remaining_seconds"])
    hours, remainder = divmod(remaining_seconds, 3600)
    minutes = remainder // 60
    time_str = f"{hours}h {minutes}m" if hours else f"{minutes}m"
    end = datetime.datetime.fromisoformat(data["end"])

    hosts_status = "active" if data["hosts"] == "active" else "MISSING"
    nat_status = data["firewall"]
    block_type = data.get("block_type", "blocklist")
    if block_type == "blacklist":
        block_type = "blocklist"
    if nat_status == "active":
        fw_line = "active (QUIC blocked)"
    elif nat_status == "inactive":
        fw_line = "inactive"
    else:
        fw_line = "unknown (needs sudo to verify)"

    lines = [
        f"Rule:      {data['rule_name']} ({block_type})",
        f"Remaining: {time_str}",
        f"Ends at:   {end.strftime('%H:%M:%S')}",
        f"Hosts:     {hosts_status} ({data['hosts_count']} domains)",
        f"Firewall:  {fw_line}",
    ]
    if hosts_status == "MISSING":
        lines.append("")
        lines.append(
            "Hosts entries are missing. The watchdog should restore them "
            "within a minute. Manual teardown during a live block ends "
            "the session."
        )
    return "\n".join(lines)
