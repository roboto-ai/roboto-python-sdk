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
    _name: str
    _logic: Callable[
        [Any, CLIContext, argparse.ArgumentParser], None
    ]  # Args, CLIContext
    _inner_setup_parser: Optional[Callable[[Any], None]]  # Parser
    _command_kwargs: Optional[dict[str, Any]]

    def __init__(
        self,
        name: str,
        logic: Callable[[Any, CLIContext, argparse.ArgumentParser], None],
        command_kwargs: Optional[dict],
        setup_parser: Optional[Callable[[Any], None]] = None,
    ):
        self._name = name
        self._logic = logic
        self._inner_setup_parser = setup_parser
        self._command_kwargs = command_kwargs

    @property
    def name(self):
        return self._name

    @property
    def command_kwargs(self):
        if self._command_kwargs is not None:
            return self._command_kwargs
        return {}

    def setup_parser(
        self, parser: argparse.ArgumentParser, context: Optional[CLIContext]
    ):
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
                    "User with 0 or 2+ orgs must explicitly provide --org to org-bound operations. "
                    + "This can also be achieved by setting a 'ROBOTO_ORG_ID' environment variable, "
                    + "whose value will be used by default."
                )
            except RobotoDomainException as exc:
                print_error_and_exit(f"{exc.__class__.__name__}: {exc}")

        parser.set_defaults(func=context_aware_logic)
        if self._inner_setup_parser is not None:
            self._inner_setup_parser(parser)


class RobotoCommandSet(object):
    commands: list[RobotoCommand]
    name: str

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
        self.commands.sort(key=lambda command: command.name)
