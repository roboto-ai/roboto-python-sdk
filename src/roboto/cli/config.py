# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import logging
import os
import pathlib
import sys
from typing import Optional

from packaging.version import InvalidVersion, Version
import pydantic

from ..http import HttpClient
from ..logging import LOGGER_NAME
from ..time import utcnow
from ..version import __version__
from .terminal import AnsiColor

logger = logging.getLogger(LOGGER_NAME)


GITHUB_RELEASES_URL = "https://api.github.com/repos/roboto-ai/roboto-python-sdk/releases/latest"


class CLIState(pydantic.BaseModel):
    last_checked_version: Optional[datetime.datetime] = None
    last_version: str = "0.0.0"
    out_of_date: bool = True


def _get_latest_version_from_github() -> Optional[str]:
    """
    Fetch the latest release version from GitHub Releases API.

    Returns:
        The latest version string (without 'v' prefix), or None if the request fails.
    """
    http = HttpClient()

    try:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": f"roboto-cli/{__version__} (+https://github.com/roboto-ai)",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        response = http.get(GITHUB_RELEASES_URL, headers=headers)
        release_data = response.to_dict()

        tag_name = release_data.get("tag_name")
        if not tag_name:
            logger.debug("GitHub release response missing 'tag_name' field")
            return None

        version = tag_name.lstrip("v")

        return version
    except Exception as exc:
        # Version checking should never block CLI usage
        logger.debug("Failed to fetch latest version from GitHub: %s", exc)
        return None


def is_version_outdated(current: str, latest: str) -> bool:
    """
    Check if the current version is older than the latest version.

    Args:
        current: The current version string (e.g., "1.0.0").
        latest: The latest available version string (e.g., "1.1.0").

    Returns:
        True if current version is older than latest, False otherwise.
        Returns False if either version string is invalid.
    """
    try:
        return Version(current) < Version(latest)
    except InvalidVersion:
        logger.debug("Invalid version format: current=%s, latest=%s", current, latest)
        return False


def check_last_update():
    roboto_tmp_dir = pathlib.Path.home() / ".roboto" / "tmp"
    roboto_tmp_dir.mkdir(parents=True, exist_ok=True)
    cli_state_file = roboto_tmp_dir / "cli_state.json"

    last_version = None

    state = CLIState(last_checked_version=None)
    if cli_state_file.is_file():
        state = CLIState.model_validate_json(cli_state_file.read_text())
        last_version = state.last_version

    if (
        state.last_checked_version is None
        or __version__ != last_version
        or state.out_of_date is None
        or state.out_of_date is True
        or (utcnow() - datetime.timedelta(hours=1)) > state.last_checked_version
    ):
        latest = _get_latest_version_from_github()
        if latest is None:
            return

        state.last_checked_version = utcnow()
        state.last_version = __version__
        state.out_of_date = is_version_outdated(__version__, latest)

        cli_state_file.write_text(state.model_dump_json())

        suppress_message = os.getenv("ROBOTO_CLI_SUPPRESS_UPGRADE_PROMPT", "false").lower() != "false"

        if state.out_of_date and not suppress_message:
            notice = f"{AnsiColor.BLUE}[notice]{AnsiColor.END}"
            print(
                f"\n{notice} A new release of roboto is available: "
                + f"{AnsiColor.RED + __version__ + AnsiColor.END} -> {AnsiColor.GREEN + latest + AnsiColor.END}\n"
                + f"{notice} To update, follow Upgrade CLI instructions at "
                + "https://github.com/roboto-ai/roboto-python-sdk/blob/main/README.md",
                file=sys.stderr,
            )
