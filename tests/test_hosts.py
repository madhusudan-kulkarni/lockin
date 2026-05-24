"""Tests for lockin.hosts — /etc/hosts manager."""

import tempfile
import textwrap
from pathlib import Path
from unittest import mock

import pytest

from lockin.hosts import (
    MARKER_END,
    MARKER_START,
    add_entries,
    get_entries,
    remove_entries,
)


def _mock_write(hosts_path: Path):
    """Mock _write_hosts to write directly instead of via sudo."""
    def fake_write(lines):
        content = "\n".join(lines) + "\n"
        hosts_path.write_text(content)
    return fake_write


@pytest.fixture
def hosts_file():
    """Create a temp hosts file and mock HOSTS_PATH + _write_hosts."""
    with tempfile.NamedTemporaryFile(mode="w+", delete=False) as f:
        f.write(textwrap.dedent("""\
            127.0.0.1 localhost
            ::1 localhost

            192.168.1.1 my-server
        """))
    path = Path(f.name)
    yield path
    path.unlink(missing_ok=True)


class TestAddEntries:
    def test_adds_entries_with_markers(self, hosts_file, monkeypatch):
        monkeypatch.setattr("lockin.hosts.HOSTS_PATH", hosts_file)
        monkeypatch.setattr(
            "lockin.hosts._write_hosts", _mock_write(hosts_file)
        )
        add_entries(["twitter.com", "facebook.com"])

        content = hosts_file.read_text()
        assert MARKER_START in content
        assert MARKER_END in content
        assert "127.0.0.2 twitter.com www.twitter.com" in content
        assert "127.0.0.2 facebook.com www.facebook.com" in content
        assert "::1 twitter.com www.twitter.com" in content
        assert "::1 facebook.com www.facebook.com" in content

    def test_adds_only_given_domains(self, hosts_file, monkeypatch):
        monkeypatch.setattr("lockin.hosts.HOSTS_PATH", hosts_file)
        monkeypatch.setattr(
            "lockin.hosts._write_hosts", _mock_write(hosts_file)
        )
        add_entries(["github.com"])
        content = hosts_file.read_text()
        assert "github.com" in content

    def test_preserves_existing_content(self, hosts_file, monkeypatch):
        monkeypatch.setattr("lockin.hosts.HOSTS_PATH", hosts_file)
        monkeypatch.setattr(
            "lockin.hosts._write_hosts", _mock_write(hosts_file)
        )
        add_entries(["reddit.com"])
        content = hosts_file.read_text()
        assert "127.0.0.1 localhost" in content
        assert "192.168.1.1 my-server" in content

    def test_overwrites_existing_lockin_markers(self, hosts_file, monkeypatch):
        monkeypatch.setattr("lockin.hosts.HOSTS_PATH", hosts_file)
        monkeypatch.setattr(
            "lockin.hosts._write_hosts", _mock_write(hosts_file)
        )
        add_entries(["old.com"])
        add_entries(["new.com"])

        content = hosts_file.read_text()
        marker_count = content.count(MARKER_START)
        assert marker_count == 1, "should not duplicate markers"
        assert "new.com" in content
        assert "old.com" not in content

    def test_includes_ipv6_entries(self, hosts_file, monkeypatch):
        monkeypatch.setattr("lockin.hosts.HOSTS_PATH", hosts_file)
        monkeypatch.setattr(
            "lockin.hosts._write_hosts", _mock_write(hosts_file)
        )
        add_entries(["example.com"])

        content = hosts_file.read_text()
        assert "127.0.0.2 example.com www.example.com" in content
        assert "::1 example.com www.example.com" in content

    def test_calls_flush_cache(self, hosts_file, monkeypatch):
        monkeypatch.setattr("lockin.hosts.HOSTS_PATH", hosts_file)
        monkeypatch.setattr(
            "lockin.hosts._write_hosts", _mock_write(hosts_file)
        )
        mock_run = mock.MagicMock()
        monkeypatch.setattr("subprocess.run", mock_run)

        add_entries(["test.com"])
        flush_calls = [
            c for c in mock_run.call_args_list
            if "resolvectl" in str(c)
        ]
        assert len(flush_calls) >= 1


class TestGetEntries:
    def test_returns_domains(self, hosts_file, monkeypatch):
        monkeypatch.setattr("lockin.hosts.HOSTS_PATH", hosts_file)
        monkeypatch.setattr(
            "lockin.hosts._write_hosts", _mock_write(hosts_file)
        )
        add_entries(["a.com", "b.com"])
        domains = get_entries()
        assert "a.com" in domains
        assert "b.com" in domains

    def test_returns_empty_when_no_markers(self, hosts_file, monkeypatch):
        monkeypatch.setattr("lockin.hosts.HOSTS_PATH", hosts_file)
        assert get_entries() == []

    def test_excludes_extra_from_results(self, hosts_file, monkeypatch):
        monkeypatch.setattr("lockin.hosts.HOSTS_PATH", hosts_file)
        monkeypatch.setattr(
            "lockin.hosts._write_hosts", _mock_write(hosts_file)
        )
        add_entries(["mysite.com"])
        domains = get_entries()
        assert "mysite.com" in domains
        assert len(domains) == 1


class TestRemoveEntries:
    def test_removes_lockin_block(self, hosts_file, monkeypatch):
        monkeypatch.setattr("lockin.hosts.HOSTS_PATH", hosts_file)
        monkeypatch.setattr(
            "lockin.hosts._write_hosts", _mock_write(hosts_file)
        )
        add_entries(["blocked.com"])
        remove_entries()

        content = hosts_file.read_text()
        assert MARKER_START not in content
        assert MARKER_END not in content
        assert "blocked.com" not in content

    def test_preserves_non_lockin_content(self, hosts_file, monkeypatch):
        monkeypatch.setattr("lockin.hosts.HOSTS_PATH", hosts_file)
        monkeypatch.setattr(
            "lockin.hosts._write_hosts", _mock_write(hosts_file)
        )
        add_entries(["blocked.com"])
        remove_entries()

        content = hosts_file.read_text()
        assert "127.0.0.1 localhost" in content
        assert "192.168.1.1 my-server" in content

    def test_idempotent_no_markers(self, hosts_file, monkeypatch):
        monkeypatch.setattr("lockin.hosts.HOSTS_PATH", hosts_file)
        monkeypatch.setattr(
            "lockin.hosts._write_hosts", _mock_write(hosts_file)
        )
        remove_entries()
        content = hosts_file.read_text()
        assert "127.0.0.1 localhost" in content


class TestHostsWithSymlink:
    def test_follows_symlink(self, tmp_path, monkeypatch):
        real_hosts = tmp_path / "real_hosts"
        real_hosts.write_text("127.0.0.1 localhost\n")
        symlink_hosts = tmp_path / "hosts"
        symlink_hosts.symlink_to(real_hosts)

        monkeypatch.setattr("lockin.hosts.HOSTS_PATH", symlink_hosts)
        monkeypatch.setattr(
            "lockin.hosts._write_hosts", _mock_write(real_hosts)
        )
        add_entries(["test.com"])

        content = real_hosts.read_text()
        assert "test.com" in content
        assert MARKER_START in content

        remove_entries()
        content = real_hosts.read_text()
        assert "test.com" not in content
        assert "localhost" in content
