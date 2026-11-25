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
from .action_version import (
    ComputeShape,
    CreateReleaseRequest,
    CreateVersionedActionRequest,
    FargateSubstrateConfig,
    ReleaseExecutable,
    Substrate,
)

CPU_UNITS_PER_VCPU = 1024
"""A v1 file's ``compute_requirements.vCPU`` counts CPU units; a release counts vCPUs."""

V1_GRANTS = ("*:*", "credential:read")
"""What runs of an action created from a v1 file may do unless the file names ``grants``: every ordinary
operation, and reading the organization's secrets. Every action had these grants before releases named their own."""

V1_FIELDS = (
    "compute_requirements",
    "container_parameters",
    "docker_config",
    "grants",
    "image_uri",
    "inherits",
    "parameters",
    "requires_downloaded_inputs",
    "timeout",
)
"""Fields only a v1 file may set. A v2 file states what its action runs inside ``release`` instead."""

SUPPORTED_SCHEMA_VERSIONS = (1, 2)


class ActionConfigExecutable(ReleaseExecutable):
    """What a v2 file's release runs: a container ``image_ref``, or a Python file named by its path.

    The Python file is read when the action is created and sent as the release's ``payload``. The executable
    may name neither when ``roboto actions create --image`` or ``--payload`` supplies the code, as it must
    for a template whose image is pushed at deploy time.
    """

    python: typing.Optional[str] = None
    """Path to a Python file, relative to the ``action.json`` that names it."""

    # Named like ReleaseExecutable's validator so that it replaces that one, which would refuse an executable
    # naming neither an image nor a payload.
    @pydantic.model_validator(mode="after")
    def _names_something(self) -> "ActionConfigExecutable":
        if self.payload is not None:
            raise ValueError("an action.json names its code with 'python', a path to the file, not 'payload'")
        return self


