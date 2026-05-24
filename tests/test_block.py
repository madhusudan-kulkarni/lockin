"""Tests for lockin.block - hosts-based orchestration."""

import datetime
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from lockin.block import (
    clear_state,
    find_rule,
    get_state,
    is_block_active,
    list_rules,
    load_rules,
    parse_duration,
    save_state,
    start_block,
    stop_block,
)


class TestParseDuration:
    def test_minutes(self):
        assert parse_duration("30m") == 30

    def test_hours(self):
        assert parse_duration("2h") == 120

    def test_hours_and_minutes(self):
        assert parse_duration("1h30m") == 90

    def test_just_hours(self):
        assert parse_duration("3h") == 180

    def test_invalid_format(self):
        with pytest.raises(ValueError):
            parse_duration("abc")

    def test_zero(self):
        with pytest.raises(ValueError):
            parse_duration("0m")


class TestStateFile:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = Path(self.tmpdir) / "state.json"

    def test_get_state_no_file(self):
        assert get_state(self.state_path) is None

    def test_save_and_get_state(self):
        state = {
            "rule_name": "coding",
            "block_type": "whitelist",
            "domains": ["github.com"],
            "start": "2026-05-24T14:30:00",
            "end": "2026-05-24T16:30:00",
            "schedule_method": "systemd",
            "schedule_id": "lockin-reset",
        }
        save_state(state, self.state_path)
        loaded = get_state(self.state_path)
        assert loaded == state

    def test_clear_state(self):
        state = {"rule_name": "test", "block_type": "blacklist"}
        save_state(state, self.state_path)
        clear_state(self.state_path)
        assert get_state(self.state_path) is None


class TestRules:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.rules_path = Path(self.tmpdir) / "rules.yaml"

    def test_load_rules(self):
        self.rules_path.write_text(
            "whitelists:\n"
            "  coding:\n"
            "    - github.com\n"
            "    - stackoverflow.com\n"
            "blacklists:\n"
            "  social:\n"
            "    - twitter.com\n"
            "    - facebook.com\n"
        )
        rules = load_rules(self.rules_path)
        assert "whitelists" in rules
        assert "blacklists" in rules
        assert rules["whitelists"]["coding"] == [
            "github.com",
            "stackoverflow.com",
        ]

    def test_find_rule_in_whitelists(self):
        rules = {
            "whitelists": {"coding": ["github.com"]},
            "blacklists": {},
        }
        name, block_type, addresses = find_rule("coding", rules)
        assert name == "coding"
        assert block_type == "whitelist"
        assert addresses == ["github.com"]

    def test_find_rule_in_blacklists(self):
        rules = {
            "whitelists": {},
            "blacklists": {"social": ["twitter.com"]},
        }
        name, block_type, addresses = find_rule("social", rules)
        assert name == "social"
        assert block_type == "blacklist"
        assert addresses == ["twitter.com"]

    def test_find_rule_not_found(self):
        rules = {"whitelists": {}, "blacklists": {}}
        with pytest.raises(ValueError, match="not found"):
            find_rule("nonexistent", rules)

    def test_find_rule_case_sensitive(self):
        rules = {"whitelists": {"Coding": ["github.com"]}, "blacklists": {}}
        with pytest.raises(ValueError):
            find_rule("coding", rules)

    def test_list_rules(self):
        self.rules_path.write_text(
            "whitelists:\n"
            "  coding:\n"
            "    - github.com\n"
            "    - stackoverflow.com\n"
            "blacklists:\n"
            "  social:\n"
            "    - twitter.com\n"
        )
        result = list_rules(self.rules_path)
        assert len(result) == 2
        names = [r[0] for r in result]
        assert "coding" in names
        assert "social" in names


class TestBlockActive:
    def test_not_active_when_no_state(self):
        assert is_block_active(None) is False

    def test_active_when_end_in_future(self):
        future = (
            datetime.datetime.now() + datetime.timedelta(hours=1)
        ).isoformat()
        state = {"end": future}
        assert is_block_active(state) is True

    def test_not_active_when_end_in_past(self):
        past = (
            datetime.datetime.now() - datetime.timedelta(hours=1)
        ).isoformat()
        state = {"end": past}
        assert is_block_active(state) is False


class TestStartStopBlock:
    def _patch_all(self, monkeypatch):
        """Mock all external calls for start/stop tests."""
        tmp = tempfile.mkdtemp()
        state_file = Path(tmp) / "state.json"
        rules_file = Path(tmp) / "rules.yaml"
        rules_file.write_text(
            "whitelists:\n"
            "  coding:\n"
            "    - github.com\n"
            "    - stackoverflow.com\n"
            "blacklists:\n"
            "  social:\n"
            "    - twitter.com\n"
            "    - facebook.com\n"
        )
        self.mock_add = mock.MagicMock()
        self.mock_remove = mock.MagicMock()
        self.mock_nat_setup = mock.MagicMock()
        self.mock_nat_reset = mock.MagicMock()

        monkeypatch.setattr("lockin.block.STATE_FILE", state_file)
        monkeypatch.setattr(
            "lockin.block.get_rules_path", lambda: rules_file
        )
        monkeypatch.setattr("lockin.block.add_entries", self.mock_add)
        monkeypatch.setattr("lockin.block.nat.setup", self.mock_nat_setup)
        monkeypatch.setattr("lockin.block.nat.reset", self.mock_nat_reset)
        monkeypatch.setattr(
            "lockin.block.remove_entries", self.mock_remove
        )
        monkeypatch.setattr("lockin.block.get_entries", lambda: [])
        monkeypatch.setattr("lockin.block.lock_hosts", mock.MagicMock())
        monkeypatch.setattr("lockin.block._install_watchdog", mock.MagicMock())
        monkeypatch.setattr("lockin.block._remove_watchdog", mock.MagicMock())
        monkeypatch.setattr(
            "lockin.block.browser.kill", mock.MagicMock(return_value=[])
        )
        monkeypatch.setattr("lockin.block.policies.apply", mock.MagicMock())
        monkeypatch.setattr("lockin.block.policies.clear", mock.MagicMock())

    def test_start_block_writes_state(self, monkeypatch):
        self._patch_all(monkeypatch)

        state = start_block("social", duration_minutes=30)
        assert state["rule_name"] == "social"
        assert state["block_type"] == "blacklist"
        assert "domains" in state
        assert state["end"] > state["start"]

    def test_start_block_calls_hosts_and_nat(self, monkeypatch):
        self._patch_all(monkeypatch)

        start_block("social", duration_minutes=30)
        self.mock_add.assert_called_once()
        self.mock_nat_setup.assert_called_once()

    def test_stop_block_cleans_up(self, monkeypatch):
        self._patch_all(monkeypatch)

        start_block("social", duration_minutes=30, hardcore=False)
        stop_block()

        self.mock_remove.assert_called_once()
        self.mock_nat_reset.assert_called_once()

    def test_start_block_rejects_already_active(self, monkeypatch):
        self._patch_all(monkeypatch)

        start_block("social", duration_minutes=30)
        with pytest.raises(RuntimeError, match="already active"):
            start_block("coding", duration_minutes=30)
