# Copyright (c) 2024 Roboto Technologies, Inc.
#
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

import collections.abc
import datetime
import enum
import hashlib
import json
import typing

import pydantic

from roboto.pydantic.serializers import (
    field_serializer_user_metadata,
)
from roboto.types import UserMetadata

from ...compat import StrEnum


class Accessibility(StrEnum):
    """Accessibility of an action: who can find and invoke it."""

    Organization = "organization"
    """Members of the organization that owns the action."""

    ActionHub = "action_hub"
    """Every Roboto user, through the Action Hub."""


class ActionParameter(pydantic.BaseModel):
    """A named value that an invocation passes to an action, so one action can run with different settings.

    Roboto rejects an action whose parameters share a name, or that has a parameter that is both required and has
    a default. It rejects an invocation that gives no value for a required parameter, and gives each optional
    parameter the invocation leaves out its default.
    """

    name: str
    """Name of the parameter, unique among the action's parameters."""

    required: bool = False
    """Whether an invocation must give a value for the parameter."""

    description: typing.Optional[str] = None
    """Human-readable description of the parameter."""

    default: typing.Optional[typing.Any] = None
    """Value an invocation gets when it gives none, or ``None`` for no default.

    Accepts any value, but stores it as a string: a string is kept as given, and any other value is written as
    JSON, so ``False`` becomes ``"false"`` and ``["a", "b"]`` becomes ``'["a", "b"]'``.
    """

    model_config = pydantic.ConfigDict(extra="ignore")

    def __eq__(self, other: typing.Any) -> bool:
        if not isinstance(other, ActionParameter):
            return NotImplemented

        return (
            self.name == other.name
            and self.required == other.required
            and self.description == other.description
            and self.default == other.default
        )

    @pydantic.field_validator("default", mode="before")
    @classmethod
    def validate_default(cls, v: typing.Optional[typing.Any]) -> typing.Optional[str]:
        """Convert a ``default`` that is not a string to JSON, or to ``str(v)`` when JSON cannot encode it."""
        if v is None or isinstance(v, str):
            return v

        try:
            return json.dumps(v)
        except TypeError:
            return str(v)


class ActionParameterChangeset(pydantic.BaseModel):
    """Changes to an action's parameters, for :py:meth:`~roboto.domain.actions.Action.update`."""

    put_parameters: list[ActionParameter] = pydantic.Field(default_factory=list)
    """Parameters to add, each replacing any parameter of the same name. Defaults to none."""

    remove_parameters: list[str] = pydantic.Field(default_factory=list)
    """Names of parameters to remove. Defaults to none."""

    class Builder:
        """Builder that collects parameters to put and to remove into an ``ActionParameterChangeset``."""

        __put_parameters: list[ActionParameter]
        __remove_parameters: list[str]

        def __init__(self) -> None:
            self.__put_parameters = []
            self.__remove_parameters = []

        def put_parameter(self, parameter: ActionParameter) -> "ActionParameterChangeset.Builder":
            """Add a parameter to put, and return this builder."""
            self.__put_parameters.append(parameter)
            return self

        def remove_parameter(self, parameter_name: str) -> "ActionParameterChangeset.Builder":
            """Add the name of a parameter to remove, and return this builder."""
            self.__remove_parameters.append(parameter_name)
            return self

        def build(self) -> "ActionParameterChangeset":
            """Return a changeset of the parameters this builder collected."""
            changeset: collections.abc.Mapping = {
                "put_parameters": self.__put_parameters,
                "remove_parameters": self.__remove_parameters,
            }
            return ActionParameterChangeset(**{k: v for k, v in changeset.items() if v})

    def is_empty(self) -> bool:
        """Return whether the changeset has no parameters to put or remove."""
        return not self.put_parameters and not self.remove_parameters


class ActionReference(pydantic.BaseModel):
    """Reference to an action by name, optionally pinned to one version and to the organization that owns it."""

    name: str
    """Name of the action, unique within the organization that owns it."""

    digest: typing.Optional[str] = None
    """Digest of the version of the action to use, or ``None`` for its latest version."""

    owner: typing.Optional[str] = None
    """ID of the organization that owns the action, or ``None`` for the organization that uses the reference."""

    def __eq__(self, other: typing.Any) -> bool:
        if not isinstance(other, ActionReference):
            return NotImplemented

        return self.name == other.name and self.digest == other.digest and self.owner == other.owner

    def __str__(self) -> str:
        return f"{self.owner}/{self.name}" if not self.digest else f"{self.owner}/{self.name}@{self.digest}"


