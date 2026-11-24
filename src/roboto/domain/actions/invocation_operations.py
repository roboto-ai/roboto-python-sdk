# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import datetime
import typing
from typing import Any, Optional

import pydantic

from ...query import ConditionType
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
    """Request body for ``POST /v1/actions/invocations/cancel/all``.

    The ``roboto invocations cancel-all`` CLI command sends it. Each request cancels active invocations, those that
    have not completed, failed, or been cancelled: every queued one in the organization and a limited number of those
    already scheduled or running. Repeat it until the response's
    ``CancelActiveInvocationsResponse.has_more`` is ``False``, as the CLI command does.
    """

    created_before: Optional[datetime.datetime] = None
    """Latest creation time of the scheduled and running invocations to cancel, inclusive.

    It does not limit queued invocations: each request cancels those whatever their age. ``None`` sets no age limit.
    """

    condition: Optional[ConditionType] = None
    """Condition an invocation must match to be cancelled. ``None`` cancels every active invocation in the organization.

    Takes the fields and comparators of ``POST /v1/actions/invocations/query``; for example, ``input.session_id`` equal
    to a session ID cancels the invocations whose input names that session.
    """


class CancelActiveInvocationsResponse(pydantic.BaseModel):
    """Response body of ``POST /v1/actions/invocations/cancel/all``.

    That route takes ``CancelActiveInvocationsRequest``.
    ``POST /v1/datasets/{dataset_id}/invocations/cancel``, which cancels the invocations whose data source is that
    dataset, also returns it.
    """

    success_count: int
    """Number of invocations this request cancelled."""

    failure_count: int
    """Number of invocations this request tried and failed to cancel."""

    has_more: bool
    """Whether active invocations may remain after this request.

    They remain either beyond the number one request cancels or because a cancellation failed. Repeat the request until
    it is ``False``.
    """


class CreateInvocationRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.actions.Action.invoke`, which starts one run of an action."""

    compute_requirement_overrides: Optional[ComputeRequirements] = None
    """Compute requirements, such as vCPU and memory, that replace the action's own.

    Fields left unset keep the action's values. ``None`` uses the action's own.
    """

    container_parameter_overrides: Optional[ContainerParameters] = None
    """Container parameters, such as the entry point and environment variables, that replace the action's own.

    Fields left unset keep the action's values. ``None`` uses the action's own.
    """

    data_source_id: str
    """ID of the dataset the invocation reads from.

    An invocation that reads from no dataset takes the ``data_source_id`` of
    :py:meth:`~roboto.domain.actions.InvocationDataSource.unspecified` instead.
    """

    data_source_type: InvocationDataSourceType
    """Type of the data source that ``data_source_id`` names.

    :py:attr:`~roboto.domain.actions.InvocationDataSourceType.Dataset` is the only type.
    """

    idempotency_id: Optional[str] = None
    """ID that no other invocation may share.

    A request that repeats one is rejected with ``RobotoConflictException``, so retrying it never runs the action
    twice. ``None`` sets no such ID.
    """

    input_data: list[str]
    """Deprecated. Gitignore-style patterns for the files in the data source to read.

    Use ``rich_input_data`` instead. Ignored when ``rich_input_data`` is set.
    """

    rich_input_data: typing.Optional[InvocationInput] = None
    """Inputs the invocation reads, such as files, topics, or sessions. ``None`` falls back to ``input_data``."""

    invocation_source: InvocationSource
    """Whether a user or a trigger started the invocation.

    Only Roboto can create invocations with source :py:attr:`~roboto.domain.actions.InvocationSource.Trigger`.
    """

    invocation_source_id: Optional[str] = None
    """ID of the user or trigger that started the invocation.

    On a :py:attr:`~roboto.domain.actions.InvocationSource.Manual` invocation, Roboto replaces it with the caller's
    user ID.
    """

    owner_org_id: Optional[str] = None
    """ID of the organization that owns the action, such as ``roboto-public`` for an action in the Action Hub.

    The invocation is created in the caller's organization, not the action's. ``None`` looks the action up in the
    organization the request's headers name.
    """

    parameter_values: Optional[dict[str, Any]] = None
    """Values for the action's parameters, keyed by parameter name.

    Roboto converts each value to a string, and fills in the default of each parameter left out. ``None`` gives no
    values, which Roboto rejects with ``RobotoInvalidRequestException`` when the action has a required parameter.
    """

    timeout: Optional[int] = None
    """Maximum time the invocation may run, in minutes.

    ``None`` uses the action's timeout, or Roboto's default when the action has none.
    """

    upload_destination: Optional[InvocationUploadDestination] = None
    """Dataset to upload the files the invocation writes to its output directory to.

    ``None`` uploads them to the dataset the invocation's input files and topics come from when they all come from one,
    and otherwise not at all.
    """


class SetContainerInfoRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.actions.Invocation.set_container_image_digest`.

    Only the invocation itself, while it runs, or Roboto administrators may send it.
    """

    image_digest: str
    """Digest of the container image the invocation pulled to run."""


class SetLogsLocationRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.actions.Invocation.set_logs_location`.

    Only Roboto administrators may send it.
    """

    bucket: str
    """Name of the S3 bucket that holds the invocation's logs."""

    prefix: str
    """S3 key prefix under which the invocation's log files are stored."""


class UpdateInvocationStatus(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.actions.Invocation.update_status`.

    Only the invocation itself, while it runs, or Roboto administrators may send it.
    """

    status: InvocationStatus
    """Status the invocation moves to."""

    detail: str
    """Human-readable detail recorded with the status, such as why the invocation failed."""
