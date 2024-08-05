# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import json

from ...domain.orgs import Org
from ...domain.users import User
from ...exceptions import RobotoHttpExceptionParse
from ..command import (
    RobotoCommand,
    RobotoCommandSet,
)
from ..context import CLIContext


def show(args, context: CLIContext, parser: argparse.ArgumentParser):
    if not args.id:
        user = User.for_self(roboto_client=context.roboto_client)
    else:
        user = User.from_id(user_id=args.id, roboto_client=context.roboto_client)
    print(json.dumps(user.to_dict(), indent=2))


def show_setup_parser(parser):
    parser.add_argument(
        "--id",
        type=str,
        help=argparse.SUPPRESS,
    )


def delete(args, context: CLIContext, parser: argparse.ArgumentParser):
    if not args.ignore_prompt:
        print("Are you absolutely sure you want to delete your user? [y/n]:", end=" ")
        choice = input().lower()
        if choice not in ["y", "yes"]:
            return

    user = User.from_id(user_id=args.id, roboto_client=context.roboto_client)
    user.delete()
    print(f"Successfully deleted user '{args.id}'")


def delete_setup_parser(parser):
    parser.add_argument(
        "--id",
        type=str,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--ignore-prompt",
        action="store_true",
        help="Ignore the prompt which asks you to confirm that you'd like to delete your user.",
    )


def orgs(args, context: CLIContext, parser: argparse.ArgumentParser):
    records = Org.for_self(roboto_client=context.roboto_client)
    for record in records:
        print(json.dumps(record.to_dict(), indent=2))


def whoami(args, context: CLIContext, parser: argparse.ArgumentParser):
    with RobotoHttpExceptionParse():
        contents = context.http_client.get(
            context.http_client.url("v1/users/whoami")
        ).to_dict(json_path=["data"])
        print(json.dumps(contents, indent=2))


delete_command = RobotoCommand(
    name="delete",
    logic=delete,
    setup_parser=delete_setup_parser,
    command_kwargs={"help": "Removes you from the roboto platform."},
)

orgs_command = RobotoCommand(
    name="orgs",
    logic=orgs,
    command_kwargs={"help": "Lists the roles that a user is a member of."},
)

show_command = RobotoCommand(
    name="show",
    logic=show,
    setup_parser=show_setup_parser,
    command_kwargs={"help": "Shows your user record."},
)

whoami_command = RobotoCommand(
    name="whoami",
    logic=whoami,
    command_kwargs={
        "help": "Returns the full identity context available to Roboto when you make a request."
    },
)

commands = [orgs_command, show_command, whoami_command, delete_command]

command_set = RobotoCommandSet(
    name="users",
    help="Get information about your account.",
    commands=commands,
)
