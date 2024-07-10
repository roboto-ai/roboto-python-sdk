# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

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


class CreateInvocationRequest(pydantic.BaseModel):
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
    status: InvocationStatus
    detail: str
