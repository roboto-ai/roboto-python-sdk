# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import subprocess
import typing

from ..outcome import StepOutcome, StepStatus
from .environment import SetupEnvironment
from .files import download_file
from .prompts import Prompts, confirm

DOCKER_CHECK_TIMEOUT_SECONDS = 20

UV_INSTALL_SCRIPT_URL = "https://astral.sh/uv/install.sh"
UV_INSTALL_COMMAND = f"curl -LsSf {UV_INSTALL_SCRIPT_URL} | sh"
# The PowerShell pipeline that downloads Astral's installer for Windows and runs it.
UV_WINDOWS_INSTALL_PIPELINE = "irm https://astral.sh/uv/install.ps1 | iex"
UV_WINDOWS_INSTALL_ARGUMENTS = ("-ExecutionPolicy", "ByPass", "-c", UV_WINDOWS_INSTALL_PIPELINE)
# The same arguments as typed at a Windows prompt, with the pipeline, which holds spaces, in double quotes.
UV_WINDOWS_INSTALL_COMMAND = f'powershell -ExecutionPolicy ByPass -c "{UV_WINDOWS_INSTALL_PIPELINE}"'


def check_uv(environment: SetupEnvironment, prompts: typing.Optional[Prompts]) -> StepOutcome:
    """Report whether uv is installed, and offer to install it when it isn't.

    The ``roboto-guide`` skill runs Python scripts with uv when uv is installed, and needs Python 3.11 or newer
    without it, so uv is optional. When ``prompts`` is given and the user agrees, uv is installed with the installer
    Astral publishes for the platform, whose output goes to the terminal. A missing uv, a declined offer, and an
    install that fails are all reported as optional, never as a failure of setup, with the command that installs uv.

    Args:
        environment: The machine to check.
        prompts: Asks the user whether to install uv. ``None`` when nobody is at the keyboard, in which case nothing
            is installed.
    """
    if environment.which("uv") is not None:
        return StepOutcome(step="uv", status=StepStatus.AlreadyDone, summary="Installed.")

    what_for = "The roboto-guide skill uses uv to run scripts."
    install_command = UV_WINDOWS_INSTALL_COMMAND if environment.platform == "win32" else UV_INSTALL_COMMAND

    def not_installed(summary: str) -> StepOutcome:
        return StepOutcome(
            step="uv",
            status=StepStatus.Optional,
            summary=summary,
            next_steps=(f"To install it, run `{install_command}`.",),
        )

    if prompts is None:
        return not_installed(f"Not installed. {what_for}")
    if not confirm(prompts, f"  {what_for} Install it now?"):
        return not_installed("Not installed.")

    try:
        installed = _install_uv(environment)
    except Exception as exc:
        # The installer couldn't be downloaded or started, whatever the cause. Ctrl-C propagates and stops setup.
        return not_installed(f"Couldn't install it: {exc}")
    if not installed:
        return not_installed("Its installer failed.")
    return StepOutcome(
        step="uv", status=StepStatus.Done, summary="Installed.", next_steps=("Open a new terminal to use it.",)
    )


def check_docker(environment: SetupEnvironment) -> StepOutcome:
    """Report whether Docker is installed and running. Installs nothing.

    Only the ``create-roboto-action`` skill needs Docker, to build and run actions on the user's machine, so a missing
    or stopped Docker is reported as optional.

    Args:
        environment: The machine to check.
    """
    what_for = "The create-roboto-action skill uses Docker to test actions on this machine."

    docker = environment.which("docker")
    if docker is None:
        return StepOutcome(
            step="Docker",
            status=StepStatus.Optional,
            summary=f"Couldn't find the `docker` command. {what_for}",
            next_steps=("To install it, see https://docs.docker.com/get-started/get-docker/.",),
        )

    if not _docker_info_succeeds(docker, environment):
        return StepOutcome(
            step="Docker",
            status=StepStatus.Optional,
            summary=f"Installed, but `docker info` failed. {what_for}",
            next_steps=("Start Docker before you use that skill.",),
        )

    return StepOutcome(step="Docker", status=StepStatus.AlreadyDone, summary="Running.")


def _install_uv(environment: SetupEnvironment) -> bool:
    """Run Astral's uv installer for the platform, and return whether it exited successfully."""
    env = dict(environment.env)
    if environment.platform == "win32":
        powershell = environment.which("powershell") or "powershell"
        return subprocess.run([powershell, *UV_WINDOWS_INSTALL_ARGUMENTS], env=env).returncode == 0  # noqa: S603

    # The same script `curl ... | sh` would run. Setup downloads it itself, so curl isn't needed for that; the script
    # then downloads uv with curl or wget, and fails where the machine has neither.
    script = download_file(UV_INSTALL_SCRIPT_URL)
    return subprocess.run(["/bin/sh"], input=script, env=env).returncode == 0  # noqa: S603


def _docker_info_succeeds(docker: str, environment: SetupEnvironment) -> bool:
    # `docker info` exits non-zero when it can't connect to Docker: Docker is stopped, or the user lacks permission
    # to use it. A command that fails to start (OSError) or doesn't answer within the timeout counts as a failure
    # too; anything else, such as Ctrl-C, propagates.
    try:
        completed = subprocess.run(  # noqa: S603
            [docker, "info"],
            capture_output=True,
            env=dict(environment.env),
            stdin=subprocess.DEVNULL,
            timeout=DOCKER_CHECK_TIMEOUT_SECONDS,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return completed.returncode == 0
