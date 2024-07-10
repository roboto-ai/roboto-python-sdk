# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse

from ...domain import actions
from ..command import RobotoCommand
from ..context import CLIContext


def show(
    args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser
) -> None:
    invocation = actions.Invocation.from_id(
        args.invocation_id,
        roboto_client=context.roboto_client,
    )
    print(str(invocation))
    return


def show_parser(parser: argparse.ArgumentParser):
    parser.add_argument("invocation_id")


show_command = RobotoCommand(
    name="show",
    logic=show,
    setup_parser=show_parser,
    command_kwargs={"help": "Show invocation details."},
)
