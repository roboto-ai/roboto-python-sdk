# Copyright (c) 2025 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import pathlib
import typing

import pydantic
from pydantic import ConfigDict

from .action_record import (
    ActionParameter,
    ActionReference,
    ComputeRequirements,
    ContainerParameters,
)


class DockerImageConfig(pydantic.BaseModel):
    dockerfile: pathlib.Path = pathlib.Path.cwd() / "Dockerfile"
    context: pathlib.Path = pathlib.Path.cwd()
    build_args: dict[str, str] = pydantic.Field(default_factory=dict)


class ActionConfig(pydantic.BaseModel):
    """User-facing model for Action configuration used when creating or updating Actions.

    This model defines the structure of the "action.json" file accepted by
    ``roboto actions create --from-file`` and templated for new Roboto Actions
    created by ``roboto actions init``.

    ActionConfig intentionally differs from :py:class:`roboto.domain.actions.action_record.ActionRecord`
    by providing a simplified interface that:
        - Omits platform-managed fields (e.g., ``created``, ``modified``, ``org_id``, ``digest``)
        - Omits post-creation fields (e.g., ``published``, ``accessibility``)
        - Focuses on user-configurable options relevant at creation time

    Structure:
        - Required: ``name``
        - Optional: Most configuration options (compute requirements, parameters, metadata, etc.)

    See Also:
        :py:class:`roboto.domain.actions.action_record.ActionRecord`: The complete action representation
        :py:class:`roboto.domain.actions.action_record.ActionParameter`: Parameter configuration
        :py:class:`roboto.domain.actions.action_record.ComputeRequirements`: Compute resource configuration
    """

    # Required
    name: str

    # Optional
    compute_requirements: typing.Optional[ComputeRequirements] = None
    container_parameters: typing.Optional[ContainerParameters] = None
    description: typing.Optional[str] = None
    inherits: typing.Optional[ActionReference] = None
    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    parameters: list[ActionParameter] = pydantic.Field(default_factory=list)
    requires_downloaded_inputs: typing.Optional[bool] = None
    tags: list[str] = pydantic.Field(default_factory=list)
    short_description: typing.Optional[str] = None
    timeout: typing.Optional[int] = None

    # Mutually exclusive
    docker_config: typing.Optional[DockerImageConfig] = None
    """Configuration with which to build a Docker image for the Action."""

    image_uri: typing.Optional[str] = None
    """URI to a non-local Docker image. Must already be pushed a registry accessible by the Roboto Platform."""

    @classmethod
    def from_file(cls, path: pathlib.Path) -> "ActionConfig":
        """Load ActionConfig from a JSON file.

        Args:
            path: Path to the JSON file containing action configuration

        Returns:
            Parsed ActionConfig instance

        Raises:
            FileNotFoundError: If the file doesn't exist
            pydantic.ValidationError: If the JSON is invalid or doesn't match the schema
        """
        if not path.exists():
            raise FileNotFoundError(f"{path.name} not found: {path}")
        return cls.model_validate_json(path.read_text())

    @pydantic.model_validator(mode="before")
    def enforce_invariants(cls, values: dict) -> dict:
        if values.get("docker_config") and values.get("image_uri"):
            raise ValueError(
                "'docker_config' and 'image_uri' are mutually exclusive configuration options. "
                "Use 'docker_config' to build a Docker image from a local Dockerfile, "
                "or 'image_uri' to reference a Docker image already pushed to a registry "
                "accessible by the Roboto Platform."
            )
        return values

    model_config = ConfigDict(extra="ignore")
