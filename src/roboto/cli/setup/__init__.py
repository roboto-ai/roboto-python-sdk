# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The ``roboto setup`` command, which sets up a machine to use Roboto from the command line, the SDK, and AI tools.

It checks the access token and offers to sign in through a browser, asks which organization to use by default when the
user belongs to several and has no default, and, for the AI tools the user chooses among Claude Code, Codex, Cursor,
and VS Code, installs Roboto's agent skills and adds the Roboto MCP server. Running it again updates the agent skills
and changes nothing else that is already set up. ``roboto.cli.entry`` adds the command to the ``roboto`` program from
``HELP``, ``DESCRIPTION``, ``setup_parser`` and ``run``, and runs it without the CLI context other commands receive,
since a new user runs it before saving an access token or a config file.
"""

from .command import (
    DESCRIPTION,
    HELP,
    run,
    setup_parser,
)

__all__ = ["DESCRIPTION", "HELP", "run", "setup_parser"]
