"""Tests for scripts/check_release.py."""

import zipfile
from pathlib import Path

import pytest

from scripts.check_release import (
    changelog_has_version,
    package_version,
    parse_tag,
    project_identity,
    wheel_identity,
)


class TestParseTag:
    def test_accepts_calver_tag(self):
        assert parse_tag("v2026.8.2") == "2026.8.2"

    def test_rejects_missing_v_prefix(self):
        with pytest.raises(ValueError, match="tag must be v"):
            parse_tag("2026.8.2")

    def test_rejects_semver_brackets_style(self):
        with pytest.raises(ValueError, match="tag must be v"):
            parse_tag("v1.2.3")


class TestChangelogHasVersion:
    def test_matches_calver_heading(self, tmp_path: Path):
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text("## 2026.8.2 (2026-08-24)\n\n- fix\n")
        assert changelog_has_version(changelog, "2026.8.2") is True

    def test_rejects_semver_heading(self, tmp_path: Path):
        changelog = tmp_path / "CHANGELOG.md"
        changelog.write_text("## [2026.8.2]\n\n- fix\n")
        assert changelog_has_version(changelog, "2026.8.2") is False


class TestProjectIdentity:
    def test_reads_name_and_version(self, tmp_path: Path):
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text(
            '[project]\nname = "lockin-blocker"\nversion = "2026.8.2"\n'
        )
        assert project_identity(pyproject) == ("lockin-blocker", "2026.8.2")


class TestPackageVersion:
    def test_reads_init_version(self, tmp_path: Path):
        init_py = tmp_path / "__init__.py"
        init_py.write_text('__version__ = "2026.8.2"\n')
        assert package_version(init_py) == "2026.8.2"


class TestWheelIdentity:
    def test_reads_wheel_metadata(self, tmp_path: Path):
        dist = tmp_path / "dist"
        dist.mkdir()
        wheel_path = dist / "lockin_blocker-2026.8.2-py3-none-any.whl"
        with zipfile.ZipFile(wheel_path, "w") as archive:
            archive.writestr(
                "lockin_blocker-2026.8.2.dist-info/METADATA",
                "Name: lockin-blocker\nVersion: 2026.8.2\n",
            )
        assert wheel_identity(dist, "lockin-blocker") == (
            "lockin-blocker",
            "2026.8.2",
        )

    def test_rejects_multiple_wheels(self, tmp_path: Path):
        dist = tmp_path / "dist"
        dist.mkdir()
        for name in (
            "lockin_blocker-2026.8.2-py3-none-any.whl",
            "lockin_blocker-2026.8.1-py3-none-any.whl",
        ):
            with zipfile.ZipFile(dist / name, "w") as archive:
                archive.writestr(
                    "lockin_blocker-2026.8.2.dist-info/METADATA",
                    "Name: lockin-blocker\nVersion: 2026.8.2\n",
                )
        with pytest.raises(ValueError, match="exactly one"):
            wheel_identity(dist, "lockin-blocker")
