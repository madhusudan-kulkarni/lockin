"""Tests for lockin CLI."""

from unittest import mock

import pytest
from click.testing import CliRunner

from lockin.cli import main


@pytest.fixture
def runner():
    return CliRunner()


class TestListCommand:
    def test_list_shows_rules(self, runner, tmp_path):
        rules_path = tmp_path / "rules.yaml"
        rules_path.write_text(
            "whitelists:\n"
            "  coding:\n"
            "    - github.com\n"
            "blacklists:\n"
            "  social:\n"
            "    - twitter.com\n"
        )
        with (
            mock.patch("lockin.cli.ensure_user_rules"),
            mock.patch(
                "lockin.cli.get_rules_path", return_value=rules_path
            ),
        ):
            result = runner.invoke(main, ["list"])
            assert result.exit_code == 0
            assert "coding" in result.output
            assert "social" in result.output
            assert "blocklist" in result.output
            assert "whitelist" not in result.output

    def test_list_empty_rules(self, runner, tmp_path):
        rules_path = tmp_path / "rules.yaml"
        rules_path.write_text("whitelists: {}\nblacklists: {}\n")
        with (
            mock.patch("lockin.cli.ensure_user_rules"),
            mock.patch(
                "lockin.cli.get_rules_path", return_value=rules_path
            ),
        ):
            result = runner.invoke(main, ["list"])
            assert result.exit_code == 0


class TestStatusCommand:
    def test_status_no_block(self, runner):
        with (
            mock.patch("lockin.block.get_state", return_value=None),
            mock.patch("lockin.block.get_entries", return_value=[]),
        ):
            result = runner.invoke(main, ["status"])
            assert result.exit_code == 0
            assert "No active block" in result.output

    def test_status_json_idle(self, runner):
        with mock.patch(
            "lockin.cli.get_status_data", return_value={"active": False}
        ):
            result = runner.invoke(main, ["status", "--json"])
            assert result.exit_code == 0
            import json
            data = json.loads(result.output)
            assert data["active"] is False


class TestStopCommand:
    def test_stop_no_block(self, runner):
        with mock.patch(
            "lockin.block.get_state", return_value=None
        ):
            result = runner.invoke(main, ["stop"])
            assert result.exit_code == 3

    def test_stop_hardcore_no_traceback(self, runner):
        with mock.patch(
            "lockin.cli.stop_block",
            side_effect=RuntimeError(
                "Hardcore mode is active. Use 'lockin unlock' to end the session."
            ),
        ):
            result = runner.invoke(main, ["stop"])
            assert result.exit_code == 1
            assert "Hardcore mode is active" in result.output
            assert result.exception is None or result.exit_code == 1
            assert "Traceback" not in (result.output + (result.stderr or ""))


