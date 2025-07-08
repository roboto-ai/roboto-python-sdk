# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing
from typing import Any, Optional

import pydantic

from .action_record import (
    ComputeRequirements,
    ContainerParameters,
)
from .invocation_record import (
    InvocationDataSourceType,
    InvocationInput,
    InvocationSource,
    InvocationStatus,
    InvocationUploadDestination,
)


class CancelActiveInvocationsRequest(pydantic.BaseModel):
    """Request payload to bulk cancel all active invocations within an organization.

    This operation cancels multiple invocations in a single request, but only
    affects invocations that are in non-terminal states (Queued, Running, etc.).
    The operation is limited in the number of invocations it will attempt to
    cancel in a single call for performance reasons.

    For large numbers of active invocations, continue calling this operation
    until the count_remaining returned in the response is 0.
    """

    created_before: Optional[datetime.datetime] = None
    """Only cancel invocations created before this timestamp.

    If not provided, cancels all active invocations regardless of age.
    """


class CancelActiveInvocationsResponse(pydantic.BaseModel):
    """Response payload from bulk cancellation of active invocations.

    Contains the results of a bulk cancellation operation, including counts
    of successful and failed cancellations, and the number of invocations
    remaining to be cancelled.
    """

    success_count: int
    """Number of invocations successfully cancelled."""

    failure_count: int
    """Number of invocations that failed to cancel."""

    count_remaining: int
    """Number of invocations that are still active."""


class CreateInvocationRequest(pydantic.BaseModel):
    """Request payload to create a new action invocation.

    Contains all the configuration needed to invoke an action, including
    input data specifications, parameter values, and execution overrides.
    """

    compute_requirement_overrides: Optional[ComputeRequirements] = None
    """Optional overrides for CPU, memory, and other compute specifications."""

    container_parameter_overrides: Optional[ContainerParameters] = None
    """Optional overrides for container image, entrypoint, and environment variables."""

    data_source_id: str
    """ID of the data source providing input data."""

    data_source_type: InvocationDataSourceType
    """Type of the data source (e.g., Dataset)."""

    idempotency_id: Optional[str] = None
    """Optional unique ID to ensure the invocation runs exactly once."""

    input_data: list[str]
    """List of file patterns for input data selection."""

    rich_input_data: typing.Optional[InvocationInput] = None
    """Optional rich input data specification that supersedes the simple input_data patterns."""

    invocation_source: InvocationSource
    """Source of the invocation (Manual, Trigger, etc.)."""

    invocation_source_id: Optional[str] = None
    """Optional ID of the entity that initiated the invocation."""

    parameter_values: Optional[dict[str, Any]] = None
    """Optional parameter values to pass to the action."""

    timeout: Optional[int] = None
    """Optional timeout override in minutes."""

    upload_destination: Optional[InvocationUploadDestination] = None
    """Optional destination for output files."""


class SetContainerInfoRequest(pydantic.BaseModel):
    """Request to set container information for an invocation.

    Used internally by the Roboto platform to record container details
    after the action image has been pulled and inspected.

    Note:
        This is typically called from the monitor process and is not
        intended for direct use by SDK users.
    """

    image_digest: str
    """The digest of the container image that was pulled."""


class SetLogsLocationRequest(pydantic.BaseModel):
    """Request to set the location where invocation logs are stored.

    Used internally by the Roboto platform to record where log files
    are saved for later retrieval.

    Note:
        This is typically called from the invocation-scheduling-service
        and is not intended for direct use by SDK users.
    """

    bucket: str
    """S3 bucket name where logs are stored."""

    prefix: str
    """S3 key prefix for the log files."""


class UpdateInvocationStatus(pydantic.BaseModel):
    """Request payload to update an invocation's status.

    Used to record status changes during invocation execution, such as
    transitioning from Queued to Running to Completed.
    """

    status: InvocationStatus
    """The new status for the invocation."""

    detail: str
    """Additional detail about the status change."""
