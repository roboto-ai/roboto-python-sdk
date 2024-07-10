# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import pathlib
import typing

import pydantic
from pydantic import ConfigDict

from ...domain import actions


class DockerImageConfig(pydantic.BaseModel):
    dockerfile: pathlib.Path = pathlib.Path.cwd() / "Dockerfile"
    context: pathlib.Path = pathlib.Path.cwd()
    build_args: dict[str, str] = pydantic.Field(default_factory=dict)


class ActionConfig(pydantic.BaseModel):
    """Model for file-based Action config, to be used when creating or updating Actions."""

    # Required
    name: str

    # Optional
    compute_requirements: typing.Optional[actions.ComputeRequirements] = None
    container_parameters: typing.Optional[actions.ContainerParameters] = None
    description: typing.Optional[str] = None
    inherits: typing.Optional[actions.ActionReference] = None
    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    parameters: list[actions.ActionParameter] = pydantic.Field(default_factory=list)
    tags: list[str] = pydantic.Field(default_factory=list)
    short_description: typing.Optional[str] = None
    timeout: typing.Optional[int] = None

    # Mutually exclusive
    docker_config: typing.Optional[DockerImageConfig] = None
    """Configuration with which the CLI can build a Docker image for the Action."""

    image_uri: typing.Optional[str] = None
    """URI to a non-local Docker image. Must already be pushed a registry accessible by the Roboto Platform."""

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

    model_config = ConfigDict(extra="forbid")
