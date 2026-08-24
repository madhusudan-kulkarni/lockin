"""Tests for lockin.block - hosts-based orchestration."""

import datetime
import tempfile
from pathlib import Path
from unittest import mock

import pytest

from lockin.block import (
    clear_state,
    end_session,
    find_rule,
    get_state,
    is_block_active,
    list_rules,
    load_rules,
    parse_duration,
    parse_until,
    request_unlock,
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


class TestParseUntil:
    def test_24h(self):
        now = datetime.datetime(2026, 8, 24, 10, 0)
        end = parse_until("17:00", now)
        assert end.hour == 17
        assert end.minute == 0
        assert end.day == 24

    def test_12h_pm(self):
        now = datetime.datetime(2026, 8, 24, 10, 0)
        end = parse_until("9:30pm", now)
        assert end.hour == 21
        assert end.minute == 30

    def test_12h_with_space(self):
        now = datetime.datetime(2026, 8, 24, 10, 0)
        end = parse_until("9:30 PM", now)
        assert end.hour == 21

    def test_rolls_to_tomorrow(self):
        now = datetime.datetime(2026, 8, 24, 22, 0)
        end = parse_until("17:00", now)
        assert end.day == 25

    def test_invalid(self):
        with pytest.raises(ValueError, match="Invalid time"):
            parse_until("noon", datetime.datetime.now())


class TestStateFile:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.state_path = Path(self.tmpdir) / "state.json"

    def test_get_state_no_file(self):
        assert get_state(self.state_path) is None

    def test_save_and_get_state(self):
        state = {
            "rule_name": "social",
            "block_type": "blacklist",
            "domains": ["twitter.com"],
            "start": "2026-05-24T14:30:00",
            "end": "2026-05-24T16:30:00",
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
            "blacklists:\n"
            "  social:\n"
            "    - twitter.com\n"
        )
        rules = load_rules(self.rules_path)
        assert rules["blacklists"]["social"] == ["twitter.com"]

    def test_find_rule_in_blacklists(self):
        rules = {
            "blacklists": {"social": ["twitter.com"]},
        }
        name, block_type, addresses = find_rule("social", rules)
        assert name == "social"
        assert block_type == "blacklist"
        assert addresses == ["twitter.com"]

    def test_legacy_whitelists_are_blocklists(self):
        rules = {
            "whitelists": {"coding": ["github.com"]},
            "blacklists": {},
        }
        name, block_type, addresses = find_rule("coding", rules)
        assert name == "coding"
        assert block_type == "blacklist"
        assert addresses == ["github.com"]

    def test_find_rule_not_found(self):
        rules = {"whitelists": {}, "blacklists": {}}
        with pytest.raises(ValueError, match="not found"):
            find_rule("nonexistent", rules)

    def test_find_rule_case_sensitive(self):
        rules = {"blacklists": {"Social": ["twitter.com"]}}
        with pytest.raises(ValueError):
            find_rule("social", rules)

    def test_list_rules_blocklist_type(self):
        self.rules_path.write_text(
            "whitelists:\n"
            "  coding:\n"
            "    - github.com\n"
            "blacklists:\n"
            "  social:\n"
            "    - twitter.com\n"
        )
        result = list_rules(self.rules_path)
        assert len(result) == 2
        types = {r[1] for r in result}
        assert types == {"blocklist"}


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
        tmp = tempfile.mkdtemp()
        state_file = Path(tmp) / "state.json"
        rules_file = Path(tmp) / "rules.yaml"
        rules_file.write_text(
            "blacklists:\n"
            "  social:\n"
            "    - twitter.com\n"
            "    - facebook.com\n"
        )
        self.mock_add = mock.MagicMock()
        self.mock_remove = mock.MagicMock()
        self.mock_nat_setup = mock.MagicMock()
        self.mock_nat_reset = mock.MagicMock()
        self.mock_watchdog_remove = mock.MagicMock()

        monkeypatch.setattr("lockin.block.STATE_FILE", state_file)
        monkeypatch.setattr(
            "lockin.block.get_rules_path", lambda: rules_file
        )
        monkeypatch.setattr("lockin.block.ensure_user_rules", lambda: rules_file)
        monkeypatch.setattr("lockin.block.add_entries", self.mock_add)
        monkeypatch.setattr("lockin.block.nat.setup", self.mock_nat_setup)
        monkeypatch.setattr("lockin.block.nat.reset", self.mock_nat_reset)
        monkeypatch.setattr("lockin.block.nat.backend", lambda: "nftables")
        monkeypatch.setattr(
            "lockin.block.remove_entries", self.mock_remove
        )
        monkeypatch.setattr("lockin.block.get_entries", lambda: [])
        monkeypatch.setattr("lockin.block.lock_hosts", mock.MagicMock())
        monkeypatch.setattr("lockin.block._install_watchdog", mock.MagicMock())
        monkeypatch.setattr(
            "lockin.block._remove_watchdog", self.mock_watchdog_remove
        )
        monkeypatch.setattr(
            "lockin.block.browser.kill", mock.MagicMock(return_value=[])
        )
        monkeypatch.setattr("lockin.block.policies.apply", mock.MagicMock())
        monkeypatch.setattr("lockin.block.policies.clear", mock.MagicMock())
        monkeypatch.setattr("lockin.block.notify_block_ended", mock.MagicMock())

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

        self.mock_remove.assert_called()
        self.mock_nat_reset.assert_called()
        self.mock_watchdog_remove.assert_called()

    def test_start_block_rejects_already_active(self, monkeypatch):
        self._patch_all(monkeypatch)

        start_block("social", duration_minutes=30)
        with pytest.raises(RuntimeError, match="already active"):
            start_block("social", duration_minutes=30)

    def test_start_rolls_back_if_nat_fails(self, monkeypatch):
        self._patch_all(monkeypatch)
        self.mock_nat_setup.side_effect = RuntimeError("nft failed")

        with pytest.raises(RuntimeError, match="nft failed"):
            start_block("social", duration_minutes=30)

        self.mock_remove.assert_called()
        self.mock_nat_reset.assert_called()
        assert get_state() is None

    def test_end_session_force_without_state(self, monkeypatch):
        self._patch_all(monkeypatch)
        result = end_session(force=True)
        assert result is None
        self.mock_remove.assert_called()
        self.mock_nat_reset.assert_called()
        self.mock_watchdog_remove.assert_called()

    def test_end_session_noop_without_state(self, monkeypatch):
        self._patch_all(monkeypatch)
        result = end_session(force=False)
        assert result is None
        self.mock_remove.assert_not_called()


class TestRequestUnlock:
    def _patch_state(self, monkeypatch, end, unlock_requested=False):
        tmp = tempfile.mkdtemp()
        state_file = Path(tmp) / "state.json"
        monkeypatch.setattr("lockin.block.STATE_FILE", state_file)
        state = {
            "rule_name": "social",
            "block_type": "blacklist",
            "end": end.isoformat(),
            "unlock_requested": unlock_requested,
        }
        save_state(state, state_file)
        return state_file

    def test_shortens_long_block(self, monkeypatch):
        end = datetime.datetime.now() + datetime.timedelta(hours=3)
        self._patch_state(monkeypatch, end)
        state, shortened = request_unlock(30)
        assert shortened is True
        assert state["unlock_requested"] is True
        new_end = datetime.datetime.fromisoformat(state["end"])
        assert new_end < end

    def test_does_not_lengthen(self, monkeypatch):
        end = datetime.datetime.now() + datetime.timedelta(minutes=5)
        self._patch_state(monkeypatch, end)
        state, shortened = request_unlock(30)
        assert shortened is False
        assert datetime.datetime.fromisoformat(state["end"]) == end

    def test_second_request_refused(self, monkeypatch):
        end = datetime.datetime.now() + datetime.timedelta(hours=3)
        self._patch_state(monkeypatch, end)
        request_unlock(30)
        with pytest.raises(RuntimeError, match="already requested"):
            request_unlock(30)


class TestResolveRules:
    def test_union_sorted_name(self):
        from lockin.block import resolve_rules

        rules = {
            "blacklists": {
                "news": ["cnn.com"],
                "social": ["twitter.com"],
            }
        }
        name, addrs = resolve_rules(["news", "social"], rules)
        assert name == "news,social"
        assert "cnn.com" in addrs
        assert "twitter.com" in addrs

    def test_yaml_default(self):
        from lockin.block import resolve_rules

        rules = {
            "default": "social",
            "blacklists": {
                "news": ["cnn.com"],
                "social": ["twitter.com"],
            },
        }
        name, addrs = resolve_rules([], rules)
        assert name == "social"
        assert addrs == ["twitter.com"]

    def test_single_rule_without_default(self):
        from lockin.block import resolve_rules

        rules = {"blacklists": {"social": ["twitter.com"]}}
        name, addrs = resolve_rules([], rules)
        assert name == "social"
        assert addrs == ["twitter.com"]

    def test_ambiguous_without_default(self):
        from lockin.block import resolve_rules

        rules = {
            "blacklists": {
                "news": ["cnn.com"],
                "social": ["twitter.com"],
            }
        }
        with pytest.raises(ValueError, match="Must specify --rule"):
            resolve_rules([], rules)


def test_start_block_stores_expanded_domains(monkeypatch):
    tmp = tempfile.mkdtemp()
    state_file = Path(tmp) / "state.json"
    rules_file = Path(tmp) / "rules.yaml"
    rules_file.write_text(
        "blacklists:\n"
        "  social:\n"
        "    - reddit.com\n"
    )
    monkeypatch.setattr("lockin.block.STATE_FILE", state_file)
    monkeypatch.setattr("lockin.block.get_rules_path", lambda: rules_file)
    monkeypatch.setattr("lockin.block.ensure_user_rules", lambda: rules_file)
    mock_add = mock.MagicMock()
    monkeypatch.setattr("lockin.block.add_entries", mock_add)
    monkeypatch.setattr("lockin.block.nat.setup", mock.MagicMock())
    monkeypatch.setattr("lockin.block.nat.reset", mock.MagicMock())
    monkeypatch.setattr("lockin.block.nat.backend", lambda: "nftables")
    monkeypatch.setattr("lockin.block.remove_entries", mock.MagicMock())
    monkeypatch.setattr("lockin.block.lock_hosts", mock.MagicMock())
    monkeypatch.setattr("lockin.block._install_watchdog", mock.MagicMock())
    monkeypatch.setattr("lockin.block._remove_watchdog", mock.MagicMock())
    monkeypatch.setattr("lockin.block.browser.kill", mock.MagicMock(return_value=[]))
    monkeypatch.setattr("lockin.block.policies.apply", mock.MagicMock())
    monkeypatch.setattr("lockin.block.policies.clear", mock.MagicMock())

    state = start_block("social", duration_minutes=30)
    assert "old.reddit.com" in state["domains"]
    assert "old.reddit.com" in mock_add.call_args[0][0]


class TestGetStatus:
    def test_missing_hosts_does_not_recommend_cleanup(self, monkeypatch):
        from lockin.block import get_status

        future = (
            datetime.datetime.now() + datetime.timedelta(hours=1)
        ).isoformat()
        with (
            mock.patch(
                "lockin.block.get_state",
                return_value={
                    "rule_name": "social",
                    "block_type": "blacklist",
                    "end": future,
                },
            ),
            mock.patch("lockin.block.get_entries", return_value=[]),
            mock.patch("lockin.block.nat.probe", return_value="active"),
        ):
            text = get_status()
            assert "cleanup" not in text.lower()
            assert "watchdog" in text.lower()


def test_default_rules_are_hostnames_only():
    from lockin.block import DEFAULT_RULES_PATH, load_rules

    rules = load_rules(DEFAULT_RULES_PATH)
    assert not rules.get("whitelists")
    assert rules.get("default") == "social"
    assert "social" in rules["blacklists"]
    assert "news" in rules["blacklists"]
    for addresses in rules["blacklists"].values():
        for name in addresses:
            assert "/" not in name
            assert "*" not in name
