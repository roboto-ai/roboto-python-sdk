# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse

from ...image_registry import ImageRegistry
from ..command import RobotoCommand
from ..common_args import add_org_arg
from ..context import CLIContext


def delete_repository(
    args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser
) -> None:
    image_registry = ImageRegistry(context.roboto_client)
    image_registry.delete_repository(
        args.repository_name, org_id=args.org, force=args.force
    )


def delete_repository_parser(parser: argparse.ArgumentParser) -> None:
    add_org_arg(parser)

    parser.add_argument(
        "repository_name",
        action="store",
        help="The name of the image repository to delete.",
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Force deletion of the repository, even if it is not empty.",
    )


delete_repo_command = RobotoCommand(
    name="delete-repository",
    logic=delete_repository,
    setup_parser=delete_repository_parser,
    command_kwargs={
        "help": (
            "Delete an image repository hosted in Roboto's image registry. "
            "Requires Docker CLI."
        )
    },
)