class ExecutorContainer(enum.Enum):
    """Container of an invocation that wrote a log line, as :py:attr:`~roboto.domain.actions.LogRecord.process`.

    The containers run together for each invocation of an action, and are listed here in the order they start.
    """

    LogRouter = "firelens_log_router"
    """Container that forwards the invocation's logs."""

    Monitor = "monitor"
    """Container that enforces the invocation's timeout."""

    Setup = "setup"
    """Container that prepares the action's input before the action runs.

    Downloads the input files unless the action sets ``requires_downloaded_inputs`` to ``False``.
    """

    Action = "action"
    """Container that runs the action's container image."""

    OutputHandler = "output_handler"
    """Container that uploads the files the action wrote to its output directory, once the action succeeds."""


class ComputeRequirements(pydantic.BaseModel):
    """CPU, memory and storage for the container that runs an action.

    Construction raises ``pydantic.ValidationError`` for a value or a ``vCPU`` and ``memory`` combination that is
    not allowed. The organization's plan can also cap each value below the largest one allowed here.
    """

    vCPU: int = 512
    """CPU units for the container, where 1024 units are one vCPU. Defaults to 512.

    One of 256, 512, 1024, 2048, 4096, 8192 or 16384.
    """

    memory: int = pydantic.Field(default=1024, validation_alias=pydantic.AliasChoices("memory_MiB", "memory_mib"))
    """Memory for the container, in MiB. Defaults to 1024.

    The allowed values depend on ``vCPU``:

    - 256: 512, 1024 or 2048.
    - 512: 1024 to 4096, in steps of 1024.
    - 1024: 2048 to 8192, in steps of 1024.
    - 2048: 4096 to 16384, in steps of 1024.
    - 4096: 8192 to 30720, in steps of 1024.
    - 8192: 16384 to 61440, in steps of 4096.
    - 16384: 32768 to 122880, in steps of 8192.

    Also accepted under the keys ``memory_MiB`` and ``memory_mib``.
    """

    gpu: typing.Literal[False] = False
    """Whether to give the container a GPU. Only ``False`` is accepted."""

    storage: int = pydantic.Field(default=21, validation_alias=pydantic.AliasChoices("storage_GiB", "storage_gib"))
    """Storage for the container, in GiB. Defaults to 21, the minimum.

    Also accepted under the keys ``storage_GiB`` and ``storage_gib``.
    """

    @pydantic.model_validator(mode="after")
    def validate_storage_limit(self):
        """Reject compute requirements that set ``storage`` below 21 GiB."""
        if self.storage < 21:
            raise ValueError(f"Unsupported Storage value {self.storage}. Storage must be at least 21 GiB.")
        return self

    @pydantic.model_validator(mode="after")
    def validate_vcpu_mem_combination(self) -> "ComputeRequirements":
        """Reject compute requirements whose ``vCPU`` is not an allowed value, or whose ``memory`` it does not allow."""
        allowed_vpcu = (256, 512, 1024, 2048, 4096, 8192, 16384)
        if self.vCPU not in allowed_vpcu:
            raise ValueError(f"Unsupported vCPU value. Allowed options: {allowed_vpcu}")

        memory = self.memory
        allowed_memory: collections.abc.Sequence[int] = list()
        if self.vCPU == 256:
            allowed_memory = [512, 1024, 2048]
        elif self.vCPU == 512:
            allowed_memory = range(1024, 5 * 1024, 1024)
        elif self.vCPU == 1024:
            allowed_memory = range(2 * 1024, 9 * 1024, 1024)
        elif self.vCPU == 2048:
            allowed_memory = range(4 * 1024, 17 * 1024, 1024)
        elif self.vCPU == 4096:
            allowed_memory = range(8 * 1024, 31 * 1024, 1024)
        elif self.vCPU == 8192:
            allowed_memory = range(16 * 1024, 61 * 1024, 4 * 1024)
        elif self.vCPU == 16384:
            allowed_memory = range(32 * 1024, 121 * 1024, 8 * 1024)
        else:
            raise ValueError(f"Unknown vCPU value {self.vCPU}")

        if memory not in allowed_memory:
            raise ValueError(
                f"Unsupported memory/vCPU combination, allowed memory for {self.vCPU} vCPU: {list(allowed_memory)}"
            )

        return self

    def __eq__(self, other: typing.Any) -> bool:
        if not isinstance(other, ComputeRequirements):
            return NotImplemented

        return (
            self.vCPU == other.vCPU
            and self.memory == other.memory
            and self.gpu == other.gpu
            and self.storage == other.storage
        )

    model_config = pydantic.ConfigDict(
        extra="ignore",
        # Accept memory and storage by field name as well as by their validation aliases. pydantic 2.11 replaces
        # populate_by_name with validate_by_name and validate_by_alias, but the SDK supports pydantic 2.5 and later.
        populate_by_name=True,
    )


