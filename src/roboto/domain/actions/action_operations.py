# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from typing import Any, Optional, Union

import pydantic
from pydantic import ConfigDict

from ...sentinels import (
    NotSet,
    NotSetType,
    is_not_set,
)
from ...updates import MetadataChangeset
from .action_record import (
    Accessibility,
    ActionParameter,
    ActionParameterChangeset,
    ActionReference,
    ComputeRequirements,
    ContainerParameters,
)


class CreateActionRequest(pydantic.BaseModel):
    """Request payload to create a new action.

    Contains all the configuration needed to create a new action in the Roboto
    platform, including container settings, compute requirements, parameters,
    and metadata.
    """

    # Required
    name: str
    """Unique name for the action within the organization."""

    # Optional
    compute_requirements: Optional[ComputeRequirements] = None
    """CPU, memory, and other compute specifications."""

    container_parameters: Optional[ContainerParameters] = None
    """Container image URI, entrypoint, and environment variables."""

    description: Optional[str] = None
    """Detailed description of what the action does."""

    inherits: Optional[ActionReference] = None
    """Reference to another action to inherit configuration from."""

    metadata: dict[str, Any] = pydantic.Field(default_factory=dict)
    """Custom key-value metadata to associate with the action."""

    parameters: list[ActionParameter] = pydantic.Field(default_factory=list)
    """List of parameters that can be provided at invocation time."""

    requires_downloaded_inputs: Optional[bool] = None
    """Whether input files should be downloaded before execution."""

    short_description: Optional[str] = None
    """Brief description (max 140 characters) for display purposes."""

    tags: list[str] = pydantic.Field(default_factory=list)
    """List of tags for categorizing and searching actions."""

    timeout: Optional[int] = None
    """Maximum execution time in minutes before the action is terminated."""

    uri: Optional[str] = None
    """Container image URI if not inheriting from another action."""


class SetActionAccessibilityRequest(pydantic.BaseModel):
    """Request payload to set action accessibility.

    Used to change whether an action is private to the organization or
    published publicly in the Action Hub.
    """

    accessibility: Accessibility
    """The new accessibility level (Organization or ActionHub)."""

    digest: Optional[str] = None
    """Specific version of Action. If not specified, the latest version's accessibility will be updated."""
    model_config = ConfigDict(extra="ignore")


class UpdateActionRequest(pydantic.BaseModel):
    """Request payload to update an action.

    Contains the changes to apply to an existing action. Only specified fields
    will be updated; others remain unchanged. Uses NotSet sentinel values to
    distinguish between explicit None values and unspecified fields.
    """

    compute_requirements: Optional[Union[ComputeRequirements, NotSetType]] = NotSet
    """New compute requirements (CPU, memory)."""

    container_parameters: Optional[Union[ContainerParameters, NotSetType]] = NotSet
    """New container parameters (image, entrypoint, etc.)."""

    description: Optional[Union[str, NotSetType]] = NotSet
    """New detailed description."""

    inherits: Optional[Union[ActionReference, NotSetType]] = NotSet
    """New action reference to inherit from."""

    metadata_changeset: Union[MetadataChangeset, NotSetType] = NotSet
    """Changes to apply to metadata (add, remove, update keys)."""

    parameter_changeset: Union[ActionParameterChangeset, NotSetType] = NotSet
    """Changes to apply to parameters (add, remove, update)."""

    uri: Optional[Union[str, NotSetType]] = NotSet
    """New container image URI."""

    short_description: Optional[Union[str, NotSetType]] = NotSet
    """New brief description (max 140 characters)."""

    timeout: Optional[Union[int, NotSetType]] = NotSet
    """New maximum execution time in minutes."""

    requires_downloaded_inputs: Union[bool, NotSetType] = NotSet
    """Whether to download input files before execution."""

    @pydantic.field_validator("uri")
    def validate_uri(cls, v):
        if v is None or is_not_set(v):
            return v

        stripped = v.strip()
        if not stripped:
            raise ValueError("uri cannot be empty")
        return stripped

    model_config = ConfigDict(
        extra="ignore", json_schema_extra=NotSetType.openapi_schema_modifier
    )
