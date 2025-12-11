# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from ..command import RobotoCommandSet
from .clear import clear_command
from .size import size_command
from .where import where_command

commands = [
    clear_command,
    size_command,
    where_command,
]

command_set = RobotoCommandSet(
    name="cache",
    help="Manage the local Roboto cache.",
    commands=commands,
)
