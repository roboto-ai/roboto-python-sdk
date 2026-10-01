# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import argparse
import os
import sys

from ...version import __version__
from ..config import get_latest_version
from ..outcome import (
    StepOutcome,
    StepStatus,
    print_heading,
    print_outcomes,
)
from ..setup.environment import SetupEnvironment
from ..setup.skills import update_agent_skills
from .installation import (
    CLI_STEP,
    detect_installation,
    upgrade_installation,
)

HELP = "Upgrade the Roboto CLI and the agent skills `roboto setup` installed."

DESCRIPTION = (
    "Upgrade the Roboto CLI to the latest release, the way it was installed: a release binary is replaced in place "
    + "after its download is checked, and a Homebrew install is upgraded with Homebrew. For a .deb package or the "
    + "Python package, prints how to upgrade it. Then updates the agent skills `roboto setup` installed, and removes "
    + "any Roboto no longer publishes. Set ROBOTO_DOWNLOAD_URL to download the CLI's release files from a mirror. The "
    + "latest version is looked up on GitHub, and a release binary is replaced only when the mirror has that release."
)


def setup_parser(parser: argparse.ArgumentParser) -> None:
    # The notice that a newer release exists would be stale right after an upgrade.
    parser.set_defaults(suppress_upgrade_check=True)


def run(args: argparse.Namespace) -> None:
    """Upgrade the CLI, then the agent skills, and report each as it finishes, with anything the user still has to do.

    Exits with status 1 when either failed, and with status 130 when the user presses Ctrl-C.
    """
    color = sys.stdout.isatty()
    try:
        outcomes = _run_steps(color)
    except KeyboardInterrupt:
        # A downloaded CLI binary and each skill directory are renamed into place whole, so stopping partway leaves
        # each as it was before or after the upgrade.
        print()
        print("Upgrade stopped. Run `roboto upgrade` again to finish.")
        sys.exit(130)

    if any(outcome.status is StepStatus.Failed for outcome in outcomes):
        sys.exit(1)


def _run_steps(color: bool) -> list[StepOutcome]:
    print_heading(CLI_STEP, color)
    outcomes = print_outcomes([_upgrade_cli()], color)

    skills = update_agent_skills(SetupEnvironment.current())
    if skills is not None:
        print_heading("Agent skills", color)
        outcomes += print_outcomes([skills], color)

    return outcomes


def _upgrade_cli() -> StepOutcome:
    latest_version = get_latest_version()
    if latest_version is None:
        return StepOutcome(
            step=CLI_STEP,
            status=StepStatus.Failed,
            summary="Couldn't look up the latest release on GitHub.",
            next_steps=("Check your network connection, then run `roboto upgrade` again.",),
        )

    installation = detect_installation(
        env=os.environ, executable=sys.executable, frozen=getattr(sys, "frozen", False), platform=sys.platform
    )
    return upgrade_installation(
        installation,
        current_version=__version__,
        latest_version=latest_version,
        download_url=os.environ.get("ROBOTO_DOWNLOAD_URL") or None,
    )
