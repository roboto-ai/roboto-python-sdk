# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The ``roboto invocations`` command group, which shows, follows, and cancels invocations of actions.

An invocation is one run of an action. ``roboto invocations status`` prints an invocation's status history, and with
``--tail`` keeps printing new statuses until the invocation finishes. ``roboto invocations logs`` prints the lines an
invocation's containers wrote to STDOUT and STDERR, and with ``--tail`` keeps printing new ones until the invocation
finishes. ``roboto invocations cancel-all`` cancels every queued invocation in the ``--org`` organization, and every
scheduled or running one created before the command started. ``command_set`` holds the group, and
``roboto.cli.entry`` adds it to the ``roboto`` program.
"""

from ..command import RobotoCommandSet
from .cancel import cancel_command
from .cancel_all import cancel_all_command
from .logs import get_logs_command
from .show import show_command
from .status import status_command

commands = [
    cancel_command,
    cancel_all_command,
    get_logs_command,
    show_command,
    status_command,
]

command_set = RobotoCommandSet(
    name="invocations",
    help=("Get logs and status history from invoked actions, including the option to cancel them."),
    commands=commands,
)
