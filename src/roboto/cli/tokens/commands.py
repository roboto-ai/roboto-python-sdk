# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import json

from ...domain.tokens import Token
from ..command import (
    RobotoCommand,
    RobotoCommandSet,
)
from ..context import CLIContext


def create(args, context: CLIContext, parser: argparse.ArgumentParser):
    token, secret = Token.create(
        expiry_days=args.expiry_days,
        name=args.name,
        description=args.description,
        roboto_client=context.roboto_client,
    )

    creds_example_json = json.dumps(
        {"username": "<your email>", "token": secret}, indent=2
    )

    print(
        "This secret will only be available to you once, so store it somewhere safe!\n"
        + "To use this personal access token, create a file at ~/.roboto/config.json, and populate it with "
        + f"{creds_example_json}."
    )


def create_setup_parser(parser):
    parser.add_argument(
        "--name",
        type=str,
        required=True,
        help="A human readable name for this token.",
    )

    parser.add_argument(
        "--description",
        type=str,
        help="An optional description for this token.",
    )

    parser.add_argument(
        "--expiry-days",
        type=int,
        choices=[30, 60, 90],
        default=30,
        help="The number of days this token will be valid for.",
    )


def list(args, context: CLIContext, parser: argparse.ArgumentParser):
    tokens = Token.for_self(roboto_client=context.roboto_client)
    for token in tokens:
        print(json.dumps(token.to_dict(), indent=2))


def show(args, context: CLIContext, parser: argparse.ArgumentParser):
    token = Token.from_id(token_id=args.id, roboto_client=context.roboto_client)
    print(json.dumps(token.to_dict(), indent=2))


def show_setup_parser(parser):
    parser.add_argument(
        "--id",
        type=str,
        required=True,
        help="The token_id for a token to look up.",
    )


def delete(args, context: CLIContext, parser: argparse.ArgumentParser):
    Token.from_id(token_id=args.id, roboto_client=context.roboto_client).delete()
    print(f"Successfully deleted token '{args.id}'!")


def delete_setup_parser(parser):
    parser.add_argument(
        "--id",
        type=str,
        required=True,
        help="The token_id for a token to delete.",
    )


create_command = RobotoCommand(
    name="create",
    logic=create,
    setup_parser=create_setup_parser,
    command_kwargs={"help": "Creates a temporary access token."},
)


list_command = RobotoCommand(
    name="list",
    logic=list,
    command_kwargs={"help": "Creates a temporary access token."},
)

show_command = RobotoCommand(
    name="show",
    logic=show,
    setup_parser=show_setup_parser,
    command_kwargs={"help": "Gets a token by unique token_id."},
)

delete_command = RobotoCommand(
    name="delete",
    logic=delete,
    setup_parser=delete_setup_parser,
    command_kwargs={"help": "Deletes a token by unique token_id."},
)

commands = [
    create_command,
    delete_command,
    list_command,
    show_command,
]

command_set = RobotoCommandSet(
    name="tokens",
    help="Generate and review your platform access tokens.",
    commands=commands,
)