class ContainerParameters(pydantic.BaseModel):
    """How to run an action's container image."""

    command: typing.Optional[list[str]] = None
    """Command to run in the container, in place of the image's ``CMD``, or ``None`` to keep the image's."""

    entry_point: typing.Optional[list[str]] = None
    """Entry point of the container, in place of the image's ``ENTRYPOINT``, or ``None`` to keep the image's."""

    env_vars: typing.Optional[dict[str, str]] = None
    """Environment variables to set in the container, keyed by name."""

    workdir: typing.Optional[str] = None
    """Working directory of the container, in place of the image's ``WORKDIR``, or ``None`` to keep the image's."""

    def __eq__(self, other: typing.Any) -> bool:
        if not isinstance(other, ContainerParameters):
            return NotImplemented

        return (
            self.command == other.command
            and self.entry_point == other.entry_point
            and self.env_vars == other.env_vars
            and self.workdir == other.workdir
        )

    model_config = pydantic.ConfigDict(extra="ignore")


class ActionRecord(pydantic.BaseModel):
    """Data record of an action, as the Roboto API returns it.

    An action is a reusable function to process, transform or analyze data in Roboto.
    :py:class:`~roboto.domain.actions.Action` wraps this record with methods that act on the action, and exposes it
    as :py:attr:`~roboto.domain.actions.Action.record`.
    """

    created: datetime.datetime
    """Time the action was created."""

    created_by: str
    """ID of the user who created the action."""

    modified: datetime.datetime
    """Time the action was last modified."""

    modified_by: str
    """ID of the user who last modified the action."""

    name: str
    """Human-readable name of the action, unique within its organization."""

    org_id: str
    """ID of the organization that owns the action."""

    accessibility: Accessibility = Accessibility.Organization
    """Who can find and invoke the action."""

    compute_requirements: typing.Optional[ComputeRequirements] = None
    """CPU, memory and storage for each invocation of the action, or ``None`` if none were set.

    An invocation can override them.
    """

    container_parameters: typing.Optional[ContainerParameters] = None
    """How to run the action's container image. An invocation can override them."""

    description: typing.Optional[str] = None
    """Human-readable description of the action, or ``None`` if it has none."""

    digest: typing.Optional[str] = None
    """Digest that identifies this version of the action.

    When a record is constructed without one, it is set to the result of ``compute_digest``.
    """

    inherits: typing.Optional[ActionReference] = None
    """Deprecated. Action this action inherits its configuration from.

    Roboto rejects a request to create or update an action that sets it.
    """

    metadata: dict[str, typing.Any] = pydantic.Field(default_factory=dict)
    """Key-value metadata on the action.

    Values must be strings, numbers or booleans; serializing the record fails on any other value.
    """

    parameters: list[ActionParameter] = pydantic.Field(default_factory=list)
    """Parameters that an invocation of the action can give values for."""

    published: typing.Optional[datetime.datetime] = None
    """Time the action was published to the Action Hub, or ``None`` if it is not in the Action Hub."""

    requires_downloaded_inputs: typing.Optional[bool] = None
    """Whether Roboto downloads an invocation's input files before the action runs. ``None`` means ``True``."""

    tags: list[str] = pydantic.Field(default_factory=list)
    """Tags on the action."""

    uri: typing.Optional[str] = None
    """URI of the container image the action runs, or ``None`` if none was set."""

    short_description: typing.Optional[str] = None
    """Brief description of the action, or ``None`` if it has none.

    At most 140 characters (:py:const:`~roboto.domain.actions.action.SHORT_DESCRIPTION_LENGTH`).
    """

    timeout: typing.Optional[int] = None
    """Maximum time an invocation of the action may run, in minutes, or ``None`` if the action sets none."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.digest = self.compute_digest() if not self.digest else self.digest

    def compute_digest(self) -> str:
        """Compute a digest of the fields set on this record.

        The digest is a 32-character hexadecimal BLAKE2b hash of the fields given at construction or assigned
        since, written as JSON with sorted keys. Construction assigns ``digest`` when it is not given, so calling
        this method afterwards hashes ``digest`` as well and returns a different value from it.
        """
        hasher = hashlib.blake2b(
            digest_size=16,
            # https://docs.python.org/3.9/library/hashlib.html#personalization
            person=b"ActionRecord",
        )
        digestable = self.model_dump(exclude_unset=True, mode="json")
        hasher.update(json.dumps(digestable, sort_keys=True).encode("utf-8"))
        return hasher.hexdigest()

    @property
    def reference(self) -> ActionReference:
        """Reference to this version of the action, by its name, digest and owning organization."""
        return ActionReference(
            name=self.name,
            digest=self.digest,
            owner=self.org_id,
        )

    @pydantic.field_serializer("metadata")
    def serialize_metadata(self, metadata: dict[str, typing.Any]) -> UserMetadata:
        """Serialize ``metadata`` as a dictionary of strings, numbers and booleans.

        Converts ``decimal.Decimal`` values to ``float``. Pydantic calls this when the record is serialized; use
        ``model_dump`` or ``model_dump_json`` instead.
        """
        return field_serializer_user_metadata(metadata)
