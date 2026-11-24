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

USER_AGENT = f"roboto-cli/{__version__} (+https://github.com/roboto-ai)"
"""User agent the CLI sends in its requests to sites other than Roboto, such as GitHub.

Some sites refuse the user agent Python sends by default.
"""


class CLIState(pydantic.BaseModel):
    """Result of the CLI's last check for a newer release, saved in ``~/.roboto/tmp/cli_state.json``."""

    last_checked_version: Optional[datetime.datetime] = None
    """Time of the last check that reached GitHub, or ``None`` if none has."""

    last_version: str = "0.0.0"
    """Version of the CLI that ran the last check."""

    out_of_date: bool = True
    """Whether the last check found a release newer than the CLI version that ran it."""


def get_latest_version() -> Optional[str]:
    """Look up the version of the latest release of the Roboto Python SDK on GitHub.

    Returns:
        The release's tag without its leading ``v``, such as ``"0.44.0"``, or ``None`` if the request fails or the
        response names no tag.
    """
    http = HttpClient()

    try:
        headers = {
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
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
        # Catches every exception, such as a network failure, an error status, or a body that is not a JSON object, so
        # the check after each command never fails the command. `roboto upgrade` reports the None as a failed lookup.
        logger.debug("Failed to fetch latest version from GitHub: %s", exc)
        return None


def is_version_outdated(current: str, latest: str) -> bool:
    """Return whether ``current`` is an older version than ``latest``.

    Versions compare by the rules of ``packaging.version.Version``, so ``"1.10.0"`` is newer than ``"1.9.0"``. When
    either string is not a valid version, the result is ``False``.
    """
    try:
        return Version(current) < Version(latest)
    except InvalidVersion:
        logger.debug("Invalid version format: current=%s, latest=%s", current, latest)
        return False


def check_last_update():
    """Print a notice to standard error when a newer release of the CLI is available.

    The ``roboto`` command calls this after each command, unless ``--suppress-upgrade-check`` is passed. It saves each
    check's result in ``~/.roboto/tmp/cli_state.json`` and looks up the latest release on GitHub only when:

    - no check has been saved,
    - the saved check ran under a different CLI version,
    - the saved check found the CLI out of date, or
    - the saved check is more than an hour old.

    So once a newer release is found, every command looks it up again and prints the notice until the CLI is upgraded.
    When the lookup fails, nothing is saved or printed. Setting ``ROBOTO_CLI_SUPPRESS_UPGRADE_PROMPT`` to any value
    other than ``false``, in any letter case, still runs the check but prints no notice.

    Raises:
        pydantic.ValidationError: ``~/.roboto/tmp/cli_state.json`` does not hold a saved check.
        OSError: ``~/.roboto/tmp`` cannot be created, or the state file cannot be read or written.
    """
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
        latest = get_latest_version()
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
                + f"{notice} To update, run `roboto upgrade`.",
                file=sys.stderr,
            )
