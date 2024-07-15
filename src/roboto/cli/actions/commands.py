# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from ..command import RobotoCommandSet
from .create import create_command
from .delete import delete_command
from .init import init_command
from .invoke import invoke_command
from .list_invocations import (
    list_invocations_command,
)
from .search import search_command
from .show import show_command
from .update import update_command

commands = [
    create_command,
    delete_command,
    update_command,
    search_command,
    show_command,
    invoke_command,
    list_invocations_command,
    init_command,
]

command_set = RobotoCommandSet(
    name="actions",
    help=(
        "Create, edit and invoke reusable actions that run containerized code on your datasets."
    ),
    commands=commands,
)
