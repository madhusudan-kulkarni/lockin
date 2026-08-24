"""Tests for lockin.doctor."""

import json
from datetime import datetime, timedelta

from lockin.doctor import format_results, run_checks


def test_format_results_failed_mentions_failure():
    text = format_results([("firewall", False, "missing")])
    assert "failed" in text.lower()


def _patch_fs(
    monkeypatch, tmp_path, *, hosts_text, live_state=None, leftover_state=False
):
    home = tmp_path
    cfg = home / ".config" / "lockin"
    cfg.mkdir(parents=True)
    (cfg / "rules.yaml").write_text(
        "blacklists:\n  social:\n    - twitter.com\n"
    )
    if live_state is not None:
        (cfg / "state.json").write_text(json.dumps(live_state))
    elif leftover_state:
        (cfg / "state.json").write_text(json.dumps({
            "end": (datetime.now() - timedelta(hours=1)).isoformat(),
        }))
    hosts = tmp_path / "hosts"
    hosts.write_text(hosts_text)
    systemd = tmp_path / "run-systemd"
    systemd.mkdir()

    monkeypatch.setattr("lockin.doctor._user_home", lambda: home)
    monkeypatch.setattr("lockin.doctor._hosts_path", lambda: hosts)
    monkeypatch.setattr("lockin.doctor._systemd_run_path", lambda: systemd)
    monkeypatch.setattr(
        "lockin.doctor.shutil.which",
        lambda cmd: "/bin/x" if cmd in ("nft", "systemctl") else None,
    )


def test_idle_machine_passes(tmp_path, monkeypatch):
    _patch_fs(monkeypatch, tmp_path, hosts_text="127.0.0.1 localhost\n")
    monkeypatch.setattr("lockin.doctor._nft_table_present", lambda: False)
    monkeypatch.setattr("lockin.doctor._timer_active", lambda: False)
    results = run_checks()
    assert all(ok for _, ok, _ in results)


def test_live_session_is_ok(tmp_path, monkeypatch):
    end = (datetime.now() + timedelta(hours=1)).isoformat()
    _patch_fs(
        monkeypatch,
        tmp_path,
        hosts_text="# === lockin start ===\n127.0.0.2 twitter.com\n",
        live_state={"rule_name": "social", "end": end},
    )
    monkeypatch.setattr("lockin.doctor._nft_table_present", lambda: True)
    monkeypatch.setattr("lockin.doctor._timer_active", lambda: True)
    results = run_checks()
    by_name = {n: (ok, detail) for n, ok, detail in results}
    assert by_name["session"][0] is True
    assert "live" in by_name["session"][1]
    assert all(ok for ok, _ in by_name.values())


def test_missing_default_warns_but_passes(tmp_path, monkeypatch):
    home = tmp_path
    cfg = home / ".config" / "lockin"
    cfg.mkdir(parents=True)
    (cfg / "rules.yaml").write_text(
        "blacklists:\n"
        "  social:\n"
        "    - twitter.com\n"
        "  news:\n"
        "    - cnn.com\n"
    )
    hosts = tmp_path / "hosts"
    hosts.write_text("127.0.0.1 localhost\n")
    systemd = tmp_path / "run-systemd"
    systemd.mkdir()
    monkeypatch.setattr("lockin.doctor._user_home", lambda: home)
    monkeypatch.setattr("lockin.doctor._hosts_path", lambda: hosts)
    monkeypatch.setattr("lockin.doctor._systemd_run_path", lambda: systemd)
    monkeypatch.setattr(
        "lockin.doctor.shutil.which",
        lambda cmd: "/bin/x" if cmd in ("nft", "systemctl") else None,
    )
    monkeypatch.setattr("lockin.doctor._nft_table_present", lambda: False)
    monkeypatch.setattr("lockin.doctor._timer_active", lambda: False)
    results = run_checks()
    default_check = next(r for r in results if r[0] == "default rule")
    assert default_check[1] is True
    assert "default:" in default_check[2]
    assert all(ok for _, ok, _ in results)


def test_leftovers_fail(tmp_path, monkeypatch):
    _patch_fs(
        monkeypatch,
        tmp_path,
        hosts_text="# === lockin start ===\n",
    )
    monkeypatch.setattr("lockin.doctor._nft_table_present", lambda: True)
    monkeypatch.setattr("lockin.doctor._timer_active", lambda: False)
    results = run_checks()
    assert any(not ok for _, ok, _ in results)
    session = next(r for r in results if r[0] == "session")
    assert session[1] is False
