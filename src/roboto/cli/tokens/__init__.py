# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The ``roboto tokens`` command group, which creates, lists, shows, and deletes your personal access tokens.

A personal access token is a credential that authenticates requests to Roboto as the user who owns it.
``roboto tokens create`` makes one valid for 30, 60, or 90 days and prints its secret, which Roboto shows only that
once; ``roboto tokens list`` and ``roboto tokens show`` print tokens' records as JSON, without their secrets.
``command_set`` holds the group, and ``roboto.cli.entry`` adds it to the ``roboto`` program.
"""

from .commands import command_set

__all__ = ["command_set"]
