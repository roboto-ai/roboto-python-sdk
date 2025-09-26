# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from ..command import RobotoCommandSet
from .delete import delete_command
from .list import list_command
from .read import read_command
from .write import write_command

command_set = RobotoCommandSet(
    name="secrets",
    help="Manage secure secrets registered with Roboto. These are typically 3rd party API keys to power integrations.",
    commands=[delete_command, read_command, write_command, list_command],
)