class TestStartCommand:
    def test_start_without_rule(self, runner):
        result = runner.invoke(main, ["start"])
        assert result.exit_code != 0

    def test_start_without_duration(self, runner):
        result = runner.invoke(main, ["start", "--rule", "coding"])
        assert result.exit_code != 0

    def test_start_for_without_rule_uses_default(self, runner):
        with mock.patch("lockin.cli.start_block") as mock_start:
            mock_start.return_value = {
                "rule_name": "social",
                "block_type": "blacklist",
                "domains": ["twitter.com"],
                "end": "2099-01-01T00:00:00",
            }
            result = runner.invoke(main, ["start", "--for", "30m"])
            assert result.exit_code == 0
            mock_start.assert_called_once()
            assert mock_start.call_args.kwargs["rule_name"] is None

    def test_start_stacked_rules(self, runner):
        with mock.patch("lockin.cli.start_block") as mock_start:
            mock_start.return_value = {
                "rule_name": "news,social",
                "block_type": "blacklist",
                "domains": ["twitter.com"],
                "end": "2099-01-01T00:00:00",
            }
            result = runner.invoke(
                main, ["start", "--rule", "social,news", "--for", "30m"]
            )
            assert result.exit_code == 0
            assert mock_start.call_args.kwargs["rule_name"] == ["social", "news"]

    def test_start_output_no_firefox_settings_line(self, runner):
        with mock.patch("lockin.cli.start_block") as mock_start:
            mock_start.return_value = {
                "rule_name": "social",
                "block_type": "blacklist",
                "domains": ["twitter.com"],
                "end": "2099-01-01T00:00:00",
                "browsers": ["firefox"],
            }
            result = runner.invoke(main, ["start", "--for", "30m"])
            assert result.exit_code == 0
            assert "DNS over HTTPS" not in result.output
            assert "Firefox: Settings" not in result.output
            assert "Reopen" in result.output
            assert "after the block ends" not in result.output.lower()
            assert "NOW" in result.output or "now" in result.output

    def test_start_shows_blocklist_not_blacklist(self, runner):
        with mock.patch("lockin.cli.start_block") as mock_start:
            mock_start.return_value = {
                "rule_name": "social",
                "block_type": "blacklist",
                "domains": ["twitter.com"],
                "end": "2099-01-01T00:00:00",
            }
            result = runner.invoke(main, ["start", "--for", "30m"])
            assert result.exit_code == 0
            assert "blocklist" in result.output
            assert "blacklist" not in result.output

    def test_start_hardcore_mentions_unlock(self, runner):
        with mock.patch("lockin.cli.start_block") as mock_start:
            mock_start.return_value = {
                "rule_name": "social",
                "block_type": "blacklist",
                "domains": ["twitter.com"],
                "end": "2099-01-01T00:00:00",
            }
            result = runner.invoke(main, ["start", "--for", "30m"])
            assert result.exit_code == 0
            assert "unlock --now" in result.output
            assert "stop" in result.output.lower()

    def test_start_soft_does_not_mention_hardcore_unlock(self, runner):
        with mock.patch("lockin.cli.start_block") as mock_start:
            mock_start.return_value = {
                "rule_name": "social",
                "block_type": "blacklist",
                "domains": ["twitter.com"],
                "end": "2099-01-01T00:00:00",
            }
            result = runner.invoke(
                main, ["start", "--soft", "--rule", "social", "--for", "30m"]
            )
            assert result.exit_code == 0
            assert "unlock --now" not in result.output

    def test_start_invalid_rule(self, runner, tmp_path):
        rules_path = tmp_path / "rules.yaml"
        rules_path.write_text("whitelists: {}\nblacklists: {}\n")
        with (
            mock.patch(
                "lockin.cli.get_rules_path", return_value=rules_path
            ),
            mock.patch("lockin.cli.start_block") as mock_start,
        ):
            mock_start.side_effect = ValueError(
                "Rule 'coding' not found. Available: none"
            )
            result = runner.invoke(
                main, ["start", "--rule", "coding", "--for", "30m"]
            )
            assert result.exit_code == 4


class TestUnlockCommand:
    def test_unlock_no_block(self, runner):
        with mock.patch("lockin.cli.get_state", return_value=None):
            result = runner.invoke(main, ["unlock"])
            assert result.exit_code == 3

    def test_unlock_now_calls_end_session(self, runner):
        with (
            mock.patch(
                "lockin.cli.get_state",
                return_value={"rule_name": "social", "end": "2099-01-01T00:00:00"},
            ),
            mock.patch("lockin.cli.end_session") as mock_end,
            mock.patch("lockin.cli.notify_block_ended") as mock_note,
        ):
            result = runner.invoke(main, ["unlock", "--now"], input="yes\n")
            assert result.exit_code == 0
            mock_end.assert_called_once_with(force=True)
            mock_note.assert_called_once()


class TestCleanupCommand:
    def test_cleanup_without_state(self, runner):
        with (
            mock.patch("lockin.cli.get_state", return_value=None),
            mock.patch("lockin.cli.end_session") as mock_end,
        ):
            result = runner.invoke(main, ["cleanup"])
            assert result.exit_code == 0
            mock_end.assert_called_once_with(force=True)
            assert "Done" in result.output
