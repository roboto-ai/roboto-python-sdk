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


def delete_image(
    args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser
) -> None:
    image_registry = ImageRegistry(context.roboto_client)
    image_registry.delete_image(args.remote_image, org_id=args.org)


def delete_image_parser(parser: argparse.ArgumentParser) -> None:
    add_org_arg(parser)

    parser.add_argument(
        "remote_image",
        action="store",
        help="Specify the remote image to delete, in the format ``<repository>:<tag>``.",
    )


delete_image_command = RobotoCommand(
    name="delete-image",
    logic=delete_image,
    setup_parser=delete_image_parser,
    command_kwargs={
        "help": (
            "Delete a container image hosted in Roboto's image registry. "
            "Requires Docker CLI."
        )
    },
)
