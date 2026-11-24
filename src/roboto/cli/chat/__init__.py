# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The ``roboto chat`` command group, which holds a conversation with Roboto's AI in the terminal.

Its one command, ``roboto chat start``, sends each prompt you type to the AI in one agent thread and prints the AI's
replies as they arrive, until you enter ``quit``, ``exit``, ``q`` or ``e``. ``command_set`` holds the group, and
``roboto.cli.entry`` adds it to the ``roboto`` program.
"""

from ..command import RobotoCommandSet
from .start import start_command

command_set = RobotoCommandSet(
    name="chat",
    help="Talk with your data, using natural language.",
    commands=[start_command],
)
