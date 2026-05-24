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
        with mock.patch(
            "lockin.cli.get_rules_path", return_value=rules_path
        ):
            result = runner.invoke(main, ["list"])
            assert result.exit_code == 0
            assert "coding" in result.output
            assert "social" in result.output
            assert "whitelist" in result.output
            assert "blacklist" in result.output

    def test_list_empty_rules(self, runner, tmp_path):
        rules_path = tmp_path / "rules.yaml"
        rules_path.write_text("whitelists: {}\nblacklists: {}\n")
        with mock.patch(
            "lockin.cli.get_rules_path", return_value=rules_path
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


class TestStopCommand:
    def test_stop_no_block(self, runner):
        with mock.patch(
            "lockin.block.get_state", return_value=None
        ):
            result = runner.invoke(main, ["stop"])
            assert result.exit_code == 3


class TestStartCommand:
    def test_start_without_rule(self, runner):
        result = runner.invoke(main, ["start"])
        assert result.exit_code != 0

    def test_start_without_duration(self, runner):
        result = runner.invoke(main, ["start", "--rule", "coding"])
        assert result.exit_code != 0

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
