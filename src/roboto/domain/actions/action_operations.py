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
    """Request body for :py:meth:`~roboto.domain.actions.Action.create`."""

    name: str
    """Human-readable name of the action, unique within its organization.

    Letters, digits, underscores, and dashes only.
    """

    compute_requirements: Optional[ComputeRequirements] = None
    """CPU, memory, and storage for the action's container.

    ``None`` uses the defaults of :py:class:`~roboto.domain.actions.ComputeRequirements`.
    """

    container_parameters: Optional[ContainerParameters] = None
    """Command, entry point, environment variables, and working directory for the action's container.

    ``None`` sets none of them.
    """

    description: Optional[str] = None
    """Human-readable description of the action."""

    inherits: Optional[ActionReference] = None
    """Deprecated. Action this action would inherit its configuration from.

    Set the configuration on the action itself instead. A request that sets this field fails with
    ``RobotoInvalidRequestException``.
    """

    metadata: dict[str, Any] = pydantic.Field(default_factory=dict)
    """Key-value metadata to set on the action."""

    parameters: list[ActionParameter] = pydantic.Field(default_factory=list)
    """Parameters a caller can set when invoking the action. Defaults to none.

    Names must be unique, and a required parameter cannot have a default. Otherwise the request fails with
    ``RobotoInvalidRequestException``.
    """

    requires_downloaded_inputs: Optional[bool] = None
    """Whether an invocation's input files are downloaded into the action's container before it runs.

    ``None`` means ``True``.
    """

    short_description: Optional[str] = None
    """Brief human-readable description of the action.

    :py:meth:`~roboto.domain.actions.Action.create` rejects one longer than 140 characters
    (:py:const:`~roboto.domain.actions.action.SHORT_DESCRIPTION_LENGTH`).
    """

    tags: list[str] = pydantic.Field(default_factory=list)
    """Tags to set on the action. Defaults to none."""

    timeout: Optional[int] = None
    """Maximum time, in minutes, an invocation of the action may run before Roboto stops it.

    ``None`` uses Roboto's default. A value above the organization's limit fails the request with
    ``RobotoLimitExceededException``.
    """

    uri: Optional[str] = None
    """URI of the container image the action runs, such as ``"ubuntu:latest"``."""


class SetActionAccessibilityRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.actions.Action.set_accessibility`.

    Only Roboto administrators may send it.

    A ``digest`` that matches no version of the action raises ``RobotoNotFoundException``.
    """

    accessibility: Accessibility
    """Who can find and invoke the action: members of its organization, or every Roboto user through the Action Hub."""

    digest: Optional[str] = None
    """Digest of the version of the action to return in the response. ``None`` returns the latest version.

    Accessibility applies to every version of the action, whatever the digest.
    """
    model_config = ConfigDict(extra="ignore")


class UpdateActionRequest(pydantic.BaseModel):
    """Request body for :py:meth:`~roboto.domain.actions.Action.update`.

    Each field left unset (``NotSet``) leaves that property of the action unchanged. A change to what the action runs
    (its image, container, compute, parameters, timeout, or input downloading) creates a new version of the action,
    with a new digest. A change to only its descriptions, tags, or metadata does not.

    Building the request raises ``pydantic.ValidationError`` when ``uri`` is empty after surrounding whitespace is
    stripped.
    """

    compute_requirements: Optional[Union[ComputeRequirements, NotSetType]] = NotSet
    """CPU, memory, and storage for the action's container.

    ``None`` resets them to the defaults of :py:class:`~roboto.domain.actions.ComputeRequirements`. A value above the
    organization's limits fails the request with ``RobotoLimitExceededException``.
    """

    container_parameters: Optional[Union[ContainerParameters, NotSetType]] = NotSet
    """Command, entry point, environment variables, and working directory for the action's container.

    ``None`` clears them.
    """

    description: Optional[Union[str, NotSetType]] = NotSet
    """Human-readable description of the action. ``None`` or ``""`` clears it."""

    inherits: Optional[Union[ActionReference, NotSetType]] = NotSet
    """Deprecated. Action this action would inherit its configuration from.

    Set the configuration on the action itself instead. A request that sets this field to an action reference fails
    with ``RobotoInvalidRequestException``.
    """

    metadata_changeset: Union[MetadataChangeset, NotSetType] = NotSet
    """Changes to the action's tags and metadata."""

    parameter_changeset: Union[ActionParameterChangeset, NotSetType] = NotSet
    """Parameters to add, replace, or remove, matched by name.

    The added parameters must have unique names, and a required parameter cannot have a default. Otherwise the request
    fails with ``RobotoInvalidRequestException``.
    """

    uri: Optional[Union[str, NotSetType]] = NotSet
    """URI of the container image the action runs. ``None`` clears it.

    Surrounding whitespace is stripped, and a URI that is empty after stripping is rejected.
    """

    short_description: Optional[Union[str, NotSetType]] = NotSet
    """Brief human-readable description of the action. ``None`` or ``""`` clears it.

    :py:meth:`~roboto.domain.actions.Action.update` rejects one longer than 140 characters
    (:py:const:`~roboto.domain.actions.action.SHORT_DESCRIPTION_LENGTH`).
    """

    timeout: Optional[Union[int, NotSetType]] = NotSet
    """Maximum time, in minutes, an invocation of the action may run before Roboto stops it.

    ``None`` clears it, so invocations use Roboto's default. A value above the organization's limit fails the request
    with ``RobotoLimitExceededException``.
    """

    requires_downloaded_inputs: Union[bool, NotSetType] = NotSet
    """Whether an invocation's input files are downloaded into the action's container before it runs."""

    @pydantic.field_validator("uri")
    def validate_uri(cls, v):
        """Reject a ``uri`` that is empty after surrounding whitespace is stripped, and return it stripped otherwise."""
        if v is None or is_not_set(v):
            return v

        stripped = v.strip()
        if not stripped:
            raise ValueError("uri cannot be empty")
        return stripped

    model_config = ConfigDict(extra="ignore", json_schema_extra=NotSetType.openapi_schema_modifier)
