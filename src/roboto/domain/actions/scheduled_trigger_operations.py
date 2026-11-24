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
    """Request body for :py:meth:`~roboto.domain.actions.ScheduledTrigger.create`.

    Building it raises ``pydantic.ValidationError`` when:

    - ``name`` is empty, is longer than 256 characters, or has a character other than a letter, digit, underscore, or
      hyphen.
    - ``action_name`` has no letter, digit, underscore, or hyphen.
    - ``timeout`` is negative.
    """

    action_name: str = pydantic.Field(pattern=r"[\w\-]+")
    """Name of the action to invoke, unique within the organization that owns it.

    The trigger invokes the action's latest version.
    """

    action_owner_id: Optional[str] = None
    """ID of the organization that owns the action. ``None`` uses the organization the trigger is created in."""

    compute_requirement_overrides: Optional[ComputeRequirements] = None
    """Overrides of the action's compute requirements for each invocation. ``None`` uses the action's own."""

    container_parameter_overrides: Optional[ContainerParameters] = None
    """Overrides of the action's container parameters for each invocation. ``None`` uses the action's own."""

    enabled: bool
    """Whether the trigger invokes the action on its schedule once it is created."""

    invocation_input: Optional[InvocationInput] = None
    """Query that selects each invocation's input data when the invocation runs. ``None`` selects none."""

    invocation_upload_destination: Optional[InvocationUploadDestination] = None
    """Where each invocation uploads its output files. ``None`` sets none."""

    name: str = pydantic.Field(pattern=r"^[\w\-]+$", max_length=256)
    """Human-readable name of the trigger, unique within its organization.

    At most 256 characters, of letters, digits, underscores, and hyphens.
    """

    parameter_values: Optional[dict[str, Any]] = None
    """Values of the action's parameters, keyed by parameter name. ``None`` passes none."""

    schedule: str
    """Five-field cron expression, evaluated in UTC, that sets when the trigger invokes the action.

    For example, ``"0 * * * *"`` invokes it every hour on the hour.
    """

    timeout: Optional[Annotated[int, pydantic.Field(ge=0)]] = None
    """Maximum run time of each invocation, in minutes. ``None`` uses the action's own."""


class UpdateScheduledTriggerRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.actions.ScheduledTrigger.update`.

    Each field left unset (``NotSet``) leaves that property of the trigger unchanged.

    Building the request raises ``pydantic.ValidationError`` when ``action_name`` has no letter, digit, underscore, or
    hyphen, or when ``timeout`` is negative.
    """

    action_name: Union[Annotated[str, pydantic.Field(pattern=r"[\w\-]+")], NotSetType] = NotSet
    """Name of the action to invoke. The action's owner stays the same unless ``action_owner_id`` is also set."""

    action_owner_id: Union[str, NotSetType] = NotSet
    """ID of the organization that owns the action."""

    compute_requirement_overrides: Union[Optional[ComputeRequirements], NotSetType] = NotSet
    """Overrides of the action's compute requirements for each invocation.

    ``None`` clears the overrides, so invocations use the action's own.
    """

    container_parameter_overrides: Union[Optional[ContainerParameters], NotSetType] = NotSet
    """Overrides of the action's container parameters for each invocation.

    ``None`` clears the overrides, so invocations use the action's own.
    """

    enabled: Union[bool, NotSetType] = NotSet
    """Whether the trigger invokes the action on its schedule."""

    invocation_input: Union[Optional[InvocationInput], NotSetType] = NotSet
    """Query that selects each invocation's input data when the invocation runs. ``None`` clears it."""

    invocation_upload_destination: Union[Optional[InvocationUploadDestination], NotSetType] = NotSet
    """Where each invocation uploads its output files. ``None`` clears it."""

    parameter_values: Union[Optional[dict[str, Any]], NotSetType] = NotSet
    """Values of the action's parameters, keyed by parameter name. ``None`` clears them."""

    schedule: Union[str, NotSetType] = NotSet
    """Five-field cron expression, evaluated in UTC, that sets when the trigger invokes the action."""

    timeout: Union[Optional[Annotated[int, pydantic.Field(ge=0)]], NotSetType] = NotSet
    """Maximum run time of each invocation, in minutes.

    ``None`` clears the override, so invocations use the action's own.
    """

    model_config = pydantic.ConfigDict(extra="ignore", json_schema_extra=NotSetType.openapi_schema_modifier)
