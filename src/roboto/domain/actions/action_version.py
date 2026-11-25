# Copyright (c) 2026 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from __future__ import annotations

import base64
import datetime
import typing

import pydantic

from ...compat import StrEnum
from .action_record import ActionParameter
from .launch_requirements import EgressPosture, LaunchRequirements

DEFAULT_RELEASE_GRANTS: tuple[str, ...] = ("*:read",)
"""The grants a release states when its author names none: its runs may read, and change nothing."""


class Substrate(StrEnum):
    """The compute an action release runs on."""

    Fargate = "fargate"
    """A container started from the release's image, configured by :py:class:`FargateSubstrateConfig`."""

    Microvm = "microvm"
    """A lightweight virtual machine, which runs the release's Python payload."""


class Arch(StrEnum):
    """A CPU architecture."""

    Arm64 = "arm64"
    X86_64 = "x86_64"


class GpuSpec(pydantic.BaseModel):
    """A GPU request. Only substrates that can attach a GPU accept one."""

    count: int = 1
    """How many GPUs."""

    kind: str
    """The GPU model, for example ``"l4"``."""


class ComputeShape(pydantic.BaseModel):
    """The resources each run of a release gets by default.

    The platform rounds a shape to the nearest one the substrate offers, or refuses it.
    """

    memory_mib: int = pydantic.Field(gt=0)
    """Memory in MiB."""

    vcpu: typing.Optional[float] = None
    """Whole or fractional vCPUs, for example ``0.25``, ``0.5`` or ``2``. Unset, the substrate derives it from
    ``memory_mib``."""

    storage_gib: typing.Optional[int] = None
    """Ephemeral disk in GiB. Only substrates with a storage dimension, such as Fargate, accept it."""

    arch: typing.Optional[Arch] = None
    """CPU architecture. Unset means the substrate's native one."""

    gpu: typing.Optional[GpuSpec] = None
    """A GPU, on substrates that offer one."""


class FargateSubstrateConfig(pydantic.BaseModel):
    """How to start a :py:attr:`Substrate.Fargate` release's container."""

    substrate: typing.Literal[Substrate.Fargate] = Substrate.Fargate

    entry_point: typing.Optional[list[str]] = None
    """Overrides the image's ``ENTRYPOINT``."""

    command: typing.Optional[list[str]] = None
    """Overrides the image's ``CMD``."""

    env_vars: dict[str, str] = pydantic.Field(default_factory=dict)
    """Environment variables set in the container."""

    workdir: typing.Optional[str] = None
    """Overrides the image's working directory."""


class MicrovmSubstrateConfig(pydantic.BaseModel):
    """Configuration for a :py:attr:`Substrate.Microvm` release. It has no settings."""

    substrate: typing.Literal[Substrate.Microvm] = Substrate.Microvm


SubstrateConfig = typing.Annotated[
    typing.Union[FargateSubstrateConfig, MicrovmSubstrateConfig],
    pydantic.Field(discriminator="substrate"),
]
"""Substrate-specific configuration; its ``substrate`` must match the release's."""


class DatasetOutputTarget(pydantic.BaseModel):
    """Collect each run's ``$ROBOTO_OUTPUT_DIR`` into a dataset. Needs a substrate that runs Roboto's sidecar."""

    kind: typing.Literal["dataset"] = "dataset"

    dataset_id: str
    """The dataset outputs are uploaded to."""


class ArtifactOutputTarget(pydantic.BaseModel):
    """Collect each run's ``$ROBOTO_OUTPUT_DIR`` as artifacts of that invocation. Every substrate supports it."""

    kind: typing.Literal["artifacts"] = "artifacts"


OutputTarget = typing.Annotated[
    typing.Union[DatasetOutputTarget, ArtifactOutputTarget],
    pydantic.Field(discriminator="kind"),
]
"""Where a release's runs collect their outputs."""


class ReleaseExecutable(pydantic.BaseModel):
    """What a new release runs: a container image, Python code, or both.

    Code is sent as bytes; the platform stores it and records the reference itself.
    """

    image_ref: typing.Optional[str] = None
    """Container image reference, for example ``"my-registry.com/processor:v1.0"``. An image in Roboto's
    registry is pinned to the digest its tag names when the release is created, so pushing the tag
    again does not change what the release runs."""

    payload: typing.Optional[bytes] = None
    """The release's code, at most 1 MiB. Ship anything larger as an image."""

    payload_content_type: str = "text/x-python"
    """Media type of ``payload``, which picks the interpreter that runs it."""

    @pydantic.model_validator(mode="after")
    def _names_something(self) -> ReleaseExecutable:
        if self.image_ref is None and self.payload is None:
            raise ValueError("a release must ship an executable: an image_ref, a payload, or both")
        return self

    @pydantic.field_serializer("payload", when_used="json")
    def _payload_as_base64(self, payload: typing.Optional[bytes]) -> typing.Optional[str]:
        return base64.b64encode(payload).decode("ascii") if payload is not None else None


