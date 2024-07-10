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
    # Required
    name: str

    # Optional
    compute_requirements: Optional[ComputeRequirements] = None
    container_parameters: Optional[ContainerParameters] = None
    description: Optional[str] = None
    inherits: Optional[ActionReference] = None
    metadata: Optional[dict[str, Any]] = pydantic.Field(default_factory=dict)
    parameters: Optional[list[ActionParameter]] = pydantic.Field(default_factory=list)
    short_description: Optional[str] = None
    tags: Optional[list[str]] = pydantic.Field(default_factory=list)
    timeout: Optional[int] = None
    uri: Optional[str] = None


class SetActionAccessibilityRequest(pydantic.BaseModel):
    accessibility: Accessibility
    digest: Optional[str] = None
    """Specify specific version of Action. If not specified, the latest version's accessibility will be updated."""
    model_config = ConfigDict(extra="forbid")


class UpdateActionRequest(pydantic.BaseModel):
    compute_requirements: Optional[Union[ComputeRequirements, NotSetType]] = NotSet
    container_parameters: Optional[Union[ContainerParameters, NotSetType]] = NotSet
    description: Optional[Union[str, NotSetType]] = NotSet
    inherits: Optional[Union[ActionReference, NotSetType]] = NotSet
    metadata_changeset: Union[MetadataChangeset, NotSetType] = NotSet
    parameter_changeset: Union[ActionParameterChangeset, NotSetType] = NotSet
    uri: Optional[Union[str, NotSetType]] = NotSet
    short_description: Optional[Union[str, NotSetType]] = NotSet
    timeout: Optional[Union[int, NotSetType]] = NotSet

    @pydantic.field_validator("uri")
    def validate_uri(cls, v):
        if v is None or is_not_set(v):
            return v

        stripped = v.strip()
        if not stripped:
            raise ValueError("uri cannot be empty")
        return stripped

    model_config = ConfigDict(
        extra="forbid", json_schema_extra=NotSetType.openapi_schema_modifier
    )
