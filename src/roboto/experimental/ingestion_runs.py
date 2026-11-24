# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing

import pydantic

from ..compat import StrEnum


class IngestionRunStatus(StrEnum):
    """Status of an ingestion run: where the latest run of an ingestion rule's trigger on a file stands."""

    Running = "running"
    """The trigger is starting the ingestion action, or the action is queued or running."""

    Failed = "failed"
    """The action failed or was cancelled, or the trigger could not start it."""

    Finished = "finished"
    """The action completed.

    The file's :py:attr:`~roboto.domain.files.FileRecord.ingestion_status` says how much of the file it ingested.
    """


class IngestionRun(pydantic.BaseModel):
    """Data record of an ingestion run, as ``POST /v1/ingestion-rules/runs/latest`` returns it.

    An ingestion run is the latest time an ingestion rule's trigger ran on a file's current upload. Uploading the file
    again leaves it with no run until a trigger runs on the new upload; editing its tags or metadata keeps the run.
    :py:meth:`~roboto.experimental.sessions.Session.ingestion_status` also returns it, as each pending file's
    ``last_run``.
    """

    file_id: str
    """ID of the file the trigger ran on."""
    rule_id: str
    """ID of the ingestion rule whose trigger ran."""
    trigger_id: str
    """ID of the rule's trigger."""
    started: datetime.datetime
    """Time the trigger began the run."""
    status: IngestionRunStatus
    """Status of the run."""
    invocation_id: typing.Optional[str] = None
    """ID of the invocation the run started.

    ``None`` while the trigger is still starting the action, or when it could not start one.
    """
    detail: typing.Optional[str] = None
    """Why the trigger could not start the action, or ``None`` unless it failed to start it."""
