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
    """Settings for building an action's container image from a Dockerfile.

    Carried in ``ActionConfig.docker_config``. Import it from ``roboto.domain.actions.action_config``.
    """

    dockerfile: pathlib.Path = pathlib.Path.cwd() / "Dockerfile"
    """Path to the Dockerfile.

    Defaults to ``Dockerfile`` in the directory the process was in when ``roboto`` was imported.
    """

    context: pathlib.Path = pathlib.Path.cwd()
    """Build context directory. Defaults to the directory the process was in when ``roboto`` was imported."""

    build_args: dict[str, str] = pydantic.Field(default_factory=dict)
    """Build arguments, keyed by name, as ``docker build --build-arg`` takes them."""


class ActionConfig(pydantic.BaseModel):
    """Configuration of an action, as an ``action.json`` file holds it.

    ``roboto actions create --from-file`` reads the file to create or update an action, ``roboto actions
    invoke-local`` reads it to run the action in a local directory, and ``roboto actions init`` generates one for a
    new action.

    Unlike :py:class:`~roboto.domain.actions.ActionRecord`, it has no fields that Roboto sets, such as ``created``,
    ``org_id`` and ``digest``, and none that are set after the action is created, such as ``published`` and
    ``accessibility``. Keys it does not define are ignored. A configuration that sets both ``docker_config`` and
    ``image_uri`` raises ``pydantic.ValidationError``.
    """

    name: str
    """Human-readable name of the action, unique within its organization."""

    compute_requirements: typing.Optional[ComputeRequirements] = None
    """CPU, memory and storage for each invocation of the action.

    ``None`` uses the defaults of :py:class:`~roboto.domain.actions.ComputeRequirements`.
    """

    container_parameters: typing.Optional[ContainerParameters] = None
    """Command, entry point, environment variables and working directory for the action's container.

    ``None`` sets none of them.
    """

    description: typing.Optional[str] = None
    """Human-readable description of the action."""

    inherits: typing.Optional[ActionReference] = None
    """Deprecated. Action this action inherits its configuration from.

    Roboto rejects a request to create or update an action that sets it.
    """

    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Key-value metadata to set on the action."""

    parameters: list[ActionParameter] = pydantic.Field(default_factory=list)
    """Parameters that an invocation of the action can give values for. Defaults to none."""

    requires_downloaded_inputs: typing.Optional[bool] = None
    """Whether Roboto downloads an invocation's input files before the action runs. ``None`` means ``True``."""

    tags: list[str] = pydantic.Field(default_factory=list)
    """Tags to set on the action. Defaults to none."""

    short_description: typing.Optional[str] = None
    """Brief description of the action.

    At most 140 characters (:py:const:`~roboto.domain.actions.action.SHORT_DESCRIPTION_LENGTH`).
    """

    timeout: typing.Optional[int] = None
    """Maximum time an invocation of the action may run, in minutes. ``None`` uses Roboto's default."""

    docker_config: typing.Optional[DockerImageConfig] = None
    """How to build the action's container image from a local Dockerfile. Cannot be set with ``image_uri``.

    ``roboto actions create`` does not build images, and exits with an error when this is set. Build the image with
    ``docker``, push it with ``roboto images push``, and set ``image_uri`` instead. ``roboto actions invoke-local``
    ignores this field and builds the ``Dockerfile`` in the action's directory.
    """

    image_uri: typing.Optional[str] = None
    """URI of the container image the action runs, already pushed to a registry Roboto can pull from.

    Becomes the action's :py:attr:`~roboto.domain.actions.ActionRecord.uri`. Cannot be set with ``docker_config``.
    """

    @classmethod
    def from_file(cls, path: pathlib.Path) -> "ActionConfig":
        """Read an action configuration from a JSON file, such as ``action.json``.

        Args:
            path: Path to the JSON file.

        Raises:
            FileNotFoundError: No file exists at ``path``.
            pydantic.ValidationError: The file is not valid JSON, does not match this model, or sets both
                ``docker_config`` and ``image_uri``.
        """
        if not path.exists():
            raise FileNotFoundError(f"{path.name} not found: {path}")
        return cls.model_validate_json(path.read_text())

    @pydantic.model_validator(mode="before")
    def enforce_invariants(cls, values: dict) -> dict:
        """Reject a configuration that sets both ``docker_config`` and ``image_uri``."""
        if values.get("docker_config") and values.get("image_uri"):
            raise ValueError(
                "'docker_config' and 'image_uri' are mutually exclusive configuration options. "
                "Use 'docker_config' to build a Docker image from a local Dockerfile, "
                "or 'image_uri' to reference a Docker image already pushed to a registry "
                "accessible by the Roboto Platform."
            )
        return values

    model_config = ConfigDict(extra="ignore")
