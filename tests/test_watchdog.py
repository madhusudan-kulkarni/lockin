import datetime
import importlib
import json
import sys
from unittest import mock


def import_watchdog(monkeypatch, tmp_path):
    monkeypatch.setenv("LOCKIN_STATE", str(tmp_path / "state.json"))
    sys.modules.pop("lockin.watchdog", None)
    return importlib.import_module("lockin.watchdog")


def _future_state(tmp_path, **overrides):
    end = (
        datetime.datetime.now() + datetime.timedelta(hours=1)
    ).isoformat()
    state = {
        "start": "2026-08-24T10:00:00",
        "end": end,
        "domains": ["twitter.com"],
        "hardcore": True,
    }
    state.update(overrides)
    path = tmp_path / "state.json"
    path.write_text(json.dumps(state))
    return state


def test_watchdog_main_missing_state_is_noop(monkeypatch, tmp_path):
    watchdog = import_watchdog(monkeypatch, tmp_path)
    watchdog.main()


def test_watchdog_main_reapplies_when_live(monkeypatch, tmp_path):
    _future_state(tmp_path)
    watchdog = import_watchdog(monkeypatch, tmp_path)
    with (
        mock.patch("lockin.hosts.get_entries", return_value=[]),
        mock.patch("lockin.hosts.add_entries") as add,
        mock.patch("lockin.nat.setup") as setup,
        mock.patch("lockin.policies.apply") as apply,
        mock.patch("lockin.hosts.lock_hosts") as lock,
    ):
        watchdog.main()
        add.assert_called_once()
        setup.assert_called_once()
        apply.assert_called_once()
        lock.assert_called_once()


def test_watchdog_main_expires(monkeypatch, tmp_path):
    past = (
        datetime.datetime.now() - datetime.timedelta(minutes=1)
    ).isoformat()
    _future_state(tmp_path, end=past)
    watchdog = import_watchdog(monkeypatch, tmp_path)
    with (
        mock.patch("lockin.hosts.remove_entries") as remove,
        mock.patch("lockin.nat.reset") as reset,
        mock.patch("lockin.policies.clear") as clear,
        mock.patch("lockin.watchdog_install.remove") as wd_remove,
        mock.patch("lockin.browser.kill") as kill,
        mock.patch("lockin.notify.notify_block_ended") as note,
    ):
        watchdog.main()
        remove.assert_called_once()
        reset.assert_called_once()
        clear.assert_called_once()
        wd_remove.assert_called_once()
        kill.assert_called_once()
        note.assert_called_once()
        assert not (tmp_path / "state.json").exists()
