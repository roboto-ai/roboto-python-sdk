# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import sys

from roboto.cli.command import RobotoCommand
from roboto.cli.common_args import add_org_arg
from roboto.cli.context import CLIContext
from roboto.domain.secrets import Secret
from roboto.exceptions import (
    RobotoNotFoundException,
)


def write_logic(args, context: CLIContext, parser: argparse.ArgumentParser):
    org_id = args.org
    secret_name = args.secret_name

    try:
        secret = Secret.from_name(
            name=secret_name,
            org_id=org_id,
            roboto_client=context.roboto_client,
        )
    except RobotoNotFoundException:
        secret = Secret.create(
            name=secret_name,
            caller_org_id=org_id,
            roboto_client=context.roboto_client,
        )

    secret.update_value(args.secret_value)
    print(f"Wrote new value to {secret_name}", file=sys.stderr)


def write_setup_parser(parser):
    add_org_arg(parser)
    parser.add_argument(
        "secret_name",
        help="The name of the secret to write.",
    )
    parser.add_argument(
        "secret_value",
        help="The value to write to the secret.",
    )


write_command = RobotoCommand(
    name="write",
    logic=write_logic,
    setup_parser=write_setup_parser,
    command_kwargs={"help": "Write a new value to a new or existing secret."},
)
