# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse

from roboto.cli.command import RobotoCommand
from roboto.cli.common_args import add_org_arg
from roboto.cli.context import CLIContext
from roboto.domain.secrets import Secret


def read_logic(args, context: CLIContext, parser: argparse.ArgumentParser):
    org_id = args.org
    secret_name = args.secret_name

    secret = Secret.from_name(
        name=secret_name,
        org_id=org_id,
        roboto_client=context.roboto_client,
    )

    print(secret.read_value().get_secret_value())


def read_setup_parser(parser):
    add_org_arg(parser)
    parser.add_argument(
        "secret_name",
        help="The name of the secret to read.",
    )


read_command = RobotoCommand(
    name="read",
    logic=read_logic,
    setup_parser=read_setup_parser,
    command_kwargs={"help": "Retrieve a secret's value from secure storage, and reveal it to the user."},
)
