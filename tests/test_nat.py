"""Tests for lockin.nat."""

import subprocess
from unittest import mock

import pytest

from lockin.nat import (
    _iptables_reset_commands,
    _iptables_setup_commands,
    _nft_setup_commands,
    backend,
    reset,
    setup,
)


class TestBackendDetection:
    def test_nftables_when_nft_available(self):
        with mock.patch("shutil.which", lambda cmd: cmd == "nft"):
            assert backend() == "nftables"

    def test_iptables_when_only_iptables_available(self):
        def fake_which(cmd):
            return cmd == "iptables"
        with mock.patch("shutil.which", fake_which):
            assert backend() == "iptables"

    def test_raises_when_nothing_available(self):
        with (
            mock.patch("shutil.which", return_value=None),
            pytest.raises(RuntimeError, match="firewall"),
        ):
            backend()


class TestNftCommands:
    def test_setup_commands(self):
        cmds = _nft_setup_commands()
        assert len(cmds) >= 3  # add table, add chain, flush, rule

    def test_setup_includes_udp_drop(self):
        cmds = _nft_setup_commands()
        drop_cmds = [c for c in cmds if "reject" in str(c) or "drop" in str(c)]
        assert len(drop_cmds) >= 1

    def test_setup_drops_udp_443(self):
        cmds = _nft_setup_commands()
        quic_cmds = [
            c for c in cmds if "udp" in str(c) and "443" in str(c)
        ]
        assert len(quic_cmds) >= 1


class TestIptablesCommands:
    def test_setup_commands(self):
        cmds = _iptables_setup_commands()
        assert len(cmds) == 2  # iptables + ip6tables

    def test_setup_drops_udp(self):
        cmds = _iptables_setup_commands()
        for cmd in cmds:
            assert "udp" in str(cmd)
            assert "REJECT" in str(cmd)

    def test_reset_commands(self):
        cmds = _iptables_reset_commands()
        assert len(cmds) == 2
        assert all("-D" in str(c) for c in cmds)
        assert all("REJECT" in str(c) for c in cmds)


class TestSetupReset:
    def test_setup_calls_nft_when_nftables(self):
        with (
            mock.patch("lockin.nat.backend", return_value="nftables"),
            mock.patch("subprocess.run") as mock_run,
        ):
            setup()
            assert mock_run.call_count >= 3

    def test_setup_calls_iptables_when_iptables(self):
        with (
            mock.patch("lockin.nat.backend", return_value="iptables"),
            mock.patch("subprocess.run") as mock_run,
        ):
            setup()
            assert mock_run.call_count >= 2

    def test_reset_calls_backend(self):
        with (
            mock.patch("lockin.nat.backend", return_value="nftables"),
            mock.patch("subprocess.run") as mock_run,
        ):
            reset()
            mock_run.assert_called()

    def test_setup_raises_on_subprocess_error(self):
        with (
            mock.patch("lockin.nat.backend", return_value="nftables"),
            mock.patch(
                "subprocess.run",
                side_effect=subprocess.CalledProcessError(1, "nft"),
            ),
            pytest.raises(subprocess.CalledProcessError),
        ):
            setup()
