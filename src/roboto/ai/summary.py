# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import enum

import pydantic


class AISummaryStatus(str, enum.Enum):
    """
    Status of an AI summary.
    """

    Pending = "pending"
    """The summary is being generated. Its text may be the empty string, or may be a partial result. If
    you continually poll for the summary while it is in the pending state, you will eventually get the
    complete summary."""

    Complete = "complete"
    """The summary has been generated."""

    Failed = "failed"
    """The summary failed to generate."""


class AISummary(pydantic.BaseModel):
    """
    A wire-transmissible representation of an AI summary
    """

    text: str
    """The text of the summary."""

    created: datetime.datetime
    """The time at which the summary was created."""

    status: AISummaryStatus
    """The status of the summary."""

    summary_id: str
    """The ID of the summary."""