class CreateReleaseRequest(pydantic.BaseModel):
    """Request payload to publish an action release: what it runs, on what, and with which defaults.

    Releases are immutable and numbered. Publishing one never changes what an existing release runs.
    """

    substrate: Substrate
    """The compute the release runs on."""

    executable: ReleaseExecutable
    """What the release runs."""

    shape: ComputeShape
    """The resources each run gets unless its invocation asks for others."""

    timeout_s_default: typing.Optional[int] = pydantic.Field(default=None, gt=0)
    """How long a run may take, in seconds, unless its invocation sets a timeout. Unset, each run gets its
    organization's default: 30 minutes on the free tier, 12 hours otherwise."""

    grants: list[str] = pydantic.Field(default_factory=lambda: list(DEFAULT_RELEASE_GRANTS), min_length=1)
    """What the release's runs may do in Roboto, as ``entity:verb`` grants. ``*`` matches every entity or
    verb: ``*:read`` reads everything and changes nothing, ``dataset:create`` creates datasets, ``*:*``
    performs every ordinary operation, and ``credential:read`` reads the organization's secrets.

    Defaults to ``["*:read"]``, so an action that writes, such as one that creates topics or uploads
    files, must name grants that allow it. A restricted credential, such as an invocation's, may only
    publish a release whose grants it holds itself."""

    parameters: list[ActionParameter] = pydantic.Field(default_factory=list)
    """Parameters each invocation may set."""

    substrate_config: typing.Optional[SubstrateConfig] = None
    """Substrate-specific configuration, such as a Fargate container's command."""

    requires_downloaded_inputs: bool = True
    """Whether a run's input files are downloaded before it starts."""

    output: typing.Optional[OutputTarget] = None
    """Where runs collect their outputs. Unset, they collect nothing."""

    egress: typing.Optional[EgressPosture] = None
    """Whether runs may reach the public internet. Unset, the substrate's default applies. An invocation
    may override it."""

    launch_requirements: typing.Optional[LaunchRequirements] = None
    """What an invocation needs for the code to work. Unset, nothing is enforced."""

    version: typing.Optional[str] = None
    """The version number to publish, for example ``"1.2.0"``. For an action's first release it defaults
    to ``"1.0.0"``; for a later release, to a patch bump of the highest number the action has used."""


class CreateVersionedActionRequest(pydantic.BaseModel):
    """Request payload to create an action together with its first release."""

    description: typing.Optional[str] = None
    """Detailed description of what the action does."""

    short_description: typing.Optional[str] = None
    """Brief description (max 140 characters) for display purposes."""

    tags: list[str] = pydantic.Field(default_factory=list)
    """Tags for categorizing and searching actions."""

    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Custom key-value metadata."""

    release: CreateReleaseRequest
    """The action's first release."""


class ActionExecutable(pydantic.BaseModel):
    """What a published release runs."""

    image_ref: typing.Optional[str] = None
    """Container image reference, pinned to a digest when the image is in Roboto's registry."""

    payload_ref: typing.Optional[str] = None
    """Content address of the release's code, ``sha256:<hex>``."""

    payload_content_type: typing.Optional[str] = None
    """Media type of the release's code."""


class ActionVersion(pydantic.BaseModel):
    """One immutable, numbered release of an action."""

    action_id: str
    """The action this release belongs to."""

    version: str
    """The version number, for example ``"1.2.3"``."""

    digest: str
    """Hash of the release's content."""

    substrate: Substrate
    """The compute the release runs on."""

    grants: list[str]
    """What the release's runs may do; see :py:attr:`CreateReleaseRequest.grants`."""

    executable: ActionExecutable
    """What the release runs."""

    parameters: list[ActionParameter] = pydantic.Field(default_factory=list)
    """Parameters each invocation may set."""

    shape: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Default resources per run, in :py:class:`ComputeShape`'s fields."""

    substrate_config: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Substrate-specific configuration."""

    timeout_s_default: typing.Optional[int] = None
    """Default run timeout in seconds. Unset, each run gets its organization's default."""

    requires_downloaded_inputs: bool = True
    """Whether a run's input files are downloaded before it starts."""

    output: typing.Optional[dict[str, typing.Any]] = None
    """Where runs collect their outputs, in :py:data:`OutputTarget`'s fields."""

    egress: typing.Optional[EgressPosture] = None
    """Default network posture for runs."""

    launch_requirements: typing.Optional[LaunchRequirements] = None
    """What an invocation needs for the code to work."""

    created: datetime.datetime
    """When the release was published."""

    created_by: str
    """Who published the release."""

    deleted: typing.Optional[datetime.datetime] = None
    """When the release was deleted; unset on a live release."""

    deleted_by: typing.Optional[str] = None
    """Who deleted the release; unset on a live release."""

    replaced_by: typing.Optional[str] = None
    """The version a deleted release's labels moved to."""
