"""Tests for lockin.scheduler."""

import datetime
from unittest import mock

from lockin.scheduler import (
    _at_available,
    _cron_available,
    _systemd_available,
    cancel,
    schedule,
)


class TestAvailability:
    def test_systemd_available(self):
        with (
            mock.patch("os.path.exists", return_value=True),
            mock.patch("shutil.which", return_value="/usr/bin/systemctl"),
        ):
            assert _systemd_available() is True

    def test_systemd_not_available_no_systemctl(self):
        with (
            mock.patch("os.path.exists", return_value=True),
            mock.patch("shutil.which", return_value=None),
        ):
            assert _systemd_available() is False

    def test_systemd_not_available_no_run_systemd(self):
        with (
            mock.patch("os.path.exists", return_value=False),
            mock.patch("shutil.which", return_value="/usr/bin/systemctl"),
        ):
            assert _systemd_available() is False

    def test_at_available(self):
        with mock.patch("shutil.which", return_value="/usr/bin/at"):
            assert _at_available() is True

    def test_cron_available(self):
        with mock.patch("shutil.which", return_value="/usr/bin/crontab"):
            assert _cron_available() is True


class TestSchedule:
    def test_schedule_prefers_systemd(self):
        when = datetime.datetime(2026, 12, 31, 23, 59, 59)
        reset_cmd = "python /tmp/reset.py"

        with (
            mock.patch("lockin.scheduler._systemd_available", return_value=True),
            mock.patch("subprocess.run") as mock_run,
        ):
            method, job_id = schedule(when, reset_cmd)
            assert method == "systemd"
            mock_run.assert_called_once()

    def test_schedule_falls_back_to_at(self):
        when = datetime.datetime(2026, 12, 31, 23, 59, 59)
        reset_cmd = "python /tmp/reset.py"

        with (
            mock.patch("lockin.scheduler._systemd_available", return_value=False),
            mock.patch("lockin.scheduler._at_available", return_value=True),
            mock.patch("subprocess.run") as mock_run,
        ):
            method, job_id = schedule(when, reset_cmd)
            assert method == "at"
            mock_run.assert_called_once()

    def test_schedule_falls_back_to_thread(self):
        when = datetime.datetime(2026, 12, 31, 23, 59, 59)
        reset_cmd = "python /tmp/reset.py"

        with (
            mock.patch("lockin.scheduler._systemd_available", return_value=False),
            mock.patch("lockin.scheduler._at_available", return_value=False),
            mock.patch("lockin.scheduler._cron_available", return_value=False),
        ):
            method, job_id = schedule(when, reset_cmd)
            assert method == "thread"


class TestCancel:
    def test_cancel_systemd(self):
        with mock.patch("subprocess.run") as mock_run:
            cancel("systemd", "lockin-reset")
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert "systemctl" in args
            assert any("lockin-reset.timer" in a for a in args)

    def test_cancel_at(self):
        with mock.patch("subprocess.run") as mock_run:
            cancel("at", "42")
            mock_run.assert_called_once()
            args = mock_run.call_args[0][0]
            assert "atrm" in args
            assert "42" in args

    def test_cancel_thread_is_noop(self):
        # Thread cancellation is a no-op — should not raise
        cancel("thread", "any")
