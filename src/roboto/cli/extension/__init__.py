# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""Extension point of the ``roboto`` command-line program, which adds command groups, commands, and shared state to it.

Subclass ``RobotoCLIExtension`` to declare new command groups, commands to add to existing groups, and a context that
commands read from ``roboto.cli.context.CLIContext.extensions`` under the extension's name. The ``roboto`` program
applies every direct subclass defined by the time it starts, through ``apply_roboto_cli_command_extensions`` and
``apply_roboto_cli_context_extensions``. A command group name that is already taken, or a command for a group nothing
defines, raises ``ValueError``.
"""

from .cli_extension import (
    RobotoCLIExtension,
    apply_roboto_cli_command_extensions,
    apply_roboto_cli_context_extensions,
)

__all__ = [
    "RobotoCLIExtension",
    "apply_roboto_cli_command_extensions",
    "apply_roboto_cli_context_extensions",
]
