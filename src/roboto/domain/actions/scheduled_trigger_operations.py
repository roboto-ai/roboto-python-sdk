# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

from typing import Annotated, Any, Optional, Union

import pydantic

from ...sentinels import NotSet, NotSetType
from .action_record import (
    ComputeRequirements,
    ContainerParameters,
)
from .invocation_record import (
    InvocationInput,
    InvocationUploadDestination,
)


class CreateScheduledTriggerRequest(pydantic.BaseModel):
    """Request payload to create a scheduled trigger.

    See :py:meth:`~roboto.domain.actions.ScheduledTrigger.create` for details
    on the request attributes.
    """

    action_name: str = pydantic.Field(pattern=r"[\w\-]+")
    action_owner_id: Optional[str] = None
    compute_requirement_overrides: Optional[ComputeRequirements] = None
    container_parameter_overrides: Optional[ContainerParameters] = None
    enabled: bool
    invocation_input: Optional[InvocationInput] = None
    invocation_upload_destination: Optional[InvocationUploadDestination] = None
    name: str = pydantic.Field(pattern=r"[\w\-]+", max_length=256)
    parameter_values: Optional[dict[str, Any]] = None
    schedule: str
    timeout: Optional[Annotated[int, pydantic.Field(ge=0)]] = None


class UpdateScheduledTriggerRequest(pydantic.BaseModel):
    """Request payload to update a scheduled trigger.

    See :py:meth:`~roboto.domain.actions.ScheduledTrigger.update` for details
    on the request attributes.
    """

    action_name: Union[
        Annotated[str, pydantic.Field(pattern=r"[\w\-]+")], NotSetType
    ] = NotSet
    action_owner_id: Union[str, NotSetType] = NotSet
    compute_requirement_overrides: Union[Optional[ComputeRequirements], NotSetType] = (
        NotSet
    )
    container_parameter_overrides: Union[Optional[ContainerParameters], NotSetType] = (
        NotSet
    )
    enabled: Union[bool, NotSetType] = NotSet
    invocation_input: Union[Optional[InvocationInput], NotSetType] = NotSet
    invocation_upload_destination: Union[
        Optional[InvocationUploadDestination], NotSetType
    ] = NotSet
    parameter_values: Union[Optional[dict[str, Any]], NotSetType] = NotSet
    schedule: Union[str, NotSetType] = NotSet
    timeout: Union[Optional[Annotated[int, pydantic.Field(ge=0)]], NotSetType] = NotSet
