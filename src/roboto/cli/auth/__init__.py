# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The ``roboto auth`` command group, which signs in to Roboto.

Its one command, ``roboto auth login``, signs in through a browser and saves a new access token to a profile in the
Roboto config file. ``command_set`` holds the group, and ``roboto.cli.entry`` adds it to the ``roboto`` program.
"""

from .commands import command_set

__all__ = ["command_set"]
