# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
from typing import Any, Optional

import pydantic

from .action_record import (
    ComputeRequirements,
    ContainerParameters,
)
from .invocation_record import (
    InvocationDataSourceType,
    InvocationSource,
    InvocationStatus,
)


class CancelActiveInvocationsRequest(pydantic.BaseModel):
    """
    Request payload to bulk cancel all active invocations within an org.

    This will only cancel invocations which are in a non-terminal state,
    and will limit the number of invocations it attempts to cancel.

    Continue calling this operation until the count_remaining returned in the
    py:class:`~roboto.domain.actions.CancelActiveInvocationsResponse` is 0.
    """

    created_before: Optional[datetime.datetime] = None
    """Only cancel invocations created before this time."""


class CancelActiveInvocationsResponse(pydantic.BaseModel):
    """
    Response payload to bulk cancel all active invocations within an org.
    """

    success_count: int
    """Count of invocations successfully cancelled"""

    failure_count: int
    """Count of invocations that failed to cancel"""

    count_remaining: int
    """Number of invocations that are still active"""


class CreateInvocationRequest(pydantic.BaseModel):
    """
    Request payload to create a new invocation
    """

    compute_requirement_overrides: Optional[ComputeRequirements] = None
    container_parameter_overrides: Optional[ContainerParameters] = None
    data_source_id: str
    data_source_type: InvocationDataSourceType
    idempotency_id: Optional[str] = None
    input_data: list[str]
    invocation_source: InvocationSource
    invocation_source_id: Optional[str] = None
    parameter_values: Optional[dict[str, Any]] = None
    timeout: Optional[int] = None


class SetContainerInfoRequest(pydantic.BaseModel):
    """
    Set container info for an invocation.

    Called from the `monitor` process once the action image has been pulled.
    """

    image_digest: str


class SetLogsLocationRequest(pydantic.BaseModel):
    """
    Set location where invocation logs are saved to files.

    Called from the `invocation-scheduling-service` once the invocation has been scheduled.
    """

    bucket: str
    prefix: str


class UpdateInvocationStatus(pydantic.BaseModel):
    """
    Request payload to update invocation status
    """

    status: InvocationStatus
    detail: str
