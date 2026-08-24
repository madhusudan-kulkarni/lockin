from unittest import mock

from lockin.notify import BODY, TITLE, notify_block_ended


def test_notify_as_user_calls_notify_send(monkeypatch):
    monkeypatch.setattr("lockin.notify.os.geteuid", lambda: 1000)
    monkeypatch.setenv("USER", "madhu")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    run = mock.MagicMock()
    monkeypatch.setattr("lockin.notify.subprocess.run", run)
    notify_block_ended()
    run.assert_called_once()
    args = run.call_args[0][0]
    assert args[0] == "notify-send"
    assert TITLE in args
    assert BODY in args


def test_notify_as_root_uses_sudo_u(monkeypatch):
    monkeypatch.setattr("lockin.notify.os.geteuid", lambda: 0)
    monkeypatch.setenv("WATCHDOG_USER", "madhu")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    run = mock.MagicMock()
    monkeypatch.setattr("lockin.notify.subprocess.run", run)
    notify_block_ended()
    args = run.call_args[0][0]
    assert args[:3] == ["sudo", "-u", "madhu"]
    assert "notify-send" in args


def test_notify_swallows_errors(monkeypatch):
    monkeypatch.setattr("lockin.notify.os.geteuid", lambda: 1000)
    monkeypatch.setattr(
        "lockin.notify.subprocess.run",
        mock.MagicMock(side_effect=OSError("missing")),
    )
    notify_block_ended()
