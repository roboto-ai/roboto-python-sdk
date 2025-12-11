# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import pathlib
import tempfile

from cookiecutter.main import cookiecutter

from ..command import RobotoCommand
from ..context import CLIContext

COOKIECUTTER_REPO = "https://github.com/roboto-ai/cookiecutter-roboto-actions.git"


def init(args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser) -> None:
    path: pathlib.Path = args.path
    path = path.resolve()
    print(f"Creating Roboto action package under: {path}")

    if not path.is_dir():
        parser.error(f"{path} does not exist, or is not a directory.")

    with tempfile.TemporaryDirectory() as tmpdir:
        # GM (2025-11-05)
        # cookiecutter currently always includes the following prompt:
        #   > You've downloaded ... before. Is it okay to delete and re-download it? [y/n] (y)
        # I think this is annoying and useless. Also selecting "n" is always the wrong thing to do.
        # cookiecutter maintainers refuse to add an option for always redownloading the template:
        # see https://github.com/cookiecutter/cookiecutter/issues/1201.
        # So, this.
        # Refs:
        #   1. https://github.com/cookiecutter/cookiecutter/blob/main/cookiecutter/main.py#L79-L82
        #   2. https://github.com/cookiecutter/cookiecutter/blob/main/cookiecutter/config.py#L89-L113
        cookiecutter_config = {"cookiecutters_dir": tmpdir}

        try:
            cookiecutter(
                COOKIECUTTER_REPO,
                output_dir=str(path),
                default_config=cookiecutter_config,  # type: ignore
            )
        except KeyboardInterrupt:
            pass


def init_parser(parser: argparse.ArgumentParser):
    parser.add_argument(
        "path",
        nargs="?",
        type=pathlib.Path,
        help="Existing directory under which an action package will be created.",
        default=pathlib.Path.cwd(),
    )


init_command = RobotoCommand(
    name="init",
    logic=init,
    setup_parser=init_parser,
    command_kwargs={"help": "Initialize a new action package."},
)
