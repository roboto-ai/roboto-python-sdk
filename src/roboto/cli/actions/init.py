# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import os
import pathlib

from cookiecutter.main import cookiecutter

from ..command import RobotoCommand
from ..context import CLIContext

COOKIECUTTER_REPO = "https://github.com/roboto-ai/cookiecutter-roboto-actions.git"


def init(
    args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser
) -> None:
    path: pathlib.Path = args.path
    path = path.resolve()
    print(f"Creating Roboto action package under: {path}")

    if not path.is_dir():
        parser.error(f"{path} does not exist, or is not a directory.")

    cookiecutter(COOKIECUTTER_REPO, output_dir=path)


def init_parser(parser: argparse.ArgumentParser):
    parser.add_argument(
        "path",
        nargs="?",
        type=pathlib.Path,
        help="Existing directory under which an action package will be created.",
        default=os.getcwd(),
    )


init_command = RobotoCommand(
    name="init",
    logic=init,
    setup_parser=init_parser,
    command_kwargs={"help": "Initialize a new action package."},
)
