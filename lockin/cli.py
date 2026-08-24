"""CLI for lockin — block distracting websites so you can focus.

Uses /etc/hosts for domain blocking. No proxy, no certs, no extension.
"""

import sys

import click

from lockin import __version__
from lockin.block import (
    EXIT_ALREADY_ACTIVE,
    EXIT_ERROR,
    EXIT_NO_BLOCK,
    EXIT_RULE_NOT_FOUND,
    end_session,
    ensure_user_rules,
    extend_block,
    get_rules_path,
    get_state,
    get_status,
    get_status_data,
    list_rules,
    parse_duration,
    parse_rule_names,
    request_unlock,
    start_block,
    stop_block,
)
from lockin.notify import notify_block_ended


@click.group()
@click.version_option(version=__version__, prog_name="lockin")
def main():
    """lockin — block distracting websites so you can focus."""


@main.command()
@click.option(
    "--rule", "-r", "rule", multiple=True,
    help="Rule name(s). Repeat or comma-separate. Default: rules.yaml default.",
)
@click.option("--for", "-f", "duration", help="Duration: 30m, 2h, 1h30m")
@click.option("--until", "-u", help="End time: 17:00 or 9:30pm")
@click.option(
    "--soft", is_flag=True,
    help="Allow stop to work (hosts file not locked)",
)
def start(rule: tuple[str, ...], duration: str, until: str, soft: bool):
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
        names = parse_rule_names(rule if rule else None)
        state = start_block(
            rule_name=names or None,
            duration_minutes=duration_mins,
            until_time=until,
            hardcore=not soft,
        )
        block_type = state.get("block_type", "blocklist")
        if block_type == "blacklist":
            block_type = "blocklist"
        click.echo(
            f"Block '{state['rule_name']}' ({block_type}) "
            f"active until {state['end']}."
        )
        click.echo(
            f"  {len(state['domains'])} domains added to /etc/hosts"
        )
        click.echo("  QUIC/HTTP3 blocked (UDP 443 rejected for all destinations)")
        if not soft:
            click.echo(
                click.style(
                    "  Hardcore mode: lockin stop is disabled. "
                    "Use lockin unlock --now to end early.",
                    fg="yellow",
                )
            )
        if state.get("browsers"):
            click.echo(
                click.style(
                    f"  Browsers closed: {', '.join(state['browsers'])}. "
                    "Reopen them now so they pick up DoH policies.",
                    fg="yellow",
                )
            )
    except FileNotFoundError as e:
        click.echo(str(e), err=True)
        sys.exit(EXIT_ERROR)
    except (ValueError, RuntimeError) as e:
        msg = str(e)
        if "already active" in msg:
            click.echo(msg, err=True)
            sys.exit(EXIT_ALREADY_ACTIVE)
        elif "not found" in msg:
            click.echo(msg, err=True)
            sys.exit(EXIT_RULE_NOT_FOUND)
        elif "duration" in msg.lower() or "invalid time" in msg.lower():
            click.echo(msg, err=True)
            sys.exit(EXIT_ERROR)
        else:
            click.echo(msg, err=True)
            sys.exit(EXIT_ERROR)


@main.command()
def stop():
    """Stop the active block and clean up."""
    try:
        state = stop_block()
    except RuntimeError as e:
        click.echo(str(e), err=True)
        sys.exit(EXIT_ERROR)
    if state is None:
        click.echo("No active block.", err=True)
        sys.exit(EXIT_NO_BLOCK)
    click.echo(f"Block '{state['rule_name']}' ended. Cleaned up.")


@main.command()
@click.option("--json", "as_json", is_flag=True, help="Print machine-readable JSON")
def status(as_json: bool):
    """Show status of the active block."""
    if as_json:
        import json

        click.echo(json.dumps(get_status_data()))
        return
    click.echo(get_status())


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


@main.command()
def cleanup():
    """Remove leftover /etc/hosts entries, firewall rules, and timers."""
    state = get_state()
    if state:
        click.echo(
            f"Cleaning up '{state.get('rule_name', 'unknown')}' session..."
        )
    end_session(force=True)
    click.echo("Done.")


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
        sys.exit(EXIT_NO_BLOCK)


@main.command()
@click.argument("cooldown", type=int, required=False)
@click.option("--now", is_flag=True, help="Emergency immediate unlock")
def unlock(cooldown: int | None, now: bool):
    """Request early unlock after a cooldown.

    Default cooldown: 30 minutes. Cannot be cancelled or shortened.
    Use --now for emergency bypass with confirmation.
    """
    import datetime

    state = get_state()
    if state is None:
        click.echo("No active block.", err=True)
        sys.exit(EXIT_NO_BLOCK)

    if now:
        click.echo(
            "This defeats the purpose of lockin."
        )
        confirm = click.prompt("Type 'yes' to confirm", default="")
        if confirm != "yes":
            click.echo("Aborted.")
            return
        end_session(force=True)
        notify_block_ended()
        click.echo("Emergency unlock complete. Stay focused next time.")
        return

    minutes = cooldown or 30
    try:
        state, shortened = request_unlock(minutes)
    except RuntimeError as e:
        click.echo(str(e), err=True)
        if "already requested" in str(e).lower():
            sys.exit(EXIT_ERROR)
        sys.exit(EXIT_NO_BLOCK)

    if not shortened:
        end = datetime.datetime.fromisoformat(state["end"])
        click.echo(
            f"Block already ends at {end.strftime('%H:%M')}, "
            f"sooner than a {minutes} min cooldown."
        )
        return

    end = datetime.datetime.fromisoformat(state["end"])
    click.echo(
        f"Unlock requested. Cooldown: {minutes} min. "
        f"Unlocks at {end.strftime('%H:%M')}."
    )


@main.command()
def doctor():
    """Run diagnostic checks on your lockin installation."""
    from lockin.doctor import format_results, run_checks
    results = run_checks()
    click.echo(format_results(results))
    if any(not ok for _, ok, _ in results):
        sys.exit(EXIT_ERROR)


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
        sys.exit(EXIT_ERROR)

    click.echo(f"Upgrading lockin (current: {current})...")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode == 0:
        click.echo("Done. Run 'lockin --version' to verify.")
    else:
        click.echo(result.stderr or "Upgrade failed.", err=True)
        sys.exit(EXIT_ERROR)


@main.command()
def uninstall():
    """Remove lockin and clean up all traces."""
    import shutil

    end_session(force=True)
    click.echo("Cleaned up system files.")

    click.echo()
    click.echo("To remove the lockin binary, run one of:")
    if shutil.which("uv"):
        click.echo("  uv tool uninstall lockin-blocker")
    if shutil.which("pip") or shutil.which("pip3"):
        click.echo("  pip uninstall lockin-blocker")


if __name__ == "__main__":
    main()
