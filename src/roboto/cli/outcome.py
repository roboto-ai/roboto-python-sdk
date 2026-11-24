# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import dataclasses
import enum

from .terminal import AnsiColor, print_list_item


class StepStatus(enum.Enum):
    """Status of one step of ``roboto setup`` or ``roboto upgrade``: how the step ended.

    Both commands run every step whatever the earlier ones returned. ``Failed`` is the only status that makes either
    command exit with status 1; ``ActionNeeded`` leaves the exit status at 0.
    """

    ActionNeeded = "action_needed"
    """The step is not complete, and only the user can complete it, as the outcome's ``next_steps`` say."""

    AlreadyDone = "already_done"
    """The machine was already in the state the step produces, so the command changed nothing."""

    Done = "done"
    """The command made the change the step is responsible for."""

    Failed = "failed"
    """The command hit an error on the step, possibly after making some of its changes.

    The outcome's ``summary`` says what went wrong.
    """

    Optional = "optional"
    """The step is not complete, or the command cannot tell whether it is.

    Nothing else the command sets up depends on the step, so the user may leave it.
    """


@dataclasses.dataclass(frozen=True)
class StepOutcome:
    """Result of one step of ``roboto setup`` or ``roboto upgrade``, as the command reports it to the user."""

    step: str
    """Name of what the step sets up, checks, or upgrades, such as ``Access token``, ``Cursor``, or ``Roboto CLI``."""

    status: StepStatus

    summary: str
    """Short account of what happened. A failure may quote another program's output, which can span lines."""

    next_steps: tuple[str, ...] = ()
    """Instructions for what the user should do next, one per entry, printed under the summary.

    An outcome of any status may carry them.
    """


# An optional step has no marker, so it does not read as work the command left undone.
_MARKERS = {
    StepStatus.ActionNeeded: (AnsiColor.BLUE, "todo"),
    StepStatus.AlreadyDone: (AnsiColor.GREEN, "ok"),
    StepStatus.Done: (AnsiColor.GREEN, "done"),
    StepStatus.Failed: (AnsiColor.RED, "failed"),
}


def print_heading(heading: str, color: bool) -> None:
    """Print the heading over a group of steps, after a blank line."""
    print()
    print(f"{AnsiColor.BLUE}==>{AnsiColor.END} {heading}" if color else f"==> {heading}")


def print_outcomes(outcomes: list[StepOutcome], color: bool) -> list[StepOutcome]:
    """Print each outcome, with its next steps on the lines under it, and return ``outcomes``.

    An outcome is marked with its status, apart from an optional step, which has no marker.
    """
    for outcome in outcomes:
        marker = _MARKERS.get(outcome.status)
        if marker is None:
            prefix = "  "
            # Indented past the step's name, which has no marker in front to set it apart from its next steps.
            next_step_indent = "    "
        else:
            ansi, label = marker
            uncolored_prefix = f"  [{label}] "
            prefix = f"  {ansi}[{label}] {AnsiColor.END}" if color else uncolored_prefix
            # Lined up under the step's name.
            next_step_indent = " " * len(uncolored_prefix)
        # A failure's summary can quote another program's output, and a next step can show a file entry to add by
        # hand; either may span lines.
        print_list_item(prefix, f"{outcome.step}: {outcome.summary}")
        for next_step in outcome.next_steps:
            print_list_item(next_step_indent, next_step)
    return outcomes
