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
    """Base class of a CLI extension, which adds command sets, commands, and a context of its own to the ``roboto`` CLI.

    Roboto subclasses it to add commands to the CLI. Every direct subclass defined by the time the CLI starts is
    applied; a subclass of a subclass is not.
    """

    @classmethod
    @abc.abstractmethod
    def get_name(cls) -> str:
        """Return the extension's name, the key of its context in ``roboto.cli.context.CLIContext.extensions``.

        An extension that shares a name with another replaces that extension's context.
        """
        raise NotImplementedError("get_name")

    @classmethod
    @abc.abstractmethod
    def get_command_sets(self) -> list[RobotoCommandSet]:
        """Return the command sets the extension adds, each named differently from every other command set."""
        raise NotImplementedError("get_command_sets")

    @classmethod
    @abc.abstractmethod
    def get_commands(cls) -> list[tuple[str, RobotoCommand]]:
        """Return the commands the extension adds to existing command sets.

        Returns:
            ``(command_set_name, command)`` pairs: the name of the command set to add the command to, which the CLI or
            any extension defines, and the command.
        """
        raise NotImplementedError("get_commands_extensions")

    @classmethod
    @abc.abstractmethod
    def get_context(cls, base_context: CLIContext) -> Any:
        """Build the extension's context, which its commands read from ``roboto.cli.context.CLIContext.extensions``.

        Called only before a command that needs a configuration runs.

        Args:
            base_context: Context of the CLI, with its configuration and client loaded.

        Returns:
            Context stored in ``base_context.extensions`` under the extension's name.
        """
        raise NotImplementedError("get_context")


def apply_roboto_cli_command_extensions(
    base_command_sets: list[RobotoCommandSet],
) -> list[RobotoCommandSet]:
    """Return the CLI's command sets with every extension's command sets and commands added.

    The ``roboto`` CLI calls this when it builds its argument parser. Every extension's command sets are added before
    any extension's commands, so a command can join a command set that another extension adds.

    Args:
        base_command_sets: Command sets the CLI itself defines. Commands extensions add to them are appended to their
            ``commands`` lists in place.

    Returns:
        The base command sets, followed by each extension's command sets.

    Raises:
        ValueError: An extension adds a command set whose name is already taken, or adds a command to a command set
            that does not exist.
    """
    command_sets_by_name: dict[str, RobotoCommandSet] = {}
    for command_set in base_command_sets:
        command_sets_by_name[command_set.name] = command_set

    for subclass in RobotoCLIExtension.__subclasses__():
        for command_set in subclass.get_command_sets():
            if command_set.name in command_sets_by_name.keys():
                raise ValueError(f"Attempting to add already defined command set '{command_set.name}'")
            command_sets_by_name[command_set.name] = command_set

    for subclass in RobotoCLIExtension.__subclasses__():
        for command_set_name, command in subclass.get_commands():
            if command_set_name not in command_sets_by_name.keys():
                raise ValueError(
                    f"Attempting to add command '{command.name}' to non-existant " + "command set '{command_set_name}'"
                )

            command_sets_by_name[command_set_name].commands.append(command)

    return list(map(lambda item: item[1], command_sets_by_name.items()))


def apply_roboto_cli_context_extensions(base_context: CLIContext):
    """Store each extension's context in ``base_context.extensions``, under the extension's name.

    The ``roboto`` CLI calls this after it loads the configuration, before it runs a command that needs one.

    Args:
        base_context: Context of the CLI, with its configuration and client loaded.
    """
    for subclass in RobotoCLIExtension.__subclasses__():
        base_context.extensions[subclass.get_name()] = subclass.get_context(base_context)
