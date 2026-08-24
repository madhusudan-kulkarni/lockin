#!/usr/bin/env python3
"""Verify that an exact project version is visible on PyPI."""

from __future__ import annotations

import argparse
import http.client
import json
import sys
import time
import urllib.request
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import BinaryIO, cast

OpenUrl = Callable[[str], AbstractContextManager[BinaryIO]]


def open_pypi_url(url: str) -> AbstractContextManager[BinaryIO]:
    """Open a PyPI JSON endpoint with a bounded timeout."""
    return cast(
        AbstractContextManager[BinaryIO],
        urllib.request.urlopen(url, timeout=15),
    )


def verify_pypi_release(
    project: str,
    version: str,
    *,
    attempts: int = 12,
    delay_seconds: float = 10,
    opener: OpenUrl = open_pypi_url,
    sleeper: Callable[[float], None] = time.sleep,
) -> None:
    """Wait for PyPI to expose an exact project version."""
    url = f"https://pypi.org/pypi/{project}/{version}/json"
    last_issue = "release was not visible"
    for attempt in range(attempts):
        try:
            with opener(url) as response:
                published = json.load(response)["info"]["version"]
            if published == version:
                return
            last_issue = f"PyPI reported version {published!r}"
        except (
            OSError,
            ValueError,
            KeyError,
            TypeError,
            UnicodeDecodeError,
            http.client.IncompleteRead,
        ) as error:
            last_issue = f"{type(error).__name__}: {error}"
        if attempt + 1 < attempts:
            sleeper(delay_seconds)
    raise RuntimeError(f"PyPI did not expose {project} {version}: {last_issue}")


def main(argv: list[str] | None = None) -> int:
    """Run the PyPI release verification."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project")
    parser.add_argument("version")
    args = parser.parse_args(argv)
    try:
        verify_pypi_release(args.project, args.version)
    except RuntimeError as error:
        print(f"verify_pypi_release: {error}", file=sys.stderr)
        return 1
    print(f"verify_pypi_release: OK {args.project} {args.version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
