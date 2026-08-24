#!/usr/bin/env python3
"""Validate tag, project metadata, changelog, and exact wheel metadata."""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_CALVER_TAG = re.compile(r"^v(?P<version>\d{4}\.\d+\.\d+)$")


def parse_tag(tag: str) -> str:
    """Return the CalVer version from a release tag."""
    match = _CALVER_TAG.fullmatch(tag)
    if match is None:
        raise ValueError("tag must be vYYYY.M.PATCH")
    return match.group("version")


def project_identity(pyproject: Path) -> tuple[str, str]:
    """Read the distribution name and version from project metadata."""
    project = tomllib.loads(pyproject.read_text())["project"]
    return str(project["name"]), str(project["version"])


def package_version(package_init: Path) -> str:
    """Read __version__ from the package __init__.py."""
    match = re.search(
        r'^__version__\s*=\s*["\'](?P<version>[^"\']+)',
        package_init.read_text(),
        re.MULTILINE,
    )
    if match is None:
        raise ValueError(f"{package_init} has no __version__ declaration")
    return match.group("version")


def changelog_has_version(changelog: Path, version: str) -> bool:
    """Return whether the changelog has an exact CalVer heading."""
    return (
        re.search(
            rf"(?m)^## {re.escape(version)}(?:\s|$)",
            changelog.read_text(),
        )
        is not None
    )


def wheel_identity(dist: Path, project_name: str) -> tuple[str, str]:
    """Read name and version from the project's built wheel metadata."""
    wheel_prefix = project_name.replace("-", "_")
    wheels = sorted(dist.glob(f"{wheel_prefix}-*.whl"))
    if len(wheels) != 1:
        raise ValueError(f"expected exactly one {wheel_prefix}-*.whl in {dist}")
    with zipfile.ZipFile(wheels[0]) as archive:
        metadata_name = next(
            (
                name
                for name in archive.namelist()
                if name.endswith(".dist-info/METADATA")
            ),
            None,
        )
        if metadata_name is None:
            raise ValueError(f"{wheels[0].name} has no dist-info/METADATA")
        metadata = archive.read(metadata_name).decode()
        name = re.search(r"(?m)^Name:\s*(.+)$", metadata)
        version = re.search(r"(?m)^Version:\s*(.+)$", metadata)
        if name is None or version is None:
            raise ValueError("wheel metadata is missing Name or Version")
        return name.group(1).strip(), version.group(1).strip()


def main(argv: list[str] | None = None) -> int:
    """Run release consistency checks."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    parser.add_argument("--pyproject", type=Path, default=ROOT / "pyproject.toml")
    parser.add_argument("--changelog", type=Path, default=ROOT / "CHANGELOG.md")
    parser.add_argument(
        "--package-init",
        type=Path,
        default=ROOT / "lockin" / "__init__.py",
    )
    args = parser.parse_args(argv)

    try:
        expected = parse_tag(args.tag)
    except ValueError as error:
        print(f"check_release: {error}", file=sys.stderr)
        return 1

    project_name, project_version = project_identity(args.pyproject)
    try:
        wheel_name, wheel_version = wheel_identity(args.dist, project_name)
        init_version = package_version(args.package_init)
    except ValueError as error:
        print(f"check_release: {error}", file=sys.stderr)
        return 1

    checks = (
        (
            project_version == expected,
            f"project version {project_version} != tag {expected}",
        ),
        (
            wheel_name == project_name,
            f"wheel name {wheel_name} != project {project_name}",
        ),
        (
            wheel_version == expected,
            f"wheel version {wheel_version} != tag {expected}",
        ),
        (
            init_version == expected,
            f"package version {init_version} != tag {expected}",
        ),
        (
            changelog_has_version(args.changelog, expected),
            f"CHANGELOG.md has no ## {expected} section",
        ),
    )
    failures = [message for passed, message in checks if not passed]
    if failures:
        print("check_release: " + "; ".join(failures), file=sys.stderr)
        return 1
    print(f"check_release: OK {project_name} {expected}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