class ActionConfigRelease(CreateReleaseRequest):
    """A v2 file's ``release``: :py:class:`CreateReleaseRequest`, with ``grants`` required and the
    executable allowed to name a Python file."""

    grants: list[str] = pydantic.Field(min_length=1)
    """What the release's runs may do, as ``entity:verb`` grants. Required in a file, so that what an
    action may do is always written down beside it; see :py:attr:`CreateReleaseRequest.grants`."""

    executable: ActionConfigExecutable = pydantic.Field(default_factory=ActionConfigExecutable)
    """What the release runs. Omitted, or naming neither ``image_ref`` nor ``python``, the code must come
    from the command line."""


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
    """An ``action.json`` file: what ``roboto actions create --from-file`` creates an action from, what
    ``roboto actions invoke-local`` runs, and what ``roboto actions init`` templates.

    Two schemas share the file, told apart by ``schema_version``:

    - v2 (``"schema_version": 2``) is the body of ``POST /v1/actions/<name>``
      (:py:class:`CreateVersionedActionRequest`) as a file: ``name``, ``description``, ``short_description``,
      ``tags``, ``metadata``, and ``release``, an :py:class:`ActionConfigRelease`. The field names and units
      are the API's.
    - v1 (no ``schema_version``, or ``1``) is the legacy schema, which describes a container. The SDK
      translates it as the platform translates an action created through ``POST /v1/actions``, so a v1 file
      creates the action it always did.

    A field from the other schema is refused. Unknown fields are ignored.
    """

    schema_version: typing.Optional[int] = None
    """``2`` for the current schema; absent or ``1`` for the legacy one."""

    # Required
    name: str
    """Human-readable name of the action, unique within its organization."""

    # Optional, both schemas
    description: typing.Optional[str] = None
    """Human-readable description of the action."""

    short_description: typing.Optional[str] = None
    """Brief description of the action.

    At most 140 characters (:py:const:`~roboto.domain.actions.action.SHORT_DESCRIPTION_LENGTH`).
    """

    tags: list[str] = pydantic.Field(default_factory=list)
    """Tags to set on the action. Defaults to none."""

    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Key-value metadata to set on the action."""

    # v2 only
    release: typing.Optional[ActionConfigRelease] = None
    """The release to publish. Required in a v2 file."""

    # v1 only
    compute_requirements: typing.Optional[ComputeRequirements] = None
    """CPU, memory and storage for each invocation of the action.

    ``None`` uses the defaults of :py:class:`~roboto.domain.actions.ComputeRequirements`.
    """

    container_parameters: typing.Optional[ContainerParameters] = None
    """Command, entry point, environment variables and working directory for the action's container.

    ``None`` sets none of them.
    """

    grants: typing.Optional[list[str]] = None
    """What the action's runs may do in Roboto, as ``entity:verb`` grants. Unset, they may perform every ordinary
    operation and read the organization's secrets: ``["*:*", "credential:read"]``."""

    inherits: typing.Optional[ActionReference] = None
    """Deprecated. Action this action inherits its configuration from.

    Roboto rejects a request to create or update an action that sets it.
    """

    parameters: list[ActionParameter] = pydantic.Field(default_factory=list)
    """Parameters that an invocation of the action can give values for. Defaults to none."""

    requires_downloaded_inputs: typing.Optional[bool] = None
    """Whether Roboto downloads an invocation's input files before the action runs. ``None`` means ``True``."""

    timeout: typing.Optional[int] = None
    """Default run timeout in minutes. Unset, each run gets its organization's default."""

    # Mutually exclusive, v1 only
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

    @property
    def effective_schema_version(self) -> int:
        """The schema the file is written in: ``1`` or ``2``."""
        return self.schema_version if self.schema_version is not None else 1

    @pydantic.model_validator(mode="before")
    def enforce_invariants(cls, values: typing.Any) -> typing.Any:
        """Reject a file that mixes the two schemas, names an unknown schema, or sets both ``docker_config`` and
        ``image_uri``."""
        if not isinstance(values, dict):
            return values
        schema_version = values.get("schema_version")
        if schema_version is not None and schema_version not in SUPPORTED_SCHEMA_VERSIONS:
            raise ValueError(
                f"schema_version {schema_version!r} is not one this SDK reads; use 2, or omit it for the legacy schema"
            )
        if schema_version == 2:
            # A key holding None or an empty collection is unset: a dumped and re-validated config carries
            # every field, at its default.
            v1_fields = sorted(field for field in V1_FIELDS if values.get(field) not in (None, [], {}))
            if v1_fields:
                raise ValueError(
                    f"a schema_version 2 action.json states what it runs inside 'release', so {v1_fields} "
                    "do not belong at its top level"
                )
            if values.get("release") is None:
                raise ValueError("a schema_version 2 action.json must have a 'release'")
        elif values.get("release") is not None:
            raise ValueError("'release' needs \"schema_version\": 2; a legacy action.json has none")
        if values.get("docker_config") and values.get("image_uri"):
            raise ValueError(
                "'docker_config' and 'image_uri' are mutually exclusive configuration options. "
                "Use 'docker_config' to build a Docker image from a local Dockerfile, "
                "or 'image_uri' to reference a Docker image already pushed to a registry "
                "accessible by the Roboto Platform."
            )
        return values

    def to_create_request(self, base_dir: pathlib.Path) -> CreateVersionedActionRequest:
        """Return the ``POST /v1/actions/<name>`` body this file describes.

        Args:
            base_dir: The directory holding the file, which a v2 executable's ``python`` path is relative to.

        Raises:
            ValueError: A v1 file names no ``image_uri``, or a v2 file's release names no executable; the
                platform needs one to create an action.
            OSError: A v2 file names a Python file that cannot be read.
        """
        return CreateVersionedActionRequest(
            description=self.description,
            short_description=self.short_description,
            tags=self.tags,
            metadata=self.metadata,
            release=self.__v2_release(self.release, base_dir) if self.release is not None else self.__v1_release(),
        )

    def __v1_release(self) -> CreateReleaseRequest:
        """Translate the legacy fields as the platform translates an action created through ``POST /v1/actions``.

        CPU units become vCPUs, minutes become seconds, parameters are sorted by name, an unset
        ``requires_downloaded_inputs`` means ``True``, and the container settings become a Fargate configuration.
        """
        if self.image_uri is None:
            raise ValueError("this action.json names no image_uri; an action needs an image to be created from it")
        compute = self.compute_requirements or ComputeRequirements()
        container = self.container_parameters or ContainerParameters()
        return CreateReleaseRequest(
            substrate=Substrate.Fargate,
            executable=ReleaseExecutable(image_ref=self.image_uri),
            shape=ComputeShape(
                vcpu=compute.vCPU / CPU_UNITS_PER_VCPU, memory_mib=compute.memory, storage_gib=compute.storage
            ),
            timeout_s_default=self.timeout * 60 if self.timeout is not None else None,
            grants=list(self.grants) if self.grants is not None else list(V1_GRANTS),
            parameters=sorted(self.parameters, key=lambda parameter: parameter.name),
            substrate_config=FargateSubstrateConfig(
                entry_point=container.entry_point,
                command=container.command,
                workdir=container.workdir,
                env_vars=container.env_vars or {},
            ),
            requires_downloaded_inputs=(
                self.requires_downloaded_inputs if self.requires_downloaded_inputs is not None else True
            ),
        )

    @staticmethod
    def __v2_release(release: ActionConfigRelease, base_dir: pathlib.Path) -> CreateReleaseRequest:
        executable = release.executable
        if executable.image_ref is None and executable.python is None:
            raise ValueError(
                "this action.json's release names no executable; set release.executable.image_ref or "
                "release.executable.python"
            )
        return CreateReleaseRequest.model_validate(
            {
                **release.model_dump(exclude={"executable"}),
                "executable": ReleaseExecutable(
                    image_ref=executable.image_ref,
                    payload=(base_dir / executable.python).read_bytes() if executable.python is not None else None,
                    payload_content_type=executable.payload_content_type,
                ),
            }
        )

    model_config = ConfigDict(extra="ignore")
