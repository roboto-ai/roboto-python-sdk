# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The ``roboto upgrade`` command, which upgrades the Roboto CLI and the agent skills ``roboto setup`` installed.

It upgrades the CLI the way it was installed: it replaces a release binary in place after checking the download, and
upgrades a Homebrew install with Homebrew; for a ``.deb`` package or the Python package, it prints the command that
upgrades it. It then updates the agent skills ``roboto setup`` installed and removes any Roboto no longer publishes.
Set ``ROBOTO_DOWNLOAD_URL`` to download the CLI's release files from a mirror. ``roboto.cli.entry`` adds the command
to the ``roboto`` program from ``HELP``, ``DESCRIPTION``, ``setup_parser`` and ``run``, and runs it without the CLI
context other commands receive, so it works whatever state the access token and config file are in.
"""

from .command import (
    DESCRIPTION,
    HELP,
    run,
    setup_parser,
)

__all__ = ["DESCRIPTION", "HELP", "run", "setup_parser"]
