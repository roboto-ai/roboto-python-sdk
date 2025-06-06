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
    """
    Request payload to create a new action
    """

    # Required
    name: str

    # Optional
    compute_requirements: Optional[ComputeRequirements] = None
    container_parameters: Optional[ContainerParameters] = None
    description: Optional[str] = None
    inherits: Optional[ActionReference] = None
    metadata: dict[str, Any] = pydantic.Field(default_factory=dict)
    parameters: list[ActionParameter] = pydantic.Field(default_factory=list)
    requires_downloaded_inputs: Optional[bool] = None
    short_description: Optional[str] = None
    tags: list[str] = pydantic.Field(default_factory=list)
    timeout: Optional[int] = None
    uri: Optional[str] = None


class SetActionAccessibilityRequest(pydantic.BaseModel):
    """
    Request payload to set action accessibility
    """

    accessibility: Accessibility
    digest: Optional[str] = None
    """Specify specific version of Action. If not specified, the latest version's accessibility will be updated."""
    model_config = ConfigDict(extra="ignore")


class UpdateActionRequest(pydantic.BaseModel):
    """
    Request payload to update an action
    """

    compute_requirements: Optional[Union[ComputeRequirements, NotSetType]] = NotSet
    container_parameters: Optional[Union[ContainerParameters, NotSetType]] = NotSet
    description: Optional[Union[str, NotSetType]] = NotSet
    inherits: Optional[Union[ActionReference, NotSetType]] = NotSet
    metadata_changeset: Union[MetadataChangeset, NotSetType] = NotSet
    parameter_changeset: Union[ActionParameterChangeset, NotSetType] = NotSet
    uri: Optional[Union[str, NotSetType]] = NotSet
    short_description: Optional[Union[str, NotSetType]] = NotSet
    timeout: Optional[Union[int, NotSetType]] = NotSet
    requires_downloaded_inputs: Union[bool, NotSetType] = NotSet

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
