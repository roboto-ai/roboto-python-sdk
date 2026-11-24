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
"""Number of seconds ``check_docker`` waits for ``docker info`` to finish."""

DOCKER_INSTALL_URL = "https://docs.docker.com/get-started/get-docker/"

UV_INSTALL_SCRIPT_URL = "https://astral.sh/uv/install.sh"
UV_INSTALL_COMMAND = f"curl -LsSf {UV_INSTALL_SCRIPT_URL} | sh"
UV_WINDOWS_INSTALL_PIPELINE = "irm https://astral.sh/uv/install.ps1 | iex"
"""PowerShell pipeline that downloads Astral's uv installer for Windows and runs it."""

UV_WINDOWS_INSTALL_ARGUMENTS = ("-ExecutionPolicy", "ByPass", "-c", UV_WINDOWS_INSTALL_PIPELINE)
UV_WINDOWS_INSTALL_COMMAND = f'powershell -ExecutionPolicy ByPass -c "{UV_WINDOWS_INSTALL_PIPELINE}"'
"""Same command as typed at a Windows prompt, with the pipeline, which holds spaces, in double quotes."""


def check_uv(environment: SetupEnvironment, prompts: typing.Optional[Prompts]) -> StepOutcome:
    """Report whether uv is installed, and offer to install it when it is not.

    The ``roboto-guide`` skill runs Python scripts with uv when uv is installed, and needs Python 3.11 or newer
    without it, so uv is optional. When ``prompts`` is given and the user agrees, uv is installed with the installer
    Astral publishes for the operating system, which writes its output to the terminal. A missing uv, a declined
    offer, and a failed install are each reported as optional, never as a failure of setup, with the command that
    installs uv.

    Args:
        prompts: Asks the user whether to install uv. ``None``, for when nobody is at the keyboard, installs nothing.
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
        # Any Exception from downloading or starting the installer is reported here. Ctrl-C raises KeyboardInterrupt,
        # which this does not catch, so it still stops setup.
        return not_installed(f"Couldn't install it: {exc}")
    if not installed:
        return not_installed("Its installer failed.")
    return StepOutcome(
        step="uv", status=StepStatus.Done, summary="Installed.", next_steps=("Open a new terminal to use it.",)
    )


def check_docker(environment: SetupEnvironment) -> StepOutcome:
    """Report whether Docker is installed and running, without installing it.

    The skills that build and run actions on the user's machine, such as ``create-roboto-action``, need Docker.
    Nothing else setup installs depends on it, so a missing or stopped Docker is reported as optional.
    """
    what_for = "The create-roboto-action skill uses Docker to test actions on this machine."

    docker = environment.which("docker")
    if docker is None:
        return StepOutcome(
            step="Docker",
            status=StepStatus.Optional,
            summary=f"Couldn't find the `docker` command. {what_for}",
            next_steps=(f"To install it, see {DOCKER_INSTALL_URL}.",),
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
    """Run Astral's uv installer for the operating system, and return whether it exited successfully."""
    env = dict(environment.env)
    if environment.platform == "win32":
        powershell = environment.which("powershell") or "powershell"
        return subprocess.run([powershell, *UV_WINDOWS_INSTALL_ARGUMENTS], env=env).returncode == 0  # noqa: S603

    # The script UV_INSTALL_COMMAND pipes to sh. Setup downloads it itself, so this needs no curl, but the script then
    # downloads uv with curl or wget and fails on a machine with neither.
    script = download_file(UV_INSTALL_SCRIPT_URL)
    return subprocess.run(["/bin/sh"], input=script, env=env).returncode == 0  # noqa: S603


def _docker_info_succeeds(docker: str, environment: SetupEnvironment) -> bool:
    # `docker info` exits non-zero when it cannot reach the Docker daemon: Docker is not running, or the user lacks
    # permission to use it. A command that fails to start (OSError) or does not finish within
    # DOCKER_CHECK_TIMEOUT_SECONDS also counts as a failure; any other exception, such as Ctrl-C, propagates.
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
