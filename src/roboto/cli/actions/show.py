# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import json

from ...domain import actions
from ..command import RobotoCommand
from ..common_args import (
    add_action_reference_arg,
    add_org_arg,
)
from ..context import CLIContext


def show(
    args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser
) -> None:
    owner_org_id = args.action.owner if args.action.owner else args.org
    action = actions.Action.from_name(
        name=args.action.name,
        digest=args.action.digest,
        owner_org_id=owner_org_id,
        roboto_client=context.roboto_client,
    )
    print(json.dumps(action.to_dict(), indent=2))


def show_parser(parser: argparse.ArgumentParser):
    add_action_reference_arg(parser)
    add_org_arg(parser=parser)


show_command = RobotoCommand(
    name="show",
    logic=show,
    setup_parser=show_parser,
    command_kwargs={"help": "Show details for an action."},
)
