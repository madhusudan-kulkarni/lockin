"""CLI for lockin — block distracting websites so you can focus.

lockin v2 uses /etc/hosts for domain blocking. No proxy, no certs,
no extension. Blocked sites show "connection refused" — honest and zero-maintenance.
"""

import contextlib
import sys

import click

from lockin import __version__
from lockin.block import (
    _cleanup_stale,
    clear_state,
    ensure_user_rules,
    extend_block,
    get_rules_path,
    get_state,
    get_status,
    list_rules,
    parse_duration,
    start_block,
    stop_block,
)


@click.group()
@click.version_option(version=__version__, prog_name="lockin")
def main():
    """lockin — block distracting websites so you can focus."""


@main.command()
@click.option(
    "--rule", "-r", required=True, help="Rule name from rules.yaml"
)
@click.option("--for", "-f", "duration", help="Duration: 30m, 2h, 1h30m")
@click.option("--until", "-u", help="End time: 17:00")
@click.option(
    "--soft", is_flag=True,
    help="Allow stop to work (hosts file not locked)",
)
def start(rule: str, duration: str, until: str, soft: bool):
    """Start a blocking session."""
    if not duration and not until:
        raise click.UsageError("Must specify --for or --until.")

    try:
        click.echo(
            click.style(
                "⚠ Browsers will be closed. Save your work.",
                fg="yellow",
            )
        )
        duration_mins = parse_duration(duration) if duration else None
        state = start_block(
            rule_name=rule,
            duration_minutes=duration_mins,
            until_time=until,
            hardcore=not soft,
        )
        click.echo(
            f"Block '{state['rule_name']}' ({state['block_type']}) "
            f"active until {state['end']}."
        )
        click.echo(
            f"  {len(state['domains'])} domains added to /etc/hosts"
        )
        click.echo("  QUIC/HTTP3 blocked via nftables")
        click.echo("  ", nl=False)
        click.echo(
            click.style("Firefox: Settings → DNS over HTTPS → Off", fg="yellow")
        )
        if state.get("browsers"):
            click.echo(
                click.style(
                    f"  Browsers closed: {', '.join(state['browsers'])}. "
                    "Reopen them after the block ends.",
                    fg="yellow",
                )
            )
    except FileNotFoundError as e:
        click.echo(str(e), err=True)
        sys.exit(1)
    except (ValueError, RuntimeError) as e:
        msg = str(e)
        if "already active" in msg:
            click.echo(msg, err=True)
            sys.exit(2)
        elif "not found" in msg:
            click.echo(msg, err=True)
            sys.exit(4)
        elif "duration" in msg.lower():
            click.echo(msg, err=True)
            sys.exit(1)
        else:
            click.echo(msg, err=True)
            sys.exit(1)


@main.command()
def stop():
    """Stop the active block and clean up."""
    state = stop_block()
    if state is None:
        click.echo("No active block.", err=True)
        sys.exit(3)
    click.echo(f"Block '{state['rule_name']}' ended. Cleaned up.")


@main.command()
def status():
    """Show status of the active block."""
    output = get_status()
    click.echo(output)


@main.command("list")
def list_rules_cmd():
    """List all available rules."""
    ensure_user_rules()
    rules_path = get_rules_path()
    rules = list_rules(rules_path)
    if not rules:
        click.echo("No rules defined. Edit ~/.config/lockin/rules.yaml")
        return
    click.echo(f"{'RULE':<20} {'TYPE':<12} ADDRESSES")
    click.echo("-" * 50)
    for name, block_type, count in rules:
        click.echo(f"{name:<20} {block_type:<12} {count}")


@main.command(hidden=True)
def reset():
    """Internal: cleanup command called by the scheduler."""
    state = get_state()
    if state:
        _cleanup_stale(state)
        clear_state()


@main.command()
def cleanup():
    """Remove stale /etc/hosts entries, firewall rules, and timers."""
    state = get_state()
    if state:
        click.echo(
            f"Cleaning up stale"
            f" '{state.get('rule_name', 'unknown')}' session..."
        )
        _cleanup_stale(state)
        clear_state()
        click.echo("Done.")
    else:
        click.echo("Nothing to clean up.")


@main.command()
@click.argument("minutes", type=int)
def extend(minutes: int):
    """Extend the current block by N minutes."""
    try:
        state = extend_block(minutes)
        click.echo(
            f"Extended by {minutes} min. "
            f"Now ends at {state['end']}."
        )
    except RuntimeError as e:
        click.echo(str(e), err=True)
        sys.exit(1)


