# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from ..command import RobotoCommandSet
from .changes import changes_command
from .create import create_command
from .delete import delete_command
from .list import list_command
from .show import show_command
from .update import update_command

command_set = RobotoCommandSet(
    name="collections",
    help="Curate collections of datasets and other data types.",
    commands=[
        changes_command,
        create_command,
        delete_command,
        list_command,
        show_command,
        update_command,
    ],
)
