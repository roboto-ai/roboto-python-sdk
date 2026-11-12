# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import pathlib
import shutil
import subprocess
import tempfile

from cookiecutter.exceptions import CookiecutterException
from cookiecutter.main import cookiecutter

from ..command import RobotoCommand
from ..context import CLIContext
from ..setup.prerequisites import DOCKER_INSTALL_URL
from ..terminal import print_error_and_exit, print_warning

COOKIECUTTER_REPO = "https://github.com/roboto-ai/cookiecutter-roboto-actions.git"
GIT_INSTALL_URL = "https://git-scm.com/downloads"


def init(args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser) -> None:
    path: pathlib.Path = args.path
    path = path.resolve()

    if not path.is_dir():
        parser.error(f"{path} does not exist, or is not a directory.")

    # Git is needed now: cookiecutter clones the template with it, and the template's hook can run git init and git
    # commit. Docker is needed only later, to build and run the package.
    if shutil.which("git") is None:
        print_error_and_exit(
            [
                "Couldn't find the `git` command. Creating an action package needs Git.",
                f"To install Git, see {GIT_INSTALL_URL}.",
            ]
        )
    if shutil.which("docker") is None:
        print_warning(
            [
                "Couldn't find the `docker` command. Building and running the action package needs Docker.",
                f"To install Docker, see {DOCKER_INSTALL_URL}.",
            ]
        )

    print(f"Creating Roboto action package under: {path}")

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
        except (CookiecutterException, subprocess.CalledProcessError) as exc:
            # cookiecutter raises CalledProcessError for a failed git clone and FailedHookException for a failed git
            # command in the template's hook. Either way, Git's own output is already on the terminal.
            print_error_and_exit(f"Couldn't create the action package: {exc}")


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
    requires_config=False,
)