@main.command()
@click.argument("cooldown", type=int, required=False)
@click.option("--now", is_flag=True, help="Emergency immediate unlock")
def unlock(cooldown: int | None, now: bool):
    """Request early unlock after a cooldown.

    Default cooldown: 30 minutes. Cannot be cancelled or shortened.
    Use --now for emergency bypass with confirmation.
    """
    state = get_state()
    if state is None:
        click.echo("No active block.", err=True)
        sys.exit(1)

    if now:
        click.echo(
            "This defeats the purpose of lockin."
        )
        confirm = click.prompt("Type 'yes' to confirm", default="")
        if confirm != "yes":
            click.echo("Aborted.")
            return
        _cleanup_stale(state)
        clear_state()
        click.echo("Emergency unlock complete. Stay focused next time.")
        return

    minutes = cooldown or 30
    # Just extend the end time to force a cooldown before the block expires
    # The unlock happens when the extended timer fires
    import datetime
    new_end = datetime.datetime.fromisoformat(state["end"])
    if new_end <= datetime.datetime.now():
        new_end = datetime.datetime.now()
    new_end += datetime.timedelta(minutes=minutes)

    from lockin.block import save_state
    state["end"] = new_end.isoformat()
    save_state(state)

    click.echo(
        f"Unlock requested. Cooldown: {minutes} min. "
        f"Unlocks at {new_end.strftime('%H:%M')}."
    )


@main.command()
def doctor():
    """Run diagnostic checks on your lockin installation."""
    from lockin.doctor import format_results, run_checks
    click.echo(format_results(run_checks()))


@main.command()
def update():
    """Upgrade lockin to the latest version."""
    import shutil
    import subprocess

    current = __version__
    if shutil.which("uv"):
        cmd = ["uv", "tool", "upgrade", "lockin-blocker"]
    elif shutil.which("pip"):
        cmd = [sys.executable, "-m", "pip", "install", "--upgrade", "lockin-blocker"]
    else:
        click.echo("Neither uv nor pip found.", err=True)
        sys.exit(1)

    click.echo(f"Upgrading lockin (current: {current})...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        click.echo("Done. Run 'lockin --version' to verify.")
    else:
        click.echo(result.stderr or "Upgrade failed.", err=True)
        sys.exit(1)


@main.command()
def uninstall():
    """Remove lockin and clean up all traces."""
    import shutil
    import subprocess

    # 1. Clean up any active blocks
    state = get_state()
    if state:
        _cleanup_stale(state)
        clear_state()
        click.echo("Cleaned up active block.")

    # 2. Remove systemd units
    click.echo("Removing systemd timer...")
    with contextlib.suppress(Exception):
        subprocess.run(
            ["sudo", "systemctl", "disable", "--now",
             "lockin-watchdog.timer"],
            capture_output=True, timeout=10,
        )
    with contextlib.suppress(Exception):
        subprocess.run(
            ["sudo", "rm", "-f",
             "/etc/systemd/system/lockin-watchdog.service",
             "/etc/systemd/system/lockin-watchdog.timer"],
            capture_output=True, timeout=10,
        )
        subprocess.run(
            ["sudo", "rm", "-rf", "/usr/local/lib/lockin"],
            capture_output=True, timeout=10,
        )
        subprocess.run(
            ["sudo", "systemctl", "daemon-reload"],
            capture_output=True, timeout=10,
        )

    # 3. Remove browser policy files
    click.echo("Removing browser policies...")
    with contextlib.suppress(Exception):
        for d in [
            "/etc/firefox/policies/policies.json",
            "/etc/firefox/policies/policies.json.lockin-backup",
            "/etc/opt/chrome/policies/managed/lockin-doh.json",
            "/etc/chromium/policies/managed/lockin-doh.json",
            "/etc/opt/brave/policies/managed/lockin-doh.json",
            "/etc/opt/edge/policies/managed/lockin-doh.json",
        ]:
            subprocess.run(
                ["sudo", "rm", "-f", d],
                capture_output=True, timeout=5,
            )

    # 4. Uninstall tool
    click.echo()
    click.echo("To remove the lockin binary, run one of:")
    if shutil.which("uv"):
        click.echo("  uv tool uninstall lockin-blocker")
    if shutil.which("pip") or shutil.which("pip3"):
        click.echo("  pip uninstall lockin-blocker")


if __name__ == "__main__":
    main()
