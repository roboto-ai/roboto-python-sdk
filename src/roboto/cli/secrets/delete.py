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


def delete_logic(args, context: CLIContext, parser: argparse.ArgumentParser):
    org_id = args.org
    secret_name = args.secret_name

    secret = Secret.from_name(
        name=secret_name,
        org_id=org_id,
        roboto_client=context.roboto_client,
    )

    secret.delete()
    print(f"Deleted secret {secret_name}", file=sys.stderr)


def delete_setup_parser(parser):
    add_org_arg(parser)
    parser.add_argument(
        "secret_name",
        help="The name of the secret to delete.",
    )


delete_command = RobotoCommand(
    name="delete",
    logic=delete_logic,
    setup_parser=delete_setup_parser,
    command_kwargs={"help": "Deletes a secret from the Roboto platform. This operation cannot be undone."},
)
