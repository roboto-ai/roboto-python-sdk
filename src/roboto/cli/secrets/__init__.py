# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The ``roboto secrets`` command group, which writes, lists, and deletes an organization's secrets.

A secret is sensitive information, such as an API key or password, that actions can use while they run.
``roboto secrets write`` sets a secret's value, creating the secret when the organization has none with that name.
``roboto secrets list`` prints each secret's record as JSON, without its value, and ``roboto secrets delete`` deletes
a secret and its value, which cannot be restored. ``command_set`` holds the group, and ``roboto.cli.entry`` adds it to
the ``roboto`` program.
"""

from ..command import RobotoCommandSet
from .delete import delete_command
from .list import list_command
from .write import write_command

command_set = RobotoCommandSet(
    name="secrets",
    help="Manage secure secrets registered with Roboto. These are typically 3rd party API keys to power integrations.",
    commands=[delete_command, list_command, write_command],
)
