# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import abc
from typing import Any

from ..command import (
    RobotoCommand,
    RobotoCommandSet,
)
from ..context import CLIContext


class RobotoCLIExtension(abc.ABC):
    @classmethod
    @abc.abstractmethod
    def get_name(cls) -> str:
        raise NotImplementedError("get_name")

    @classmethod
    @abc.abstractmethod
    def get_command_sets(self) -> list[RobotoCommandSet]:
        raise NotImplementedError("get_command_sets")

    @classmethod
    @abc.abstractmethod
    def get_commands(cls) -> list[tuple[str, RobotoCommand]]:
        raise NotImplementedError("get_commands_extensions")

    @classmethod
    @abc.abstractmethod
    def get_context(cls, base_context: CLIContext) -> Any:
        raise NotImplementedError("get_context")


def apply_roboto_cli_command_extensions(
    base_command_sets: list[RobotoCommandSet],
) -> list[RobotoCommandSet]:
    command_sets_by_name: dict[str, RobotoCommandSet] = {}
    for command_set in base_command_sets:
        command_sets_by_name[command_set.name] = command_set

    for subclass in RobotoCLIExtension.__subclasses__():
        for command_set in subclass.get_command_sets():
            if command_set.name in command_sets_by_name.keys():
                raise ValueError(
                    f"Attempting to add already defined command set '{command_set.name}'"
                )
            command_sets_by_name[command_set.name] = command_set

    # Run this as a 2nd for loop, so we can define all command sets before we attempt to extend them.
    for subclass in RobotoCLIExtension.__subclasses__():
        for command_set_name, command in subclass.get_commands():
            if command_set_name not in command_sets_by_name.keys():
                raise ValueError(
                    f"Attempting to add command '{command.name}' to non-existant "
                    + "command set '{command_set_name}'"
                )

            command_sets_by_name[command_set_name].commands.append(command)

    return list(map(lambda item: item[1], command_sets_by_name.items()))


def apply_roboto_cli_context_extensions(base_context: CLIContext):
    for subclass in RobotoCLIExtension.__subclasses__():
        base_context.extensions[subclass.get_name()] = subclass.get_context(
            base_context
        )
