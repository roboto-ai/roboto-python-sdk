# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
from typing import Any, Callable, Optional

from ...exceptions import (
    RobotoDomainException,
    RobotoNoOrgProvidedException,
)
from ..argparse import SortingHelpFormatter
from ..context import CLIContext
from ..terminal import print_error_and_exit


class RobotoCommand(object):
    """Subcommand of a command set, such as ``list`` in ``roboto datasets list``.

    Args:
        name: Subcommand name, as typed after the command set's name.
        logic: Function that runs the command, called with the parsed arguments, the CLI context, and the
            subcommand's parser.
        command_kwargs: Further keyword arguments for the subcommand's parser, such as ``help`` and ``description``.
            ``None`` passes none.
        setup_parser: Function that adds the subcommand's own arguments to its parser. ``None`` adds none.
        requires_config: Whether the CLI loads the Roboto config and builds an authenticated client before running
            the command. When ``False``, the context passed to ``logic`` has neither, so commands that must work
            before any config exists, such as ``roboto auth login``, set it to ``False``.
    """

    _name: str
    _logic: Callable[[Any, CLIContext, argparse.ArgumentParser], None]
    _inner_setup_parser: Optional[Callable[[Any], None]]
    _command_kwargs: Optional[dict[str, Any]]
    _requires_config: bool

    def __init__(
        self,
        name: str,
        logic: Callable[[Any, CLIContext, argparse.ArgumentParser], None],
        command_kwargs: Optional[dict],
        setup_parser: Optional[Callable[[Any], None]] = None,
        requires_config: bool = True,
    ):
        self._name = name
        self._logic = logic
        self._inner_setup_parser = setup_parser
        self._command_kwargs = command_kwargs
        self._requires_config = requires_config

    @property
    def name(self):
        return self._name

    @property
    def command_kwargs(self):
        if self._command_kwargs is not None:
            return self._command_kwargs
        return {}

    def setup_parser(self, parser: argparse.ArgumentParser, context: Optional[CLIContext]):
        """Make ``parser`` run this command when the user chooses it, then add the command's own arguments.

        When the command runs, Roboto exceptions it raises become error messages:

        - ``RobotoNoOrgProvidedException`` prints a usage error asking for ``--org`` or ``ROBOTO_ORG_ID`` and exits
          with status 2.
        - Any other ``RobotoDomainException`` prints its class name and message and exits with status 1.

        Any other exception propagates.

        Args:
            parser: Parser of this subcommand.
            context: Context the command runs with. The CLI fills it in after parsing the command line, unless the
                command sets ``requires_config`` to ``False``.

        Raises:
            ValueError: ``context`` is ``None``. Raised when the command runs.
        """

        def context_aware_logic(args):
            if not context:
                raise ValueError(
                    "CLIContext is not set. "
                    "This is a programming error, and should be fixed by the Roboto development team."
                )
            try:
                return self._logic(args, context, parser)
            except RobotoNoOrgProvidedException:
                parser.error(
                    "User in multiple orgs must provide --org, or "
                    + "set an environment variable called 'ROBOTO_ORG_ID'."
                )
            except RobotoDomainException as exc:
                print_error_and_exit(f"{exc.__class__.__name__}: {exc}")

        parser.set_defaults(func=context_aware_logic, requires_config=self._requires_config)
        if self._inner_setup_parser is not None:
            self._inner_setup_parser(parser)


class RobotoCommandSet(object):
    """Named group of subcommands, such as ``roboto datasets``.

    Args:
        help: Help text for the command set, shown in ``roboto --help``.
    """

    commands: list[RobotoCommand]
    """Subcommands in the set."""

    name: str
    """Name the user types after ``roboto`` to reach the set's subcommands."""

    __help: str
    __context: Optional[CLIContext]

    def __init__(self, name, help, commands):
        self.name = name
        self.__help = help
        self.commands = commands

    def add_to_subparsers(
        self,
        parent_subparsers: Any,
        context: Optional[CLIContext],
    ) -> None:
        """Add this command set to ``parent_subparsers``, with one subcommand per command.

        Running the command set without a subcommand is a usage error.

        Args:
            parent_subparsers: Subparsers of the ``roboto`` parser, as ``add_subparsers`` returns them.
            context: Context each command runs with. Passed to ``RobotoCommand.setup_parser``.
        """
        self.__context = context

        command_set_parser = parent_subparsers.add_parser(self.name, help=self.__help)
        subparsers = command_set_parser.add_subparsers()
        subparsers.required = True

        for command in self.commands:
            command_parser = subparsers.add_parser(
                command.name,
                formatter_class=SortingHelpFormatter,
                **command.command_kwargs,
            )
            command.setup_parser(command_parser, context)

    def sort_commands(self):
        """Sort ``commands`` by name, in place, so that the command set's help lists them alphabetically."""
        self.commands.sort(key=lambda command: command.name)
