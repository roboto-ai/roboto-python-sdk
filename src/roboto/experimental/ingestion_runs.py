# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

"""The runs of an ingestion rule's trigger on a file.

A leaf module: :mod:`roboto.experimental.sessions` reports runs too, and importing
:mod:`roboto.experimental.ingestion_rules` from there would be circular.
"""

import datetime
import typing

import pydantic

from ..compat import StrEnum


class IngestionRunStatus(StrEnum):
    """Where one run of a rule's trigger on a file stands."""

    Running = "running"
    """The ingestion action is queued or running."""

    Failed = "failed"
    """The action failed or was cancelled, or the trigger could not start it."""

    Finished = "finished"
    """The action finished. The file's ``ingestion_status`` says how much of it was ingested."""


class IngestionRun(pydantic.BaseModel):
    """The latest time an ingestion rule's trigger ran on a file's current upload."""

    file_id: str
    rule_id: str
    """The rule whose trigger ran."""
    trigger_id: str
    started: datetime.datetime
    status: IngestionRunStatus
    invocation_id: typing.Optional[str] = None
    """The action invocation the run started. ``None`` when the trigger could not start one."""
    detail: typing.Optional[str] = None
    """Why the trigger could not start the action, when it could not."""
