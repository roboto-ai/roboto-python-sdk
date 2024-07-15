# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from ..command import RobotoCommandSet
from .cancel import cancel_command
from .logs import get_logs_command
from .show import show_command
from .status import status_command

commands = [
    cancel_command,
    get_logs_command,
    show_command,
    status_command,
]

command_set = RobotoCommandSet(
    name="invocations",
    help=(
        "Get logs and status history from invoked actions, including the option to cancel them."
    ),
    commands=commands,
)
