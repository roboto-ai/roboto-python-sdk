# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import shlex
import subprocess

from ...auth import Permissions
from ...image_registry import ImageRegistry
from ..command import RobotoCommand
from ..common_args import add_org_arg
from ..context import CLIContext


def login(
    args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser
) -> None:
    image_registry = ImageRegistry(context.roboto_client)
    permissions = Permissions(args.permissions)
    credentials = image_registry.get_temporary_credentials(
        args.repository_uri, permissions, org_id=args.org
    )
    cmd = f"docker login --username {credentials.username} --password-stdin {credentials.registry_url}"
    docker_login_completed_process = subprocess.run(
        shlex.split(cmd),
        capture_output=True,
        check=True,
        input=credentials.password,
        text=True,
    )
    print(docker_login_completed_process.stdout)


def login_parser(parser: argparse.ArgumentParser) -> None:
    add_org_arg(parser)

    parser.add_argument(
        "--repository-uri",
        dest="repository_uri",
        required=True,
        action="store",
        help="Image repository within Roboto's image registry. Login credentials will be scoped to this repository.",
    )

    parser.add_argument(
        "--permissions",
        required=False,
        action="store",
        choices=[p.value for p in Permissions],
        default=Permissions.ReadWrite.value,
        help="Specify the access level for the temporary credentials.",
    )


login_command = RobotoCommand(
    name="login",
    logic=login,
    setup_parser=login_parser,
    command_kwargs={
        "help": (
            "Temporarily login to Roboto's image registry. "
            "Requires Docker CLI. Login is valid for 12 hours and is scoped to a particular repository."
        )
    },
)
