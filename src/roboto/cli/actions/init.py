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

COOKIECUTTER_CHECKOUT = "v2"
"""The template branch whose action.json uses ``schema_version`` 2. Earlier SDKs take the default branch,
whose action.json uses the legacy schema they read."""


def init(args: argparse.Namespace, context: CLIContext, parser: argparse.ArgumentParser) -> None:
    """Create an action package under ``path`` from Roboto's action package template, and print ``path``.

    ``path`` defaults to the current directory, and the template asks for the package's details at the terminal.
    Exits with status 2 when ``path`` is not an existing directory, and with status 1 when Git is not installed or
    creating the package fails; a missing Docker only prints a warning. Ctrl-C at one of the template's prompts ends
    the command without a traceback.
    """
    path: pathlib.Path = args.path
    path = path.resolve()

    if not path.is_dir():
        parser.error(f"{path} does not exist, or is not a directory.")

    # Creating the package needs Git: cookiecutter clones the template with it, and the template's hook can run
    # `git init` and `git commit`. Docker is needed only later, to build and run the package, so its absence only warns.
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
        # cookiecutter clones the template into cookiecutters_dir, and when it finds an earlier clone there it asks
        # `You've downloaded ... before. Is it okay to delete and re-download it?`; answering no either reuses that
        # possibly outdated clone or exits. Its no_input option skips the question but also the template's own
        # prompts, so clone into an empty temporary directory instead, where the question never comes up.
        cookiecutter_config = {"cookiecutters_dir": tmpdir}

        try:
            cookiecutter(
                COOKIECUTTER_REPO,
                checkout=COOKIECUTTER_CHECKOUT,
                output_dir=str(path),
                default_config=cookiecutter_config,  # type: ignore
            )
        except KeyboardInterrupt:
            # A user who presses Ctrl-C at one of the template's prompts exits without a traceback.
            pass
        except (CookiecutterException, subprocess.CalledProcessError) as exc:
            # cookiecutter raises CalledProcessError for a failed `git clone` and FailedHookException for a failed git
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
