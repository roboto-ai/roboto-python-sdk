# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import importlib.metadata
import os
import pathlib
import sys
from typing import Optional

from packaging.version import Version
import pydantic

from roboto.http import HttpClient
from roboto.time import utcnow

from .terminal import AnsiColor


class CLIState(pydantic.BaseModel):
    last_checked_version: Optional[datetime.datetime] = None
    last_version: str = "0.0.0"
    out_of_date: bool = True


def check_last_update():
    roboto_tmp_dir = pathlib.Path.home() / ".roboto" / "tmp"
    roboto_tmp_dir.mkdir(parents=True, exist_ok=True)
    cli_state_file = roboto_tmp_dir / "cli_state.json"

    last_version = None
    try:
        version = importlib.metadata.version("roboto")
    except importlib.metadata.PackageNotFoundError:
        version = "0.0.0"

    state = CLIState(last_checked_version=None)
    if cli_state_file.is_file():
        state = CLIState.parse_file(cli_state_file)
        last_version = state.last_version

    if (
        state.last_checked_version is None
        or version != last_version
        or state.out_of_date is None
        or state.out_of_date is True
        or (utcnow() - datetime.timedelta(hours=1)) > state.last_checked_version
    ):
        http = HttpClient()

        releases = http.get(url="https://pypi.org/pypi/roboto/json").to_dict(
            json_path=["releases"]
        )
        versions = list(releases.keys())
        versions.sort(key=Version)
        latest = versions[-1]

        state.last_checked_version = utcnow()
        state.last_version = version
        state.out_of_date = version != latest

        cli_state_file.write_text(state.json())

        suppress_message = (
            os.getenv("ROBOTO_CLI_SUPPRESS_UPGRADE_PROMPT", "false").lower() != "false"
        )

        if state.out_of_date and not suppress_message:
            notice = f"{AnsiColor.BLUE}[notice]{AnsiColor.END}"
            print(
                f"\n{notice} A new release of roboto is available: "
                + f"{AnsiColor.RED + version + AnsiColor.END} -> {AnsiColor.GREEN + latest + AnsiColor.END}\n"
                + f"{notice} To update, run: {AnsiColor.GREEN}pip install --upgrade roboto{AnsiColor.END}",
                file=sys.stderr,
            )
