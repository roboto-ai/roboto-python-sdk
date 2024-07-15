# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse

from ...domain import actions
from ..command import RobotoCommand
from ..context import CLIContext


def cancel(
    args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser
) -> None:
    invocation = actions.Invocation.from_id(
        args.invocation_id,
        roboto_client=context.roboto_client,
    )
    invocation.cancel()
    print("Invocation cancelled.")
    return


def cancel_parser(parser: argparse.ArgumentParser):
    parser.add_argument("invocation_id")


cancel_command = RobotoCommand(
    name="cancel",
    logic=cancel,
    setup_parser=cancel_parser,
    command_kwargs={"help": "Cancel invocation."},
)
